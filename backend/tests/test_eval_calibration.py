"""The judge-calibration statistics are pinned by a synthetic fixture with known answers.

Every "human" answer in this file is a scripted test input in a temp directory,
recorded as reviewer "synthetic-fixture". None of it is, or is written as, a label.
"""
import json
import os
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import calibration as cal
from evals import label

# Rows = human, columns = judge, order must_see / fine / never. Asymmetric on
# purpose so a precision/recall swap fails.
CONFUSION = {
    "must_see": {"must_see": 10, "fine": 5, "never": 0},
    "fine": {"must_see": 2, "fine": 30, "never": 8},
    "never": {"must_see": 0, "fine": 5, "never": 40},
}
# p_o = 80/100; human marginals .15/.40/.45; judge marginals .12/.40/.48
# p_e = .15*.12 + .40*.40 + .45*.48 = .394 -> kappa = .406/.606 = 203/303
KAPPA = float(Fraction(203, 303))
# linear weights 1 / .5 / 0: p_o_w = (80 + .5*20)/100 = .9, p_e_w = .394 + .5*.48 = .634
KAPPA_LINEAR = float(Fraction(266, 366))
KEY = {"must_see": "m", "fine": "f", "never": "n"}


def fixture_rows():
    rows = []
    for human, judged in CONFUSION.items():
        for judge, n in judged.items():
            rows += [{"stratum": f"{judge}/escalated", "human": human, "judge": judge, "effective": judge}] * n
    return rows


def population_for(rows, scale=1):
    counts = {}
    for r in rows:
        counts[r["stratum"]] = counts.get(r["stratum"], 0) + 1
    return {s: n * scale for s, n in counts.items()}


class TestStatistics(unittest.TestCase):

    def test_known_confusion(self):
        rows = fixture_rows()
        res = cal.score_rows(rows, population_for(rows), n_boot=0)
        s = res["sample"]
        self.assertAlmostEqual(s["agreement"], 0.8)
        self.assertAlmostEqual(s["kappa"], KAPPA)
        self.assertAlmostEqual(s["kappa_linear"], KAPPA_LINEAR)
        pc = s["per_class"]
        self.assertAlmostEqual(pc["must_see"]["precision"], 10 / 12)
        self.assertAlmostEqual(pc["must_see"]["recall"], 10 / 15)
        self.assertAlmostEqual(pc["fine"]["precision"], 30 / 40)
        self.assertAlmostEqual(pc["fine"]["recall"], 30 / 40)
        self.assertAlmostEqual(pc["never"]["precision"], 40 / 48)
        self.assertAlmostEqual(pc["never"]["recall"], 40 / 45)

    def test_proportional_weights_equal_the_sample(self):
        rows = fixture_rows()
        res = cal.score_rows(rows, population_for(rows, scale=7), n_boot=0)
        self.assertAlmostEqual(res["population_weighted"]["kappa"], res["sample"]["kappa"])

    def test_weighting_by_stratum_population(self):
        # 10 reviewed rows in each stratum. The big stratum all agrees, the small one
        # all disagrees: the sample says 50%, the population says 1000/1010.
        rows = ([{"stratum": "never/pass1_only", "human": "never", "judge": "never", "effective": "never"}] * 10
                + [{"stratum": "must_see/contested", "human": "fine", "judge": "must_see", "effective": "fine"}] * 10)
        res = cal.score_rows(rows, {"never/pass1_only": 1000, "must_see/contested": 10}, n_boot=0)
        self.assertAlmostEqual(res["sample"]["agreement"], 0.5)
        self.assertAlmostEqual(res["population_weighted"]["agreement"], 1000 / 1010)
        self.assertAlmostEqual(res["population_weighted"]["per_class"]["must_see"]["precision"], 0.0)
        # The secondary comparison is scored against its own field.
        eff = cal.score_rows(rows, {"never/pass1_only": 1000, "must_see/contested": 10}, n_boot=0,
                             judge_field="effective")
        self.assertAlmostEqual(eff["sample"]["agreement"], 1.0)

    def test_bootstrap_interval(self):
        rows = fixture_rows()
        a = cal.score_rows(rows, population_for(rows), n_boot=400, seed=3)
        b = cal.score_rows(rows, population_for(rows), n_boot=400, seed=3)
        lo, hi = a["sample"]["kappa_ci95"]
        self.assertEqual(a["sample"]["kappa_ci95"], b["sample"]["kappa_ci95"])
        self.assertLess(lo, KAPPA)
        self.assertGreater(hi, KAPPA)
        self.assertLess(hi - lo, 0.4)
        perfect = [{"stratum": "fine/escalated", "human": c, "judge": c, "effective": c}
                   for c in ("must_see", "fine", "never") for _ in range(10)]
        p = cal.score_rows(perfect, {"fine/escalated": 30}, n_boot=200)
        self.assertEqual(p["sample"]["kappa"], 1.0)
        self.assertEqual(p["sample"]["kappa_ci95"], [1.0, 1.0])

    def test_single_class_kappa_is_undefined_not_one(self):
        rows = [{"stratum": "fine/escalated", "human": "fine", "judge": "fine", "effective": "fine"}] * 5
        res = cal.score_rows(rows, {"fine/escalated": 5}, n_boot=0)
        self.assertIsNone(res["sample"]["kappa"])


