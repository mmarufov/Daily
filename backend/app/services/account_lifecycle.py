"""Account lifecycle: server-side session revocation and real account deletion.

Until this module existed, `users.is_deleted` had readers but no writer
(`reader_repository._user_guard`, `ranking_repository.claim_build/reserve/latest`,
`reader_worker._current_reader`), which made every `ON DELETE CASCADE` foreign key
pointing at `public.users` unreachable code, and sign-out was purely client-side --
the `public.sessions` row survived for its full 30 days and the bearer token kept
working if it was ever extracted from the Keychain.

Deletion runs in two durable steps rather than one big transaction, on purpose:

  Step 1 (`soft_delete_account`) is small, fast and cannot realistically fail. It
  takes the `public.users` row lock *first* -- the order `ranking_repository.py`
  and `reader_worker.py` already document ("Account deletion must take this lock
  first, before its cascading rows") -- then marks the row deleted, scrubs the
  identifying columns, and drops every session and identity. After it commits the
  account is unauthenticatable, unlinkable, and fails every existing `is_deleted`
  guard. That is the promise the user is actually making a request about.

  Step 2 (`purge_account`) hard-deletes the row, which fans out across ~25
  cascading tables. It is retried by the background sweeper if the first attempt
  loses a race with an in-flight S5/S7 write, so a slow or contended purge can
  never leave a live account behind.

Splitting it this way is what gives `is_deleted` a real job: it is the durable
tombstone that keeps the account dead in the window between the two commits.
"""
from __future__ import annotations

import hashlib
import logging
import uuid

logger = logging.getLogger(__name__)

# User-scoped rows that no foreign key to public.users would remove. Static
# allowlist, never interpolated from user input; each entry is checked with a
# bound `to_regclass` first so optional schemas that were never installed are
# skipped instead of erroring (the pattern `reader_repository._invalidate` uses).
#
#   feed_build_log  -- `user_id uuid NOT NULL` with no REFERENCES at all
#                      (main.py's _ensure_tables). The one true orphan.
#   ranking_budget  -- keyed by `account text`, which holds `users.id::text` for
#                      per-account budgets. S7 installs an AFTER DELETE trigger
#                      that covers this, but only if `manage_s7_ranking.py
#                      install` was ever run; deleting it here too is idempotent
#                      and correct whether or not the trigger exists. Global rows
#                      (account='*') are deliberately retained.
_ORPHAN_USER_TABLES: tuple[tuple[str, str], ...] = (
    ("feed_build_log", "user_id"),
    ("ranking_budget", "account"),
)

# Aggregate/global tables that intentionally survive account deletion because
# they hold no per-user data -- they are keyed by domain or by a global sentinel.
# Listed explicitly so `user_scoped_tables()` can prove the purge is complete
# rather than assuming it.
_NON_USER_SCOPED: frozenset[str] = frozenset({
    "reader_embedding_global_spend",  # keyed 'global', documented as retained
    "source_quality",                 # keyed by source_domain
})


def hash_token(token: str) -> str:
    """The session lookup key. Sessions store sha256(token), never the token."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Session revocation
# ---------------------------------------------------------------------------


def revoke_session(conn, token: str) -> bool:
    """Revoke exactly the session this bearer token names. Idempotent.

    Returns True when a row was actually removed, so a caller can distinguish
    "signed out" from "that token was already dead" without a second query.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM public.sessions WHERE token_hash = %s",
            (hash_token(token),),
        )
        return cur.rowcount > 0


def revoke_all_sessions(conn, user_id: str) -> int:
    """Revoke every session for this account ("sign out everywhere"). Idempotent."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM public.sessions WHERE user_id = %s",
            (uuid.UUID(str(user_id)),),
        )
        return cur.rowcount


def purge_expired_sessions(conn, *, limit: int = 10_000) -> int:
    """Drop sessions past their 30-day expiry.

    Nothing has ever deleted from `public.sessions` -- expired rows were only
    filtered out at read time, so the table grew without bound. Bounded by
    `limit` so one sweep can't take a long lock on a table the auth path reads.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM public.sessions
            WHERE id IN (
                SELECT id FROM public.sessions
                WHERE expires_at IS NOT NULL AND expires_at < now()
                LIMIT %s
            )
            """,
            (int(limit),),
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------


def soft_delete_account(conn, user_id: str) -> bool:
    """Step 1: make the account dead, durably, in one small transaction.

    Returns False when the account does not exist or was already deleted, so the
    endpoint stays idempotent for a client that retries.

    The identifying columns are cleared here rather than waiting for the purge:
    if step 2 is delayed by a sweeper tick, no email or display name is sitting
    in the database in the meantime. Identities go too, so the same Google or
    Apple account signing in again lands on a brand-new `users` row instead of
    re-attaching to the tombstone (`_upsert_user_from_oauth` already filters
    `is_deleted = false` on the email path; dropping the identity closes the
    provider-subject path the same way).
    """
    account = uuid.UUID(str(user_id))
    with conn.transaction():
        with conn.cursor() as cur:
            # Lock users first. Every S5/S7 writer takes FOR SHARE on this row
            # before touching its cascading rows, so taking FOR UPDATE here
            # serialises deletion against in-flight builds instead of deadlocking.
            cur.execute(
                "SELECT id FROM public.users WHERE id = %s AND NOT COALESCE(is_deleted, false) FOR UPDATE",
                (account,),
            )
            if cur.fetchone() is None:
                return False
            cur.execute(
                """
                UPDATE public.users
                SET is_deleted = true,
                    deleted_at = now(),
                    email = NULL,
                    display_name = NULL,
                    photo_url = NULL,
                    last_active_at = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (account,),
            )
            cur.execute("DELETE FROM public.sessions WHERE user_id = %s", (account,))
            cur.execute("DELETE FROM public.user_identities WHERE user_id = %s", (account,))
    return True


