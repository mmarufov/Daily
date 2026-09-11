#!/usr/bin/env python3
"""Small, resumable S3 wire pilot, with an aggregate USD 5 maximum.

Default execution replays private cache only. --paid permits cache misses with
an API key from the environment or --env-file. No production database writes.
This measures wire/contract behavior and cost, NOT semantic quality or readiness.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys
import time

BACKEND = Path(__file__).resolve().parents[1]
WORKSPACE = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.services.understanding_contract import DEFAULT_RECIPE, build_evidence, digest
from app.services.understanding_provider import OpenAIUnderstandingProvider, ProviderFailure
from evals.llm_cache import BudgetExceeded, CacheMiss, CachingUnderstandingProvider, _atomic_write_bytes
from evals.snapshot import load_snapshot, verify_snapshot

MODELS = ("gpt-4.1-mini-2025-04-14", "gpt-4o-mini-2024-07-18")


def select_articles(snapshot: str, count: int = 20) -> list[dict]:
    if type(count) is not int or not 1 <= count <= 20:
        raise ValueError("Pilot count must be in [1, 20]")
    if not verify_snapshot(snapshot):
        raise ValueError("Frozen corpus content hash failed")
    buckets = defaultdict(list)
    seen = set()
    for row in load_snapshot(snapshot)["articles"]:
        url = (row.get("url") or "").split("#", 1)[0]
        if not url or url in seen:
            continue
        seen.add(url)
        # Snapshot bodies predate S2 provenance: only original snapshot metadata
        # is eligible. Never manufacture publisher artifacts or candidate IDs.
        evidence = build_evidence({"id": f"{snapshot}:{row['id']}", "url": row.get("url"),
            "title": row.get("title"), "summary": row.get("summary"),
            "source_name": row.get("source"), "published_at": row.get("published_at"),
            "language": row.get("language")})
        if evidence["sufficient"]:
            buckets[(evidence["metadata"]["source_name"], evidence["language"] or "unknown",
                     evidence["evidence_tier"])].append(evidence)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: digest(row["article_id"]))
    result = []
    while len(result) < count and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key]:
                result.append(buckets[key].pop())
                if len(result) == count:
                    break
    if len(result) != count:
        raise ValueError("Not enough distinct eligible frozen articles")
    return result


async def run_pilot(provider, *, snapshot: str, count: int, cache_dir: Path,
                    output: Path, budget_usd: float, paid: bool,
                    ledger_dir: Path = WORKSPACE / ".context/s3/pilot-ledger") -> dict:
    cache = CachingUnderstandingProvider(provider, cache_dir=cache_dir,
                                         budget_usd=budget_usd, offline=not paid,
                                         ledger_dir=ledger_dir)
    articles = select_articles(snapshot, count)
    identity = {"snapshot": snapshot, "inputs": [item["input_hash"] for item in articles],
                "recipes": [{**DEFAULT_RECIPE, "model": model} for model in MODELS],
                "budget_usd": budget_usd, "cache_dir": str(cache_dir.resolve())}
    report = {"schema_version": 1, "identity": identity, "identity_hash": digest(identity),
              "semantic_quality_validated": False, "production_ready": False,
              "limitations": ["Unlabeled pilot; valid spans and parsing do not establish semantic accuracy.",
                  "Title and summary only; legacy bodies have no verified S2 provenance.",
                  "Source/language/evidence stratification is a small operational sample, not global coverage.",
                  "No independent entity/place candidates supplied; unresolved mentions are expected."],
              "article_count": len(articles), "results": [], "status": "running"}
    if output.exists():
        previous = json.loads(output.read_text())
        if previous.get("identity_hash") != report["identity_hash"]:
            raise ValueError("Pilot output belongs to another frozen run; choose another output path")
        report["results"] = previous["results"]
    # Replay every stage on resume. Cached failures replay without extra spend;
    # uncertain requests without cache remain blocked by the durable ledger.
    def persist():
        report["budget"] = cache.budget_report()
        report["cache_hits"] = cache.hits
        report["cache_misses"] = cache.misses
        report["cache_keys"] = sorted(cache.touched)
        report["outcome_counts"] = dict(Counter(row["outcome"] for row in report["results"]))
        _atomic_write_bytes(output, (json.dumps(report, indent=2, allow_nan=False) + "\n").encode())
    persist()
    for article in articles:
        stages = [(model, "facets") for model in MODELS] + [(MODELS[0], "embedding")]
        for model, stage in stages:
            recipe = {**DEFAULT_RECIPE, "model": model}
            item = {"article_id": article["article_id"], "input_hash": article["input_hash"],
                    "source": article["metadata"]["source_name"], "evidence_tier": article["evidence_tier"],
                    "stage": stage, "model": model if stage == "facets" else recipe["embedding_model"]}
            start = time.monotonic()
            hits = cache.hits
            stop = False
            try:
                outcome = await cache.generate(article, recipe, stage)
                item.update(outcome="contract_valid", payload=outcome.payload,
                            usage_usd=outcome.usage_usd, request_id=outcome.request_id)
            except ProviderFailure as failure:
                item.update(outcome="provider_failure", failure=failure.kind,
                            usage_usd=failure.usage_usd, ambiguous=failure.ambiguous,
                            request_id=failure.request_id, retryable=failure.retryable)
                stop = failure.provider_wide
            except CacheMiss:
                item.update(outcome="offline_cache_miss")
            except BudgetExceeded:
                item.update(outcome="budget_or_uncertain_request_blocked")
                stop = True
            except Exception as error:
                # Exception text can contain provider URLs/credentials. Store only
                # the safe type and retain the reservation; never blindly retry.
                item.update(outcome="unexpected_failure", error_type=type(error).__name__)
                stop = True
            finally:
                item["elapsed_seconds"] = round(time.monotonic() - start, 4)
                item["cache_hit"] = cache.hits > hits
                if "outcome" in item:
                    report["results"] = [prior for prior in report["results"] if
                        (prior["article_id"], prior["stage"], prior["model"]) !=
                        (item["article_id"], item["stage"], item["model"])]
                    report["results"].append(item)
                persist()
            if stop:
                report["status"] = "stopped"
                persist()
                return report
    report["status"] = "completed" if all(row["outcome"] == "contract_valid" for row in report["results"]) else "completed_with_failures"
    persist()
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--snapshot", default="2026-09-02")
    result.add_argument("--count", type=int, default=20)
    result.add_argument("--budget-usd", type=float, default=5.0, help="Fixed across resumes, maximum 5 USD")
    result.add_argument("--cache-dir", type=Path, default=WORKSPACE / ".context/s3/pilot-cache")
    result.add_argument("--output", type=Path, default=WORKSPACE / ".context/s3/pilot.json")
    result.add_argument("--env-file", type=Path, default=BACKEND / ".env")
    result.add_argument("--paid", action="store_true", help="Permit misses within the durable aggregate budget")
    return result


async def main() -> int:
    args = parser().parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    # A placeholder permits request construction in offline mode; no API call is
    # possible through the offline wrapper on a miss.
    key = os.environ.get("OPENAI_API_KEY") if args.paid else "offline-cache-only"
    provider = OpenAIUnderstandingProvider(key or "")
    try:
        report = await run_pilot(provider, snapshot=args.snapshot, count=args.count,
                                 cache_dir=args.cache_dir, output=args.output,
                                 budget_usd=args.budget_usd, paid=args.paid)
    finally:
        await provider.aclose()
    print(json.dumps({"status": report["status"], "outcome_counts": report["outcome_counts"],
                      "budget": report["budget"], "output": str(args.output)}))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except (ValueError, ProviderFailure) as error:
        print(json.dumps({"status": "configuration_error", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
