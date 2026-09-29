"""Human calibration of the label judge.

The S0 ground truth (`evals/labels/`) was written by a two-pass model judge
(`label.bootstrap`: gpt-4.1-mini over the pool, gpt-4.1 over the contested set)
and partly overridden by an agent pass. None of it has a human source. This
module measures how far that judge can be trusted, against one human reviewer:

    sample   stratified draw over judge verdict x review path, seeded, and only
             from rows whose exact judge prompt is proven by the committed LLM
             cache (messages_sha256), so the reviewer sees what the judge saw
    protocol presentation order and intra-rater re-pass subset, both seeded and
             committed before the first answer (the draw itself is untouched)
    review   one row at a time, blind: the judge's verdict is written to disk
             only after the human answer is, then revealed. `--repass` re-labels
             the pre-registered subset with nothing revealed at all
    score    raw agreement, Cohen's kappa, per-class precision/recall for the
             judge against the human, stratified bootstrap CI; refuses to run
             on too few reviewed rows

    python -m evals.calibration sample --out evals/calibration/2026-09-29
    python -m evals.calibration protocol --out evals/calibration/2026-09-29
    python -m evals.calibration review --out evals/calibration/2026-09-29 --reviewer <name>
    python -m evals.calibration review --out evals/calibration/2026-09-29 --reviewer <name> --repass
    python -m evals.calibration score  --out evals/calibration/2026-09-29

Nothing here writes a human label except `review`, and `review` refuses to run
unless stdin is an interactive terminal. No model is called anywhere.

Files in a calibration directory:

    manifest.json        seed, allocation, population and draw per stratum, input hashes
    readers.json         persona -> the exact READER block the judge saw
    sample.jsonl         what the reviewer sees: ids and the exact ARTICLE block
    judge.jsonl          hidden until answered: the judge verdict per sample row
    protocol.json        presentation order and the re-pass subset, bound to sample.jsonl's hash
    adjudications.jsonl  append-only human answers with provenance
    repass.jsonl         append-only second answers on the re-pass subset, first answers hidden
    notes.jsonl          optional post-reveal notes on disagreements
    report.json / .md    written by `score`
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import label  # noqa: E402

EVALS = Path(__file__).resolve().parent
CACHE_LLM = EVALS / ".cache" / "llm"

SEED = 20260929
CLASSES = label.LABEL_VALUES                      # ("must_see", "fine", "never")
ORDINAL = {"never": 0, "fine": 1, "must_see": 2}   # for the linear-weighted kappa only

# `2026-08-31-quiet` is derived from `2026-08-31` (snapshot.derive) and 3,310 of its
# 3,606 rows repeat a 2026-08-31 judgement, so it is last in dedupe order.
SNAPSHOTS = ("2026-08-31", "2026-09-02", "2026-08-31-quiet")

# Commit #65 (b15c6ef7) renamed five persona display names *after* labelling, so the
# current persona files no longer reproduce those prompts. The parent revision does.
PERSONA_REVS = ("HEAD", "b15c6ef7^")

# Review path of a judge verdict in the two-pass bootstrap:
#   pass1_only  mid-tier model only, never escalated
#   escalated   re-labelled by the top-tier model, both passes agreed
#   contested   re-labelled and the two passes disagreed (`contested` in the row)
PATHS = ("pass1_only", "escalated", "contested")

# Draw per stratum, capped at the stratum population. Weighted toward the cells
# where the judge is most likely wrong: every must_see (the bootstrap escalated
# all of them), every contested row, and the escalations that agreed. The two
# pass1_only cells are the largest by far and the most confident, so they get
# enough rows to catch a systematic miss, not enough to dominate the sample.
ALLOCATION = {
    "must_see/contested": 7,
    "must_see/escalated": 60,
    "fine/contested": 55,
    "never/contested": 40,
    "fine/escalated": 30,
    "never/escalated": 36,
    "fine/pass1_only": 36,
    "never/pass1_only": 36,
}

# Intra-rater re-pass: a seeded random subset, re-labelled blind to the first answer
# after a minimum gap, so reviewer consistency is measured and not assumed.
REPASS_N = 40
REPASS_MIN_GAP_HOURS = 12

DEFAULT_MIN_REVIEWED = 100
DEFAULT_BOOTSTRAP = 2000


class InsufficientReviews(RuntimeError):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# ---------------------------------------------------------------------------
# Evidence: prove what the judge saw
# ---------------------------------------------------------------------------

def judge_prompt_sha(reader: str, article_blocks: list[str]) -> str:
    """`messages_sha256` exactly as `llm_cache` computes it for a `label._label_batch` call."""
    user = reader + "\n\nARTICLES:\n\n" + "\n\n".join(article_blocks)
    messages = [{"role": "system", "content": label.LABEL_SYSTEM}, {"role": "user", "content": user}]
    return hashlib.sha256(json.dumps(messages, sort_keys=True, default=str).encode()).hexdigest()


def cached_prompt_hashes(cache_dir: Path = CACHE_LLM) -> set[str]:
    out: set[str] = set()
    for path in cache_dir.glob("*/*.json"):
        try:
            sha = (json.loads(path.read_text()).get("request") or {}).get("messages_sha256")
        except (ValueError, OSError):
            continue
        if sha:
            out.add(sha)
    return out


def verified_rows(rows: list[dict], blocks: dict[str, str], reader: str, hashes: set[str]) -> set[str]:
    """Article ids whose final judge verdict came from a prompt present in the cache.

    `label.bootstrap` writes rows in pool order and batches five at a time, pass 2
    over the escalated subset in the same order. A row is verified when the batch
    that produced its *final* verdict (pass 2 if escalated, else pass 1) hashes to a
    cached request: then the reader block and article block are byte-identical to
    what the judge was sent.
    """
    def hits(ids: list[str]) -> set[str]:
        batches = [ids[i:i + 5] for i in range(0, len(ids), 5)]
        ok: set[str] = set()
        for batch in batches:
            if all(a in blocks for a in batch) and judge_prompt_sha(reader, [blocks[a] for a in batch]) in hashes:
                ok.update(batch)
        return ok

    p1 = hits([r["article_id"] for r in rows])
    p2 = hits([r["article_id"] for r in rows if r.get("pass2") is not None])
    return {r["article_id"] for r in rows
            if (r["article_id"] in p2 if r.get("pass2") is not None else r["article_id"] in p1)}


def review_path(row: dict) -> str:
    if row.get("contested"):
        return "contested"
    return "escalated" if row.get("pass2") is not None else "pass1_only"


def build_population(label_rows: dict[tuple[str, str], list[dict]],
                     docs: dict[str, dict[str, dict]],
                     readers: dict[str, list[str]],
                     hashes: set[str],
                     snapshots: Iterable[str] = SNAPSHOTS) -> tuple[list[dict], dict[str, str], dict]:
    """All model judgements eligible for calibration.

    label_rows: (snapshot, persona) -> rows as stored in `<persona>.jsonl`
    docs:       snapshot -> article id -> snapshot article
    readers:    persona -> candidate READER blocks (current and pre-rename)
    Returns (units, reader block chosen per persona, exclusion counts).
    """
    units: list[dict] = []
    chosen: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    excluded = {"duplicate_judgement": 0, "unverified_prompt": 0, "missing_article": 0}
    for snap in snapshots:
        for persona in sorted(readers):
            rows = label_rows.get((snap, persona)) or []
            model = [r for r in rows if r.get("source") == "model"]
            if not model:
                continue
            agent = {r["article_id"]: r for r in rows if r.get("source") == "agent"}
            by_id = docs[snap]
            blocks = {r["article_id"]: label._article_block(by_id[r["article_id"]])
                      for r in model if r["article_id"] in by_id}
            best, ok = None, set()
            for reader in readers[persona]:
                v = verified_rows(model, blocks, reader, hashes)
                if len(v) > len(ok):
                    best, ok = reader, v
            if best is not None:
                if persona in chosen and chosen[persona] != best:
                    raise ValueError(f"judge saw two different READER blocks for {persona}")
                chosen[persona] = best
            for r in model:
                aid = r["article_id"]
                if aid not in by_id:
                    excluded["missing_article"] += 1
                    continue
                if aid not in ok:
                    excluded["unverified_prompt"] += 1
                    continue
                key = (persona, r.get("url") or f"{snap}/{aid}")
                if key in seen:
                    excluded["duplicate_judgement"] += 1
                    continue
                seen.add(key)
                a = agent.get(aid)
                units.append({
                    "unit_id": f"{snap}/{persona}/{aid}",
                    "snapshot": snap, "persona": persona, "article_id": aid, "url": r.get("url"),
                    "stratum": f"{r['label']}/{review_path(r)}",
                    "article_block": blocks[aid],
                    "judge": {
                        "label": r["label"], "pass1": r.get("pass1"), "pass2": r.get("pass2"),
                        "model": r.get("model"), "confidence": r.get("confidence"),
                        "tags": r.get("tags") or [], "rationale": r.get("rationale") or "",
                    },
                    # What evals score against today (label.load_labels: agent over model).
                    "effective_label": a["label"] if a else r["label"],
                    "effective_source": "agent" if a else "model",
                })
    return units, chosen, excluded


def draw(units: list[dict], allocation: dict[str, int], seed: int) -> tuple[list[dict], dict]:
    """Seeded stratified draw. The persona-grouped order written to sample.jsonl is
    kept so the committed draw reproduces byte for byte, but it is not the order a
    reviewer sees: that comes from `protocol.json`, fully shuffled, so fatigue is not
    confounded with persona and stopping early does not drop whole personas."""
    rng = random.Random(f"calibration:{seed}")
    by_stratum: dict[str, list[dict]] = {}
    for u in sorted(units, key=lambda u: u["unit_id"]):
        by_stratum.setdefault(u["stratum"], []).append(u)
    unknown = set(by_stratum) - set(allocation)
    if unknown:
        raise ValueError(f"population has strata with no allocation: {sorted(unknown)}")
    picked: list[dict] = []
    strata = {}
    for name in sorted(allocation):
        pop = by_stratum.get(name, [])
        n = min(allocation[name], len(pop))
        picked += rng.sample(pop, n)
        strata[name] = {"population": len(pop), "requested": allocation[name], "drawn": n}
    personas = sorted({u["persona"] for u in picked})
    rng.shuffle(personas)
    rank = {p: i for i, p in enumerate(personas)}
    rng.shuffle(picked)
    picked.sort(key=lambda u: rank[u["persona"]])
    return picked, strata


def write_sample(out: Path, picked: list[dict], strata: dict, readers: dict[str, str],
                 seed: int, extra: dict | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("adjudications.jsonl", "notes.jsonl"):
        if (out / name).exists() and (out / name).read_text().strip():
            raise FileExistsError(f"{out / name} already holds reviews; refusing to redraw under them")
    sample, judge = [], []
    for i, u in enumerate(picked, 1):
        sid = f"s{i:03d}"
        sample.append({"sample_id": sid, "order": i, "snapshot": u["snapshot"], "persona": u["persona"],
                       "article_id": u["article_id"], "url": u["url"], "article_block": u["article_block"],
                       "article_sha256": _sha(u["article_block"])})
        judge.append({"sample_id": sid, "unit_id": u["unit_id"], "stratum": u["stratum"], **u["judge"],
                      "effective_label": u["effective_label"], "effective_source": u["effective_source"]})
    used = {u["persona"] for u in picked}
    readers = {p: readers[p] for p in sorted(used)}
    (out / "readers.json").write_text(json.dumps(
        {p: {"reader_block": r, "sha256": _sha(r)} for p, r in readers.items()}, indent=1, ensure_ascii=False) + "\n")
    _write_jsonl(out / "sample.jsonl", sample)
    _write_jsonl(out / "judge.jsonl", judge)
    manifest = {
        "seed": seed,
        "n": len(sample),
        "strata": strata,
        "allocation": {k: v["requested"] for k, v in strata.items()},
        "judge": {"pass1_model": label.PASS1_MODEL, "pass2_model": label.PASS2_MODEL,
                  "verdict": "final two-pass model label (pass2 if escalated, else pass1)"},
        "files": {name: file_sha(out / name) for name in ("sample.jsonl", "judge.jsonl", "readers.json")},
        **(extra or {}),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    write_protocol(out, seed)


def make_protocol(sample_ids: list[str], sample_sha: str, seed: int, repass_n: int = REPASS_N) -> dict:
    """Presentation order and the intra-rater subset, each from its own seeded stream,
    so neither depends on the other or on anything a reviewer has answered."""
    ids = sorted(sample_ids)
    order = list(ids)
    random.Random(f"calibration-order:{seed}").shuffle(order)
    rng = random.Random(f"calibration-repass:{seed}")
    subset = rng.sample(ids, min(repass_n, len(ids)))
    repass_order = list(subset)
    rng.shuffle(repass_order)
    return {"sample_sha256": sample_sha, "seed": seed, "order": order,
            "repass": {"n": len(subset), "sample_ids": sorted(subset), "order": repass_order,
                       "min_gap_hours": REPASS_MIN_GAP_HOURS}}


def write_protocol(out: Path, seed: int) -> dict:
    """Pre-register the protocol for an existing draw. Refuses once any answer exists,
    because an order or subset chosen after answers is no longer pre-registered."""
    for name in ("adjudications.jsonl", "repass.jsonl"):
        if (out / name).exists() and (out / name).read_text().strip():
            raise FileExistsError(f"{out / name} already holds answers; the protocol must precede them")
    sample, _, manifest = load_sample(out, require_protocol=False)
    proto = make_protocol([s["sample_id"] for s in sample], manifest["files"]["sample.jsonl"], seed)
    (out / "protocol.json").write_text(json.dumps(proto, indent=1) + "\n")
    return proto


def load_protocol(out: Path, sample: list[dict], manifest: dict) -> dict:
    proto = json.loads((out / "protocol.json").read_text())
    if proto["sample_sha256"] != manifest["files"]["sample.jsonl"]:
        raise ValueError("protocol.json was written for a different sample.jsonl")
    ids = sorted(s["sample_id"] for s in sample)
    if sorted(proto["order"]) != ids:
        raise ValueError("protocol.json order is not a permutation of the sample")
    rp = proto["repass"]
    if sorted(rp["order"]) != rp["sample_ids"] or not set(rp["sample_ids"]) <= set(ids):
        raise ValueError("protocol.json re-pass subset is inconsistent with the sample")
    return proto


def _persona_at(rev: str, key: str) -> dict | None:
    from evals.personas import as_persona
    r = subprocess.run(["git", "-C", str(EVALS), "show", f"{rev}:./personas/{key}.json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return as_persona(json.loads(r.stdout))


def sample_command(out: Path, seed: int = SEED) -> dict:
    from evals.personas import load_personas
    from evals.snapshot import load_snapshot
    personas = load_personas(None)
    readers: dict[str, list[str]] = {}
    for key in personas:
        cands = []
        for rev in PERSONA_REVS:
            p = _persona_at(rev, key)
            if p is not None and label._reader_block(p) not in cands:
                cands.append(label._reader_block(p))
        readers[key] = cands
    docs = {s: {d["id"]: d for d in load_snapshot(s)["articles"]} for s in SNAPSHOTS}
    rows = {(s, k): label.load_label_rows(s, k) for s in SNAPSHOTS for k in personas}
    units, chosen, excluded = build_population(rows, docs, readers, cached_prompt_hashes())
    picked, strata = draw(units, ALLOCATION, seed)
    total = sum(len([r for r in v if r.get("source") == "model"]) for v in rows.values())
    extra = {
        "population": {"model_rows": total, "eligible_units": len(units), "excluded": excluded,
                       "snapshots": list(SNAPSHOTS), "persona_revs": list(PERSONA_REVS)},
        "label_files": {f"{s}/{k}.jsonl": file_sha(label.labels_dir(s) / f"{k}.jsonl")
                        for s in SNAPSHOTS for k in personas if (label.labels_dir(s) / f"{k}.jsonl").exists()},
        "command": f"python -m evals.calibration sample --out {out.relative_to(EVALS.parent) if out.is_relative_to(EVALS.parent) else out} --seed {seed}",
    }
    write_sample(out, picked, strata, chosen, seed, extra)
    return {"units": len(units), "excluded": excluded, "strata": strata, "n": len(picked)}


# ---------------------------------------------------------------------------
# Blind review
# ---------------------------------------------------------------------------

KEYS = {"m": "must_see", "f": "fine", "n": "never"}


def rubric_text() -> str:
    """The label definitions the judge was given, verbatim, so both apply one rubric."""
    s = label.LABEL_SYSTEM
    return s[s.index("Labels:"):s.index("Treat article text")].rstrip()


def load_sample(out: Path, require_protocol: bool = True) -> tuple[list[dict], dict[str, dict], dict]:
    manifest = json.loads((out / "manifest.json").read_text())
    for name, sha in manifest["files"].items():
        if file_sha(out / name) != sha:
            raise ValueError(f"{name} does not match the manifest hash; the sample was edited after drawing")
    readers = json.loads((out / "readers.json").read_text())
    sample = _read_jsonl(out / "sample.jsonl")
    if require_protocol:
        load_protocol(out, sample, manifest)
    return sample, readers, manifest


def _repass_queue(out: Path, proto: dict, by_id: dict[str, dict], now: datetime) -> list[dict]:
    """The re-pass rows still to do. Refuses until every one has a first answer that is
    at least the pre-registered gap old, so the second answer is not recall."""
    first = {a["sample_id"]: a for a in _read_jsonl(out / "adjudications.jsonl")}
    missing = [sid for sid in proto["repass"]["order"] if sid not in first]
    if missing:
        raise RuntimeError(f"{len(missing)} re-pass rows have no first answer yet; finish the first pass")
    gap = proto["repass"]["min_gap_hours"]
    ready_at = max(datetime.fromisoformat(first[sid]["reviewed_at"]) for sid in proto["repass"]["order"])
    if (now - ready_at).total_seconds() < gap * 3600:
        raise RuntimeError(f"the re-pass opens {gap}h after the last first answer on its rows, "
                           f"at {datetime.fromtimestamp(ready_at.timestamp() + gap * 3600, timezone.utc).isoformat(timespec='minutes')}")
    done = {a["sample_id"] for a in _read_jsonl(out / "repass.jsonl")}
    return [by_id[sid] for sid in proto["repass"]["order"] if sid not in done]


def review(out: Path, reviewer: str, input_fn: Callable[[str], str] = input,
           emit: Callable[[str], None] = print, clock: Callable[[], float] = time.monotonic,
           dry_run: bool = False, repass: bool = False,
           now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Blind adjudication loop. The judge verdict is read from `judge.jsonl` only after
    the human answer has been appended and fsynced to `adjudications.jsonl`.

    With `repass`, the pre-registered subset is shown again in its own shuffled order and
    answers go to `repass.jsonl`. Nothing is revealed: not the judge, not the first answer."""
    if not reviewer.strip():
        raise ValueError("--reviewer is required")
    sample, readers, manifest = load_sample(out)
    proto = load_protocol(out, sample, manifest)
    proto_sha = file_sha(out / "protocol.json")
    by_id = {s["sample_id"]: s for s in sample}
    adj_path, notes_path = out / "adjudications.jsonl", out / "notes.jsonl"
    if repass:
        adj_path = out / "repass.jsonl"
        first = {a["sample_id"]: a for a in _read_jsonl(out / "adjudications.jsonl")}
        queue = _repass_queue(out, proto, by_id, now())
        total = proto["repass"]["n"]
        position = {sid: i for i, sid in enumerate(proto["repass"]["order"], 1)}
    else:
        done = {a["sample_id"] for a in _read_jsonl(adj_path)}
        queue = [by_id[sid] for sid in proto["order"] if sid not in done]
        total = len(sample)
        position = {sid: i for i, sid in enumerate(proto["order"], 1)}
    sample_sha = manifest["files"]["sample.jsonl"]
    emit(f"{total - len(queue)} of {total} already {'re-labelled' if repass else 'reviewed'}, {len(queue)} to go.")
    if repass:
        emit("Re-pass: label each row fresh. Neither the judge nor your first answer will be shown.")
    emit("m = must_see   f = fine   n = never   s = skip   r = reader again   h = rubric   q = quit")
    emit("\n" + rubric_text())
    words = []
    last_persona = None
    answered = 0
    for s in queue:
        reader = readers[s["persona"]]["reader_block"]
        emit("\n" + "=" * 96)
        if s["persona"] != last_persona:
            emit(reader)
            emit("-" * 96)
            words.append(len(reader.split()))
            last_persona = s["persona"]
        emit(f"[{position[s['sample_id']]}/{total}]  {s['sample_id']}")
        emit(s["article_block"])
        words.append(len(s["article_block"].split()))
        if dry_run:
            continue
        started = clock()
        while True:
            try:
                ans = input_fn("  your label > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "q"
            if ans == "r":
                emit(reader)
            elif ans == "h":
                emit(rubric_text())
            elif ans in KEYS or ans in ("s", "q"):
                break
        if ans == "q":
            break
        elapsed = round(clock() - started, 1)
        record = {
            "sample_id": s["sample_id"],
            "human_label": KEYS.get(ans),
            "skipped": ans == "s",
            "reviewer": reviewer,
            "os_user": getpass.getuser(),
            "reviewed_at": now().isoformat(timespec="seconds"),
            "elapsed_s": elapsed,
            "evidence_sha256": _sha(reader + "\n" + s["article_block"]),
            "sample_sha256": sample_sha,
            "protocol_sha256": proto_sha,
            "position": position[s["sample_id"]],
            "judge_hidden_until_recorded": True,
            "stdin_tty": sys.stdin.isatty(),
        }
        if repass:
            record["first_answer_hidden"] = True
            record["hours_since_first"] = round(
                (datetime.fromisoformat(record["reviewed_at"])
                 - datetime.fromisoformat(first[s["sample_id"]]["reviewed_at"])).total_seconds() / 3600, 2)
        with adj_path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        answered += 1
        if record["skipped"] or repass:
            continue
        # Only now look at the judge.
        j = next(r for r in _read_jsonl(out / "judge.jsonl") if r["sample_id"] == s["sample_id"])
        agree = j["label"] == record["human_label"]
        emit(f"  recorded {record['human_label'].upper()} in {elapsed}s.  judge said {j['label'].upper()}"
             f"  (pass1={j['pass1']} pass2={j['pass2']} conf={j['confidence']})"
             f"  {'AGREE' if agree else 'DISAGREE'}")
        emit(f"  judge why: {j['rationale']}")
        if not agree:
            note = input_fn("  optional note on the disagreement (enter to skip) > ").strip()
            if note:
                with notes_path.open("a") as f:
                    f.write(json.dumps({"sample_id": s["sample_id"], "reviewer": reviewer,
                                        "noted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                        "post_reveal": True, "note": note}, ensure_ascii=False) + "\n")
        if answered % 25 == 0:
            times = [a["elapsed_s"] for a in _read_jsonl(adj_path)]
            emit(f"  -- {answered} this session, median {statistics.median(times):.0f}s per row --")
    return {"shown": len(queue), "answered": answered, "words": words}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _metrics(pairs: list[tuple[str, str, float]]) -> dict:
    """pairs of (human, judge, weight). Weight 1 everywhere is the plain sample statistic."""
    k = len(CLASSES)
    idx = {c: i for i, c in enumerate(CLASSES)}
    cm = [[0.0] * k for _ in range(k)]           # cm[human][judge]
    for h, j, w in pairs:
        cm[idx[h]][idx[j]] += w
    total = sum(map(sum, cm))
    if total <= 0:
        return {"n_weight": 0.0}
    p = [[c / total for c in row] for row in cm]
    rows = [sum(r) for r in p]
    cols = [sum(p[i][j] for i in range(k)) for j in range(k)]
    p_o = sum(p[i][i] for i in range(k))
    p_e = sum(rows[i] * cols[i] for i in range(k))
    kappa = (p_o - p_e) / (1 - p_e) if p_e < 1 else None
    # Linear agreement weights on the ordinal scale never < fine < must_see.
    ordv = [ORDINAL[c] for c in CLASSES]
    span = max(ordv) - min(ordv)
    wt = [[1 - abs(ordv[i] - ordv[j]) / span for j in range(k)] for i in range(k)]
    pw_o = sum(wt[i][j] * p[i][j] for i in range(k) for j in range(k))
    pw_e = sum(wt[i][j] * rows[i] * cols[j] for i in range(k) for j in range(k))
    kappa_w = (pw_o - pw_e) / (1 - pw_e) if pw_e < 1 else None
    per_class = {}
    for c in CLASSES:
        i = idx[c]
        judged = sum(cm[h][i] for h in range(k))
        actual = sum(cm[i])
        per_class[c] = {
            "precision": cm[i][i] / judged if judged else None,
            "recall": cm[i][i] / actual if actual else None,
            "judge_count": judged, "human_count": actual,
        }
    return {"n_weight": total, "agreement": p_o, "kappa": kappa, "kappa_linear": kappa_w,
            "per_class": per_class,
            "confusion_human_by_judge": {h: {j: cm[idx[h]][idx[j]] for j in CLASSES} for h in CLASSES}}


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    pos = (len(xs) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def score_rows(rows: list[dict], population: dict[str, int], n_boot: int = DEFAULT_BOOTSTRAP,
               seed: int = SEED, judge_field: str = "judge") -> dict:
    """rows: {stratum, human, judge, effective}. Returns sample and population-weighted metrics
    with stratified-bootstrap 95% intervals on kappa."""
    by_stratum: dict[str, list[dict]] = {}
    for r in rows:
        by_stratum.setdefault(r["stratum"], []).append(r)
    weight = {s: population[s] / len(rs) for s, rs in by_stratum.items()}

    def compute(groups: dict[str, list[dict]]) -> tuple[dict, dict]:
        flat = [r for rs in groups.values() for r in rs]
        sample = _metrics([(r["human"], r[judge_field], 1.0) for r in flat])
        weighted = _metrics([(r["human"], r[judge_field], weight[r["stratum"]]) for r in flat])
        return sample, weighted

    sample, weighted = compute(by_stratum)
    rng = random.Random(f"calibration-bootstrap:{seed}")
    boots_s, boots_w = [], []
    for _ in range(n_boot):
        g = {s: [rs[rng.randrange(len(rs))] for _ in rs] for s, rs in sorted(by_stratum.items())}
        bs, bw = compute(g)
        if bs.get("kappa") is not None:
            boots_s.append(bs["kappa"])
        if bw.get("kappa") is not None:
            boots_w.append(bw["kappa"])
    if n_boot:
        sample["kappa_ci95"] = [_pct(boots_s, 0.025), _pct(boots_s, 0.975)] if boots_s else None
        weighted["kappa_ci95"] = [_pct(boots_w, 0.025), _pct(boots_w, 0.975)] if boots_w else None
    covered = sum(population[s] for s in by_stratum)
    weighted["population_covered"] = covered
    weighted["population_total"] = sum(population.values())
    return {"sample": sample, "population_weighted": weighted,
            "per_stratum": {s: {"reviewed": len(rs), "population": population[s],
                                "agreement": sum(r["human"] == r[judge_field] for r in rs) / len(rs)}
                            for s, rs in sorted(by_stratum.items())}}


def intra_rater(out: Path, proto: dict, n_boot: int = DEFAULT_BOOTSTRAP, seed: int = SEED) -> dict | None:
    """The reviewer against themself on the pre-registered re-pass subset. None until a
    second answer exists. Rows skipped in either pass drop out of the pairs and are counted."""
    second = _read_jsonl(out / "repass.jsonl")
    if not second:
        return None
    first = {a["sample_id"]: a for a in _read_jsonl(out / "adjudications.jsonl")}
    allowed = set(proto["repass"]["sample_ids"])
    seen: set[str] = set()
    for a in second:
        if a["sample_id"] not in allowed:
            raise ValueError(f"re-pass answer for {a['sample_id']}, which is not in the pre-registered subset")
        if a["sample_id"] in seen:
            raise ValueError(f"two re-pass answers for {a['sample_id']}")
        seen.add(a["sample_id"])
    pairs = [(first[a["sample_id"]]["human_label"], a["human_label"], 1.0) for a in second
             if a.get("human_label") in CLASSES and first.get(a["sample_id"], {}).get("human_label") in CLASSES]
    res = _metrics(pairs)
    rng = random.Random(f"calibration-intra-bootstrap:{seed}")
    boots = []
    for _ in range(n_boot if pairs else 0):
        k = _metrics([pairs[rng.randrange(len(pairs))] for _ in pairs]).get("kappa")
        if k is not None:
            boots.append(k)
    gaps = [a["hours_since_first"] for a in second if "hours_since_first" in a]
    return {"n_subset": proto["repass"]["n"], "n_answered": len(second), "n_pairs": len(pairs),
            "hours_since_first": {"median": statistics.median(gaps), "min": min(gaps)} if gaps else None,
            "agreement": res.get("agreement"), "kappa": res.get("kappa"),
            "kappa_ci95": [_pct(boots, 0.025), _pct(boots, 0.975)] if boots else None,
            "kappa_linear": res.get("kappa_linear"),
            "confusion_first_by_second": res.get("confusion_human_by_judge")}


def score(out: Path, min_reviewed: int = DEFAULT_MIN_REVIEWED, n_boot: int = DEFAULT_BOOTSTRAP,
          seed: int | None = None, write: bool = True) -> dict:
    sample, _, manifest = load_sample(out)
    proto = load_protocol(out, sample, manifest)
    seed = manifest["seed"] if seed is None else seed
    ids = {s["sample_id"] for s in sample}
    judge = {j["sample_id"]: j for j in _read_jsonl(out / "judge.jsonl")}
    adjudications = _read_jsonl(out / "adjudications.jsonl")
    seen: set[str] = set()
    for a in adjudications:
        if a["sample_id"] not in ids:
            raise ValueError(f"adjudication for unknown sample row {a['sample_id']}")
        if a["sample_id"] in seen:
            raise ValueError(f"two adjudications for {a['sample_id']}")
        if a.get("sample_sha256") != manifest["files"]["sample.jsonl"]:
            raise ValueError(f"adjudication {a['sample_id']} was recorded against a different sample")
        seen.add(a["sample_id"])
    reviewed = [a for a in adjudications if not a.get("skipped") and a.get("human_label") in CLASSES]
    if len(reviewed) < min_reviewed:
        raise InsufficientReviews(
            f"{len(reviewed)} reviewed rows (of {len(sample)} sampled, {len(adjudications)} answered "
            f"incl. skips); scoring needs at least {min_reviewed}. Refusing to report a kappa.")
    rows = [{"stratum": judge[a["sample_id"]]["stratum"], "human": a["human_label"],
             "judge": judge[a["sample_id"]]["label"], "effective": judge[a["sample_id"]]["effective_label"]}
            for a in reviewed]
    population = {s: v["population"] for s, v in manifest["strata"].items()}
    times = [a["elapsed_s"] for a in reviewed]
    report = {
        "n_sampled": len(sample),
        "n_answered": len(adjudications),
        "n_skipped": sum(1 for a in adjudications if a.get("skipped")),
        "n_reviewed": len(reviewed),
        "reviewers": sorted({a["reviewer"] for a in reviewed}),
        "seconds_per_row": {"median": statistics.median(times), "mean": statistics.mean(times),
                            "total_minutes": sum(times) / 60},
        "min_reviewed": min_reviewed, "bootstrap": n_boot, "seed": seed,
        "judge": score_rows(rows, population, n_boot, seed, "judge"),
        # Secondary: the labels evals actually score against (agent overrides applied).
        "effective_labels": score_rows(rows, population, n_boot, seed, "effective"),
        "intra_rater": intra_rater(out, proto, n_boot, seed),
        "inputs": {name: file_sha(out / name) for name in
                   ("manifest.json", "protocol.json", "sample.jsonl", "judge.jsonl", "readers.json",
                    "adjudications.jsonl", "repass.jsonl") if (out / name).exists()},
    }
    if write:
        (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
        (out / "report.md").write_text(render_report(report))
    return report


def _f(x: float | None, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_report(r: dict) -> str:
    lines = ["# Judge vs human adjudication", "",
             f"Reviewed {r['n_reviewed']} of {r['n_sampled']} sampled rows ({r['n_skipped']} skipped) "
             f"by {', '.join(r['reviewers'])}. Median {r['seconds_per_row']['median']:.1f}s per row, "
             f"{r['seconds_per_row']['total_minutes']:.0f} minutes total. "
             f"Bootstrap B={r['bootstrap']}, seed {r['seed']}.", ""]
    for title, key in (("Model judge (final two-pass verdict)", "judge"),
                       ("Effective labels (agent overrides applied; what evals score against)", "effective_labels")):
        block = r[key]
        lines += [f"## {title}", "", "| scope | agreement | kappa | 95% CI | linear-weighted kappa |",
                  "|---|---|---|---|---|"]
        for scope in ("sample", "population_weighted"):
            m = block[scope]
            ci = m.get("kappa_ci95")
            lines.append(f"| {scope} | {_f(m['agreement'])} | {_f(m['kappa'])} | "
                         f"{'n/a' if not ci else f'{ci[0]:.3f} to {ci[1]:.3f}'} | {_f(m['kappa_linear'])} |")
        lines += ["", "| class | precision (sample) | recall (sample) | precision (weighted) | recall (weighted) |",
                  "|---|---|---|---|---|"]
        for c in CLASSES:
            s, w = block["sample"]["per_class"][c], block["population_weighted"]["per_class"][c]
            lines.append(f"| {c} | {_f(s['precision'])} | {_f(s['recall'])} | {_f(w['precision'])} | {_f(w['recall'])} |")
        lines += ["", "Confusion (sample counts, rows = human, columns = judge):", "",
                  "| human \\ judge | " + " | ".join(CLASSES) + " |", "|---" * (len(CLASSES) + 1) + "|"]
        cm = block["sample"]["confusion_human_by_judge"]
        for h in CLASSES:
            lines.append(f"| {h} | " + " | ".join(f"{cm[h][j]:.0f}" for j in CLASSES) + " |")
        lines += ["", "| stratum | reviewed | population | agreement |", "|---|---|---|---|"]
        for s, v in block["per_stratum"].items():
            lines.append(f"| {s} | {v['reviewed']} | {v['population']} | {_f(v['agreement'])} |")
        lines.append("")
    ir = r.get("intra_rater")
    lines += ["## Intra-rater (reviewer against themself)", ""]
    if not ir:
        lines += ["Re-pass not done yet.", ""]
    else:
        ci = ir["kappa_ci95"]
        gap = ir["hours_since_first"]
        lines += [f"{ir['n_pairs']} pairs from the pre-registered {ir['n_subset']}-row subset "
                  f"({ir['n_answered']} re-labelled"
                  + (f", median {gap['median']:.1f}h and at least {gap['min']:.1f}h after the first answer" if gap else "")
                  + ").", "",
                  "| agreement | kappa | 95% CI | linear-weighted kappa |", "|---|---|---|---|",
                  f"| {_f(ir['agreement'])} | {_f(ir['kappa'])} | "
                  f"{'n/a' if not ci else f'{ci[0]:.3f} to {ci[1]:.3f}'} | {_f(ir['kappa_linear'])} |", ""]
        if ir["confusion_first_by_second"]:
            cm = ir["confusion_first_by_second"]
            lines += ["Rows = first answer, columns = second answer:", "",
                      "| first \\ second | " + " | ".join(CLASSES) + " |", "|---" * (len(CLASSES) + 1) + "|"]
            lines += [f"| {h} | " + " | ".join(f"{cm[h][j]:.0f}" for j in CLASSES) + " |" for h in CLASSES]
            lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Calibrate the label judge against human adjudication")
    ap.add_argument("cmd", choices=["sample", "protocol", "review", "score"])
    ap.add_argument("--out", type=Path, required=True, help="calibration directory")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--reviewer", default="")
    ap.add_argument("--dry-run", action="store_true", help="review: print every row, record nothing")
    ap.add_argument("--repass", action="store_true", help="review: re-label the pre-registered subset, nothing revealed")
    ap.add_argument("--min-reviewed", type=int, default=DEFAULT_MIN_REVIEWED)
    ap.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    args = ap.parse_args(argv)
    out = args.out.resolve()

    if args.cmd == "sample":
        res = sample_command(out, args.seed)
        print(json.dumps(res, indent=1))
    elif args.cmd == "protocol":
        proto = write_protocol(out, args.seed)
        print(f"order: {len(proto['order'])} rows; re-pass subset: {proto['repass']['n']} rows, "
              f"opens {proto['repass']['min_gap_hours']}h after the first pass")
    elif args.cmd == "review":
        if args.dry_run:
            res = review(out, args.reviewer or "dry-run", dry_run=True, emit=lambda _: None)
            w = res["words"]
            print(f"{res['shown']} rows, {sum(w)} words of evidence, median {statistics.median(w):.0f} per block")
            return
        if not sys.stdin.isatty():
            sys.exit("review reads answers from an interactive terminal only; piped input is refused")
        try:
            review(out, args.reviewer, repass=args.repass)
        except RuntimeError as e:
            sys.exit(str(e))
    else:
        try:
            report = score(out, args.min_reviewed, args.bootstrap)
        except InsufficientReviews as e:
            sys.exit(str(e))
        print(render_report(report))


if __name__ == "__main__":
    main()