def purge_account(conn, user_id: str) -> bool:
    """Step 2: hard-delete a soft-deleted account and everything keyed to it.

    Safe to call repeatedly and safe to call on an account that no longer exists.
    Refuses to touch a live account: the `AND is_deleted` in the final DELETE is
    the guard that makes this callable from an unattended background sweeper.
    """
    account = uuid.UUID(str(user_id))
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM public.users WHERE id = %s AND COALESCE(is_deleted, false) FOR UPDATE",
                (account,),
            )
            if cur.fetchone() is None:
                return False
            for table, column in _ORPHAN_USER_TABLES:
                cur.execute("SELECT to_regclass(%s) AS relation", ("public." + table,))
                found = cur.fetchone()
                if not found or not found["relation"]:
                    continue
                # Cast the column, not the parameter: `account` is text in
                # ranking_budget and uuid in feed_build_log, and one strategy
                # for both avoids a per-table branch (same reasoning as
                # reader_repository.reset_learning).
                cur.execute(
                    "DELETE FROM public." + table + " WHERE " + column + "::text = %s",
                    (str(account),),
                )
            # Everything else is reachable by cascade from this row.
            cur.execute("DELETE FROM public.users WHERE id = %s AND COALESCE(is_deleted, false)", (account,))
    return True


def delete_account(conn, user_id: str) -> dict:
    """The endpoint's entry point: step 1, then step 2 best-effort.

    A step-2 failure is not an error the caller should see. The account is
    already gone from their point of view and `purge_pending_accounts` will
    finish the job; reporting 500 here would invite a retry that can only
    re-run a no-op.
    """
    existed = soft_delete_account(conn, user_id)
    purged = False
    try:
        purged = purge_account(conn, user_id)
    except Exception:
        logger.exception("Account purge deferred to sweeper for %s...", str(user_id)[:8])
    return {"deleted": existed or purged, "purged": purged}


def pending_purge_ids(conn, *, limit: int = 50) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text AS id FROM public.users
            WHERE COALESCE(is_deleted, false)
            ORDER BY deleted_at NULLS FIRST
            LIMIT %s
            """,
            (int(limit),),
        )
        return [row["id"] for row in cur.fetchall()]


def purge_pending_accounts(conn, *, limit: int = 50) -> int:
    """Sweeper: finish any deletion whose purge didn't complete inline.

    Each account gets its own transaction so one contended row can't block the
    rest of the batch.
    """
    purged = 0
    for account_id in pending_purge_ids(conn, limit=limit):
        try:
            if purge_account(conn, account_id):
                purged += 1
        except Exception:
            logger.exception("Deferred purge failed for %s...", account_id[:8])
    return purged


# ---------------------------------------------------------------------------
# Coverage introspection
# ---------------------------------------------------------------------------


def user_scoped_tables(conn) -> dict[str, list[str]]:
    """Classify every table that stores a user identifier, from the live schema.

    This exists so a test can *prove* deletion is complete instead of asserting
    against a hand-maintained list that drifts the first time someone adds a
    table. Returns three buckets:

      cascaded  -- reachable from public.users by ON DELETE CASCADE, directly or
                   through any chain of cascading foreign keys
      explicit  -- removed by hand in `purge_account` (_ORPHAN_USER_TABLES)
      uncovered -- neither; a row here would outlive the account that created it

    `uncovered` must stay empty.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.conrelid::regclass::text AS child,
                   c.confrelid::regclass::text AS parent
            FROM pg_constraint c
            JOIN pg_class rel ON rel.oid = c.conrelid
            JOIN pg_namespace ns ON ns.oid = rel.relnamespace
            WHERE c.contype = 'f' AND c.confdeltype = 'c' AND ns.nspname = 'public'
            """
        )
        edges: dict[str, set[str]] = {}
        for row in cur.fetchall():
            edges.setdefault(_bare(row["parent"]), set()).add(_bare(row["child"]))

        cur.execute(
            """
            SELECT DISTINCT c.table_name AS name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = 'public'
              AND t.table_type = 'BASE TABLE'
              AND c.column_name IN ('user_id', 'account')
            """
        )
        candidates = {row["name"] for row in cur.fetchall()}

    cascaded: set[str] = set()
    frontier = ["users"]
    while frontier:
        table = frontier.pop()
        for child in edges.get(table, ()):
            if child not in cascaded:
                cascaded.add(child)
                frontier.append(child)

    explicit = {table for table, _ in _ORPHAN_USER_TABLES}
    return {
        "cascaded": sorted(candidates & cascaded),
        "explicit": sorted(candidates & explicit),
        "uncovered": sorted(candidates - cascaded - explicit - _NON_USER_SCOPED),
    }


def _bare(qualified: str) -> str:
    """`public.sessions` / `"public"."sessions"` -> `sessions`."""
    return qualified.split(".")[-1].strip('"')
