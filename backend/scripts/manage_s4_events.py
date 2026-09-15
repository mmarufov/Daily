#!/usr/bin/env python3
"""Explicit S4 operations. Mutations require --apply; credentials use an env name.

No paid provider calls, schema installation on requests, approval manufacture or
automatic production activation. Errors print classes only, never driver text.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.rows import dict_row

from app.services import event_repository as repo
from app.services.event_contract import Source, digest, timestamp


COMMANDS = ("status", "migrate", "register", "enable", "disable", "configure", "pause",
            "backfill", "source", "replay", "coverage", "promote")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=COMMANDS)
    p.add_argument("--database-env", default="DATABASE_URL")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--recipe")
    p.add_argument("--recipe-file", type=Path)
    p.add_argument("--expected-generation", type=int)
    p.add_argument("--max-rows", type=int, default=100)
    p.add_argument("--after")
    p.add_argument("--submissions-enabled", action="store_true")
    p.add_argument("--delivery-enabled", action="store_true")
    p.add_argument("--daily-budget-usd", default="0")
    p.add_argument("--monthly-budget-usd", default="0")
    p.add_argument("--article-id")
    p.add_argument("--source-file", type=Path)
    p.add_argument("--reviewed-by")
    p.add_argument("--job-id", type=int)
    p.add_argument("--observed-through")
    p.add_argument("--verified", action="store_true")
    p.add_argument("--report", type=Path)
    p.add_argument("--bindings", type=Path)
    p.add_argument("--operations", type=Path)
    return p


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _json_file(path):
    if path is None:
        raise ValueError("required evidence file missing")
    if path.stat().st_size > 2_000_000:
        raise ValueError("management document exceeds size limit")
    def invalid_constant(_):
        raise ValueError("non-finite JSON constant")
    value = json.loads(path.read_text(), object_pairs_hook=_object, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("management document must be an object")
    return value


def _validate(args):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.database_env):
        raise ValueError("database environment variable name required")
    if not 1 <= args.max_rows <= 10000:
        raise ValueError("maximum rows must be 1..10000")
    if args.after:
        uuid.UUID(args.after)
    if args.recipe is not None and not re.fullmatch(r"[0-9a-f]{64}", args.recipe):
        raise ValueError("recipe must be a SHA-256 identity")
    if args.command in ("enable", "disable", "backfill", "promote") and args.recipe is None:
        raise ValueError("explicit recipe required")
    if args.command in ("enable", "disable", "configure", "pause", "source", "replay", "coverage", "promote"):
        if args.expected_generation is None or args.expected_generation < 1:
            raise ValueError("explicit positive expected generation required")
    documents = {}
    if args.command == "register":
        documents["recipe"] = _json_file(args.recipe_file)
        if set(documents["recipe"]) != set(repo.DEFAULT_RECIPE):
            raise ValueError("explicit complete recipe definition required")
        identifier = digest(documents["recipe"])
        if args.recipe is not None and args.recipe != identifier:
            raise ValueError("recipe file identity mismatch")
        args.recipe = identifier
    if args.command == "configure":
        day, month = repo._money(args.daily_budget_usd), repo._money(args.monthly_budget_usd)
        if args.submissions_enabled and not 0 < day <= month:
            raise ValueError("explicit positive daily and monthly budgets required")
    if args.command in ("source", "coverage") and (not args.reviewed_by or not args.reviewed_by.strip()):
        raise ValueError("explicit reviewer required")
    if args.command == "source":
        if not args.article_id:
            raise ValueError("explicit article identity required")
        uuid.UUID(args.article_id)
        documents["source"] = Source.model_validate(_json_file(args.source_file)).model_dump()
    if args.command == "coverage":
        if args.verified and not args.observed_through:
            raise ValueError("verified coverage requires observed watermark")
        if args.observed_through:
            timestamp(args.observed_through)
    if args.command == "replay" and (args.job_id is None or args.job_id < 1):
        raise ValueError("positive explicit job identity required")
    if args.command == "promote":
        documents = {name: _json_file(getattr(args, name)) for name in ("report", "bindings", "operations")}
    return documents


def main(argv=None):
    args = parser().parse_args(argv)
    documents = _validate(args)
    dsn = os.environ.get(args.database_env)
    if not dsn:
        raise ValueError("database environment is not configured")
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        # Only the database name/server version identify the read target. Never
        # print DSN, username, password, hostname, evidence text or provider key.
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            target = conn.execute("SELECT current_database() AS database, current_setting('server_version_num') AS postgres_version").fetchone()
        if args.command == "status":
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                state = repo.status(conn)
            print(json.dumps({"target": target, "status": state}, default=str, indent=2))
            return
        if not args.apply:
            print(json.dumps({"target": target, "mode": "dry_run", "command": args.command,
                "recipe": args.recipe, "expected_generation": args.expected_generation,
                "max_rows": args.max_rows, "note": "No mutation, provider call or approval performed."}, default=str))
            return
        outcome = None
        if args.command == "migrate":
            repo.ensure_schema(conn)
        elif args.command == "register":
            outcome = repo.register_recipe(conn, documents["recipe"], enabled=False)
        elif args.command in ("enable", "disable"):
            repo.set_recipe_enabled(conn, args.recipe, args.command == "enable", expected_generation=args.expected_generation)
        elif args.command == "configure":
            repo.configure(conn, submissions_enabled=args.submissions_enabled, delivery_enabled=args.delivery_enabled,
                daily_budget_usd=args.daily_budget_usd, monthly_budget_usd=args.monthly_budget_usd,
                expected_generation=args.expected_generation)
        elif args.command == "pause":
            # Pause submissions independently. CAS in configure prevents applying
            # these previously read fields over a concurrent control change.
            control = conn.execute("SELECT * FROM public.event_control").fetchone()
            repo.configure(conn, submissions_enabled=False, delivery_enabled=control["delivery_enabled"],
                daily_budget_usd=control["daily_budget_usd"], monthly_budget_usd=control["monthly_budget_usd"],
                expected_generation=args.expected_generation)
        elif args.command == "source":
            repo.set_source(conn, args.article_id, documents["source"], expected_generation=args.expected_generation,
                            reviewed_by=args.reviewed_by)
        elif args.command == "coverage":
            repo.set_coverage(conn, observed_through=args.observed_through, verified=args.verified,
                              expected_generation=args.expected_generation, reviewed_by=args.reviewed_by)
        elif args.command == "replay":
            outcome = repo.replay(conn, args.job_id, expected_generation=args.expected_generation)
        elif args.command == "promote":
            repo.promote(conn, args.recipe, report=documents["report"], expected_bindings=documents["bindings"],
                         operations=documents["operations"], expected_generation=args.expected_generation)
        elif args.command == "backfill":
            scanned = inserted = 0
            cursor = args.after
            while scanned < args.max_rows:
                batch = repo.reconcile(conn, args.recipe, limit=min(100, args.max_rows - scanned), after=cursor)
                scanned += batch["scanned"]
                inserted += batch["inserted"]
                next_cursor = batch["next_cursor"]
                if not batch["scanned"]:
                    break
                if next_cursor is None or next_cursor == cursor:
                    raise RuntimeError("backfill cursor did not advance")
                cursor = next_cursor
            outcome = {"scanned": scanned, "inserted": inserted, "next_cursor": cursor}
        print(json.dumps({"target": target, "command": args.command, "recipe": args.recipe,
                          "applied": True, "outcome": outcome}, default=str))


def run(argv=None):
    try:
        main(argv)
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "status": "failed",
                          "note": "Earlier committed batches may remain applied; inspect before replay."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
