#!/usr/bin/env python3
"""Grant, update, inspect, or revoke an audited S2 source-display policy.

The command never accepts a database URL as an argument, which keeps secrets
out of shell history and process listings.  Set ``DATABASE_URL`` (or name a
different environment variable with ``--database-env``).

Mutating actions require ``--apply`` and review metadata.  Without ``--apply``
they print the validated proposed change and leave PostgreSQL untouched.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg
from psycopg.rows import dict_row

from app.services.article_content import (
    BODY_ARTIFACT_KINDS,
    normalize_feed_url,
    normalize_source_domain,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-env",
        default="DATABASE_URL",
        help="environment variable containing the PostgreSQL URL (default: DATABASE_URL)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="show current policy and audit events")
    inspect_parser.add_argument("domain")

    for action in ("grant", "update"):
        action_parser = subparsers.add_parser(action)
        action_parser.add_argument("domain")
        action_parser.add_argument(
            "--display-policy",
            choices=("source_only", "native_full_text"),
            required=True,
        )
        action_parser.add_argument(
            "--allow-kind",
            action="append",
            default=[],
            choices=sorted(BODY_ARTIFACT_KINDS),
            help="repeat for each audited display artifact kind",
        )
        action_parser.add_argument(
            "--publisher-feed-full-text",
            action="store_true",
            help="reviewer asserts this domain's feed payload is complete, not a teaser",
        )
        action_parser.add_argument(
            "--allow-feed-url",
            action="append",
            default=[],
            help="repeat for each exact reviewed HTTPS feed allowed to supply native text",
        )
        action_parser.add_argument("--rights-basis", required=True)
        action_parser.add_argument("--access-hint", default="unknown")
        action_parser.add_argument("--offline-cache-seconds", type=int, default=0,
                                   help="explicit reviewed offline native grant, 0..86400 (default deny)")
        action_parser.add_argument("--reviewed-by", required=True)
        action_parser.add_argument(
            "--apply", action="store_true", help="commit this audited policy change"
        )

    revoke_parser = subparsers.add_parser("revoke")
    revoke_parser.add_argument("domain")
    revoke_parser.add_argument("--reviewed-by", required=True)
    revoke_parser.add_argument("--access-hint", default="unknown")
    revoke_parser.add_argument(
        "--apply", action="store_true", help="commit this revocation"
    )
    return parser


def _validated_domain(raw: str) -> str:
    if "://" in raw:
        try:
            parsed = urlsplit(raw)
        except ValueError as exc:
            raise ValueError("domain is not a valid hostname or URL") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("domain URL must not contain credentials")
    domain = normalize_source_domain(raw)
    if not domain or "." not in domain:
        raise ValueError("domain must be a valid public-style hostname")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("source policy must name a publisher hostname, not an IP address")
    return domain


def _database_url(args: argparse.Namespace) -> str:
    value = os.getenv(args.database_env)
    if not value:
        raise ValueError(f"{args.database_env} is not set")
    return value


def _proposal(args: argparse.Namespace, domain: str) -> dict:
    if args.command == "revoke":
        reviewer = args.reviewed_by.strip()
        if not reviewer:
            raise ValueError("--reviewed-by cannot be blank")
        return {
            "action": "revoke",
            "source_domain": domain,
            "display_policy": "source_only",
            "allowed_artifact_kinds": [],
            "allowed_feed_urls": [],
            "publisher_feed_full_text": False,
            "rights_basis": "revoked",
            "access_hint": args.access_hint,
            "reviewed_by": reviewer,
        }
    raw_feed_urls = list(dict.fromkeys(url.strip() for url in args.allow_feed_url))
    allowed_feed_urls = [normalize_feed_url(url) for url in raw_feed_urls]
    if any(not url for url in allowed_feed_urls):
        raise ValueError("--allow-feed-url must be a public HTTPS feed URL")
    proposal = {
        "action": args.command,
        "source_domain": domain,
        "display_policy": args.display_policy,
        "allowed_artifact_kinds": sorted(set(args.allow_kind)),
        "allowed_feed_urls": sorted(allowed_feed_urls),
        "publisher_feed_full_text": args.publisher_feed_full_text,
        "rights_basis": args.rights_basis.strip().casefold(),
        "access_hint": args.access_hint.strip().casefold(),
        "reviewed_by": args.reviewed_by.strip(),
        "offline_cache_seconds": args.offline_cache_seconds,
    }
    if (not 0 <= proposal['offline_cache_seconds'] <= 86400
            or (proposal['offline_cache_seconds'] and proposal['display_policy'] != 'native_full_text')):
        raise ValueError("offline cache requires native permission and 0..86400 seconds")
    if not proposal["reviewed_by"]:
        raise ValueError("--reviewed-by cannot be blank")
    if not proposal["rights_basis"]:
        raise ValueError("--rights-basis cannot be blank")
    if proposal["display_policy"] == "native_full_text":
        if not proposal["allowed_artifact_kinds"]:
            raise ValueError("native_full_text requires at least one --allow-kind")
        if proposal["rights_basis"].lower() in {
            "unknown", "none", "unverified", "unspecified", "unreviewed",
            "pending", "revoked", "not_applicable", "n_a", "false", "no_rights",
        }:
            raise ValueError("native_full_text requires an explicit reviewed rights basis")
    elif (
        proposal["allowed_artifact_kinds"]
        or proposal["allowed_feed_urls"]
        or proposal["publisher_feed_full_text"]
    ):
        raise ValueError("source_only cannot allow native artifact kinds")
    if "publisher_feed" in proposal["allowed_artifact_kinds"] and not proposal["publisher_feed_full_text"]:
        raise ValueError("publisher_feed requires --publisher-feed-full-text")
    if (
        proposal["publisher_feed_full_text"]
        and (
            "publisher_feed" not in proposal["allowed_artifact_kinds"]
            or not proposal["allowed_feed_urls"]
        )
    ):
        raise ValueError(
            "--publisher-feed-full-text requires --allow-kind publisher_feed and --allow-feed-url"
        )
    return proposal


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        domain = _validated_domain(args.domain)
        database_url = _database_url(args)
        proposal = None if args.command == "inspect" else _proposal(args, domain)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "inspect":
        try:
            with psycopg.connect(database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM public.article_source_policies WHERE source_domain = %s",
                        (domain,),
                    )
                    policy = cur.fetchone()
                    cur.execute(
                        "SELECT action, policy_version, display_policy, "
                        "allowed_artifact_kinds, allowed_feed_urls, "
                        "publisher_feed_full_text, rights_basis, "
                        "access_hint, reviewed_by, created_at "
                        "FROM public.article_source_policy_events "
                        "WHERE source_domain = %s ORDER BY policy_version",
                        (domain,),
                    )
                    events = cur.fetchall()
        except Exception as exc:
            print(f"policy inspection failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"policy": policy, "events": events}, default=str, indent=2))
        return 0

    assert proposal is not None
    if not args.apply:
        print(json.dumps({"dry_run": True, "proposal": proposal}, indent=2))
        print("No changes made. Re-run with --apply after review.")
        return 0

    try:
        # Import mutation APIs only after validation and --apply so help,
        # proposal review, and tests remain usable during a rolling deploy in
        # which the CLI can arrive just before the application image.
        from app.services.article_content import revoke_source_policy, set_source_policy

        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            if args.command == "revoke":
                result = revoke_source_policy(
                    conn,
                    source_domain=domain,
                    reviewed_by=proposal["reviewed_by"],
                    access_hint=proposal["access_hint"],
                )
            else:
                result = set_source_policy(
                    conn,
                    source_domain=domain,
                    display_policy=proposal["display_policy"],
                    allowed_artifact_kinds=proposal["allowed_artifact_kinds"],
                    allowed_feed_urls=proposal["allowed_feed_urls"],
                    publisher_feed_full_text=proposal["publisher_feed_full_text"],
                    rights_basis=proposal["rights_basis"],
                    access_hint=proposal["access_hint"],
                    reviewed_by=proposal["reviewed_by"],
                    action=proposal["action"],
                )
        print(json.dumps({"applied": True, "policy": result}, default=str, indent=2))
        return 0
    except Exception as exc:
        print(f"policy change failed and was rolled back: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