def _article(aid, title):
    return {"id": aid, "title": title, "summary": f"summary {aid}", "content": "",
            "source": "Wire", "published_at": "2026-08-31T00:00:00+00:00"}


class TestSampler(unittest.TestCase):

    def setUp(self):
        self.reader = "READER: Test\n\nIn their own words:\nfixture"
        self.docs = {"snap": {f"a{i}": _article(f"a{i}", f"t{i}") for i in range(40)}}
        rows = []
        for i in range(40):
            lab = ("must_see", "fine", "never")[i % 3]
            rows.append({"article_id": f"a{i}", "url": f"u{i}", "label": lab, "source": "model",
                         "pass1": lab, "pass2": lab if i < 20 else None, "contested": i < 5,
                         "confidence": 0.9, "tags": [], "rationale": f"why {i}", "model": "m"})
        rows.append({"article_id": "a0", "url": "u0", "label": "never", "source": "agent", "tags": []})
        self.rows = {("snap", "p1"): rows}
        blocks = {r["article_id"]: label._article_block(self.docs["snap"][r["article_id"]]) for r in rows}
        ids = [r["article_id"] for r in rows if r["source"] == "model"]
        p2 = [r["article_id"] for r in rows if r["source"] == "model" and r["pass2"]]
        # The cache holds every batch except the last pass-1 batch (a35..a39).
        self.hashes = {cal.judge_prompt_sha(self.reader, [blocks[a] for a in ids[i:i + 5]]) for i in range(0, 35, 5)}
        self.hashes |= {cal.judge_prompt_sha(self.reader, [blocks[a] for a in p2[i:i + 5]]) for i in range(0, len(p2), 5)}

    def population(self, readers=None):
        return cal.build_population(self.rows, self.docs, readers or {"p1": ["wrong reader", self.reader]},
                                    self.hashes, snapshots=["snap"])

    def test_only_cache_proven_rows_are_eligible(self):
        units, chosen, excluded = self.population()
        self.assertEqual(chosen["p1"], self.reader)
        self.assertEqual(len(units), 35)
        self.assertEqual(excluded["unverified_prompt"], 5)
        self.assertNotIn("a37", {u["article_id"] for u in units})
        a0 = next(u for u in units if u["article_id"] == "a0")
        self.assertEqual((a0["stratum"], a0["effective_label"]), ("must_see/contested", "never"))
        a23 = next(u for u in units if u["article_id"] == "a23")
        self.assertEqual(a23["stratum"], "never/pass1_only")
        units, _, _ = self.population({"p1": ["wrong reader"]})
        self.assertEqual(units, [])

    def test_draw_is_seeded_capped_and_blind(self):
        units, chosen, _ = self.population()
        alloc = {s: 3 for s in {u["stratum"] for u in units}}
        alloc["must_see/contested"] = 99
        a, strata = cal.draw(units, alloc, seed=11)
        b, _ = cal.draw(units, alloc, seed=11)
        c, _ = cal.draw(units, alloc, seed=12)
        self.assertEqual([u["unit_id"] for u in a], [u["unit_id"] for u in b])
        self.assertNotEqual([u["unit_id"] for u in a], [u["unit_id"] for u in c])
        self.assertEqual(strata["must_see/contested"]["drawn"], strata["must_see/contested"]["population"])
        with tempfile.TemporaryDirectory() as tmp:
            cal.write_sample(Path(tmp), a, strata, chosen, seed=11)
            visible = (Path(tmp) / "sample.jsonl").read_text()
            for u in a:
                self.assertNotIn(u["judge"]["rationale"], visible)
            self.assertNotIn("stratum", visible)
            self.assertNotIn('"label"', visible)
            manifest = json.loads((Path(tmp) / "manifest.json").read_text())
            self.assertEqual(manifest["seed"], 11)
            self.assertEqual(manifest["n"], len(a))

    def test_unallocated_stratum_is_an_error(self):
        units, _, _ = self.population()
        with self.assertRaises(ValueError):
            cal.draw(units, {"fine/escalated": 1}, seed=1)


