"""Frozen corpus snapshots.

`build_corpus.py` fetches live feeds into `corpus.json`, which changes every time
it runs. Labels and scorecards are only meaningful against a corpus that never
changes, so a snapshot is an explicit, committed, content-hashed freeze of one
corpus. Every runner also freezes "now" to the snapshot's `frozen_now`, so
lookback windows and freshness scores do not drift as the snapshot ages.

    python -m evals.snapshot freeze 2026-08-31            # corpus.json -> snapshots/
    python -m evals.snapshot derive 2026-08-31 2026-08-31-quiet --clusters ev-01
    python -m evals.snapshot list
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

EVALS = Path(__file__).resolve().parent
SNAPSHOTS = EVALS / "snapshots"
MANIFEST = SNAPSHOTS / "manifest.json"
CORPUS = EVALS / "corpus.json"


def _read_manifest() -> list[dict]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return []


def _write_manifest(entries: list[dict]) -> None:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(entries, indent=1) + "\n")


def snapshot_path(name: str) -> Path:
    return SNAPSHOTS / f"{name}.json.gz"


def list_snapshots() -> list[dict]:
    return _read_manifest()


def load_snapshot(name: str) -> dict:
    p = snapshot_path(name)
    if not p.exists():
        raise FileNotFoundError(f"no snapshot {name!r} in {SNAPSHOTS}")
    with gzip.open(p, "rt", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("snapshot", {})["name"] = name
    return data


def frozen_now(data: dict) -> datetime:
    raw = (data.get("snapshot") or {}).get("frozen_now") or data.get("built_at")
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def save_snapshot(data: dict, name: str, note: str = "") -> Path:
    articles = data["articles"]
    ids = [a["id"] for a in articles]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate article ids in snapshot")
    meta = dict(data.get("snapshot") or {})
    meta.setdefault("frozen_now", data.get("built_at") or datetime.now(timezone.utc).isoformat())
    meta.setdefault("derived_from", None)
    meta.setdefault("removed_clusters", [])
    meta["name"] = name
    data = {**data, "snapshot": meta}

    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sha = hashlib.sha256(payload).hexdigest()
    out = snapshot_path(name)
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the archive byte-identical for identical content.
    with gzip.GzipFile(filename=str(out), mode="wb", compresslevel=9, mtime=0) as f:
        f.write(payload)

    entries = [e for e in _read_manifest() if e["name"] != name]
    entries.append({
        "name": name, "file": out.name, "built_at": data.get("built_at"),
        "frozen_now": meta["frozen_now"], "n_articles": len(articles), "sha256": sha,
        "derived_from": meta["derived_from"], "removed_clusters": meta["removed_clusters"],
        "note": note,
    })
    entries.sort(key=lambda e: e["name"])
    _write_manifest(entries)
    return out


def verify_snapshot(name: str) -> bool:
    entry = next((e for e in _read_manifest() if e["name"] == name), None)
    if entry is None:
        return False
    with gzip.open(snapshot_path(name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest() == entry["sha256"]


def freeze(corpus_path: Path = CORPUS, name: str | None = None, note: str = "") -> Path:
    data = json.loads(Path(corpus_path).read_text())
    if name is None:
        name = data["built_at"][:10]
    return save_snapshot(data, name, note=note)


def _clone_ground_truth(name: str, new_name: str, remove_article_ids: set[str],
                        removed_clusters: list[str]) -> None:
    """Clone labels for a derived corpus and remove references to deleted articles."""
    source = EVALS / "labels" / name
    if not source.exists():
        raise FileNotFoundError(f"no labels for source snapshot {name}: {source}")
    target = EVALS / "labels" / new_name
    if target.exists():
        raise FileExistsError(f"labels already exist for derived snapshot {new_name}: {target}")
    target.mkdir(parents=True)
    for path in source.iterdir():
        out = target / path.name
        if path.suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            rows = [row for row in rows if row.get("article_id") not in remove_article_ids]
            out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        elif path.name == "events.json":
            doc = json.loads(path.read_text())
            clusters = []
            for cluster in doc.get("clusters", []):
                if cluster.get("id") in removed_clusters:
                    continue
                cluster = dict(cluster)
                cluster["article_ids"] = [i for i in cluster.get("article_ids", []) if i not in remove_article_ids]
                if cluster["article_ids"]:
                    clusters.append(cluster)
            doc["snapshot"] = new_name
            doc["clusters"] = clusters
            out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        else:
            shutil.copy2(path, out)


def derive(name: str, new_name: str, remove_article_ids: set[str],
           removed_clusters: list[str] | None = None, note: str = "", quiet: bool = False) -> Path:
    """A derived snapshot with named articles removed, e.g. a 'quiet day' with the
    world-critical cluster deleted so the false-major rate can be measured."""
    data = load_snapshot(name)
    unknown = set(remove_article_ids) - {a["id"] for a in data["articles"]}
    if unknown:
        raise ValueError(f"removal set contains ids not in the snapshot: {sorted(unknown)[:5]}")
    data["articles"] = [a for a in data["articles"] if a["id"] not in remove_article_ids]
    removed_clusters = list(removed_clusters or [])
    data["snapshot"] = {**data["snapshot"], "derived_from": name,
                        "removed_clusters": removed_clusters, "quiet": quiet}
    _clone_ground_truth(name, new_name, remove_article_ids, removed_clusters)
    return save_snapshot(data, new_name, note=note)


def cluster_article_ids(name: str, cluster_ids: list[str]) -> set[str]:
    events = EVALS / "labels" / name / "events.json"
    if not events.exists():
        raise FileNotFoundError(f"no events labels for {name}: {events}")
    doc = json.loads(events.read_text())
    out: set[str] = set()
    for c in doc.get("clusters", []):
        if c["id"] in cluster_ids:
            out.update(c["article_ids"])
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Frozen corpus snapshots")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("name", nargs="?")
    f.add_argument("--corpus", default=str(CORPUS))
    f.add_argument("--note", default="")
    d = sub.add_parser("derive")
    d.add_argument("name")
    d.add_argument("new_name")
    d.add_argument("--clusters", nargs="*", default=[], help="event cluster ids from labels/<name>/events.json")
    d.add_argument("--articles", nargs="*", default=[], help="explicit article ids to drop")
    d.add_argument("--quiet", action="store_true", help="mark as a quiet-day corpus for false-major scoring")
    d.add_argument("--note", default="")
    sub.add_parser("list")
    args = ap.parse_args()

    if args.cmd == "freeze":
        p = freeze(Path(args.corpus), args.name, note=args.note)
        print(f"froze -> {p}")
    elif args.cmd == "derive":
        ids = set(args.articles) | (cluster_article_ids(args.name, args.clusters) if args.clusters else set())
        p = derive(args.name, args.new_name, ids, removed_clusters=args.clusters, note=args.note, quiet=args.quiet)
        print(f"derived -> {p} (removed {len(ids)} articles)")
    else:
        for e in list_snapshots():
            ok = "ok " if verify_snapshot(e["name"]) else "BAD"
            print(f"{ok} {e['name']:<24} {e['n_articles']:>5} articles  frozen_now={e['frozen_now']}"
                  f"{'  derived from ' + e['derived_from'] if e.get('derived_from') else ''}")