class TestPipeline(unittest.TestCase):
    """sample -> blind review -> score on a fixture whose answers realise CONFUSION."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.truth = {}
        picked = []
        i = 0
        for human, judged in CONFUSION.items():
            for judge, n in judged.items():
                for _ in range(n):
                    i += 1
                    aid = f"a{i:03d}"
                    self.truth[aid] = human
                    picked.append({
                        "unit_id": f"snap/p1/{aid}", "snapshot": "snap", "persona": "p1", "article_id": aid,
                        "url": f"u{aid}", "stratum": f"{judge}/escalated",
                        "article_block": label._article_block(_article(aid, f"title {aid}")),
                        "judge": {"label": judge, "pass1": judge, "pass2": judge, "model": "m",
                                  "confidence": 0.9, "tags": [], "rationale": f"JUDGE-RATIONALE-{aid}"},
                        "effective_label": judge, "effective_source": "model",
                    })
        strata = {s: {"population": n, "requested": n, "drawn": n}
                  for s, n in population_for([{"stratum": p["stratum"]} for p in picked]).items()}
        cal.write_sample(self.out, picked, strata, {"p1": "READER: fixture"}, seed=5)

    def tearDown(self):
        self.tmp.cleanup()

    def run_review(self, limit=None):
        out, truth = self.out, self.truth
        log: list[str] = []
        state = {"current": None, "answered": 0}

        def emit(line):
            log.append(line)
            if "judge said" in line:
                # The reveal must come after the answer is durable on disk.
                recorded = {a["sample_id"] for a in cal._read_jsonl(out / "adjudications.jsonl")}
                self.assertIn(state["sid"], recorded)

        def answer(prompt):
            if prompt.startswith("  optional note"):
                return "fixture note" if state["answered"] == 1 else ""
            if limit is not None and state["answered"] >= limit:
                return "q"
            shown = "\n".join(log)
            aid = shown.rsplit("ARTICLE id=", 1)[1].split("\n", 1)[0]
            sid = next(s["sample_id"] for s in cal._read_jsonl(out / "sample.jsonl") if s["article_id"] == aid)
            self.assertNotIn(f"JUDGE-RATIONALE-{aid}", shown, "judge verdict leaked before the answer")
            state.update(sid=sid)
            state["answered"] += 1
            return KEY[truth[aid]]

        cal.review(out, "synthetic-fixture", input_fn=answer, emit=emit, clock=iter(range(0, 10**6, 3)).__next__)
        return log

    def test_end_to_end_statistics(self):
        with self.assertRaises(cal.InsufficientReviews):
            cal.score(self.out, min_reviewed=1, write=False)
        self.run_review(limit=40)
        with self.assertRaisesRegex(cal.InsufficientReviews, "40 reviewed rows .* at least 100"):
            cal.score(self.out, min_reviewed=100, write=False)
        self.run_review()       # resumes where it stopped
        rep = cal.score(self.out, min_reviewed=100, n_boot=300)
        judge = rep["judge"]["sample"]
        self.assertEqual(rep["n_reviewed"], 100)
        self.assertAlmostEqual(judge["agreement"], 0.8)
        self.assertAlmostEqual(judge["kappa"], KAPPA)
        self.assertAlmostEqual(judge["per_class"]["must_see"]["precision"], 10 / 12)
        self.assertAlmostEqual(judge["per_class"]["must_see"]["recall"], 10 / 15)
        self.assertEqual(rep["seconds_per_row"]["median"], 3)
        self.assertTrue((self.out / "report.md").read_text().startswith("# Judge vs human adjudication"))

        adj = cal._read_jsonl(self.out / "adjudications.jsonl")
        self.assertEqual(len({a["sample_id"] for a in adj}), 100)
        for field in ("reviewer", "reviewed_at", "elapsed_s", "evidence_sha256", "sample_sha256"):
            self.assertTrue(all(field in a for a in adj), field)
        notes = cal._read_jsonl(self.out / "notes.jsonl")
        self.assertTrue(all(n["post_reveal"] for n in notes))

    def test_tampered_sample_is_refused(self):
        path = self.out / "sample.jsonl"
        path.write_text(path.read_text().replace("title a001", "title edited"))
        with self.assertRaisesRegex(ValueError, "does not match the manifest"):
            cal.score(self.out, min_reviewed=0, write=False)

    def test_redraw_over_reviews_is_refused(self):
        (self.out / "adjudications.jsonl").write_text('{"sample_id": "s001"}\n')
        with self.assertRaises(FileExistsError):
            cal.write_sample(self.out, [], {}, {}, seed=1)

    def test_cli_refuses_piped_input(self):
        import subprocess
        r = subprocess.run([sys.executable, "-m", "evals.calibration", "review", "--out", str(self.out),
                            "--reviewer", "x"], input="m\n", capture_output=True, text=True,
                           cwd=Path(__file__).resolve().parents[1])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("interactive terminal", r.stderr)
        self.assertFalse((self.out / "adjudications.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
