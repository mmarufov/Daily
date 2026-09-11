"""Small S7 control, lease, spend and atomic-envelope store.

Lock order when combined: user -> canonical reader -> S7 control -> build ->
reservation/counters/result. No network operation belongs in these transactions.
Publication caller must hold reader publication_guard and perform fresh evidence
authorization before publish(). A stored envelope is not independently authorized
for delivery: latest() deliberately requires the caller's fresh authorization.
"""
from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
import json
import uuid

from psycopg.types.json import Jsonb

from app.services.reader_contract import canonical_hash

SUPPORTED_MODEL = "gpt-4.1-mini-2025-04-14"
SUPPORTED_PRICES = (Decimal('0.40'), Decimal('1.60'))


class RankingStoreError(ValueError):
    pass


@contextmanager
def _transaction(conn):
    """Bound lock contention even when called outside the serving adapter."""
    with conn.transaction():
        conn.execute("SET LOCAL statement_timeout = '2000ms'")
        conn.execute("SET LOCAL lock_timeout = '100ms'")
        yield


def _money(value):
    if isinstance(value, bool):
        raise RankingStoreError("invalid_money")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 1_000_000:
            raise RankingStoreError("invalid_money")
        return amount.quantize(Decimal("0.00000001"), rounding=ROUND_CEILING)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RankingStoreError("invalid_money") from exc


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RankingStoreError("invalid_id") from exc


def _identity(value):
    if not isinstance(value, dict) or not value:
        raise RankingStoreError("invalid_identity")
    try:
        # Reject non-JSON values and nonfinite numbers; no permissive default=str.
        encoded = json.dumps(value, allow_nan=False, sort_keys=True)
        if len(encoded.encode()) > 32_768:
            raise RankingStoreError("identity_too_large")
        return canonical_hash(value)
    except (TypeError, ValueError) as exc:
        raise RankingStoreError("invalid_identity") from exc


def install_schema(conn):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(73405701)")
        conn.execute(Path(__file__).with_name("ranking_schema.sql").read_text())


def control(conn, *, lock=False):
    with _transaction(conn):
        exists = conn.execute("SELECT to_regclass('public.ranking_control') AS relation").fetchone()
        if not exists or not exists["relation"]:
            return None
        return conn.execute("SELECT * FROM public.ranking_control WHERE singleton"
                            + (" FOR SHARE" if lock else "")).fetchone()


def configure(conn, recipe, *, approved=False, serving=False, provider=False,
              daily_usd=0, account_daily_usd=0):
    if any(type(flag) is not bool for flag in (approved, serving, provider)):
        raise RankingStoreError("invalid_flag")
    recipe_hash = _identity(recipe)
    if approved:
        # Approval applies to an executable, bounded rubric, not arbitrary JSON.
        # Keep this shared with the request contract so CLI and serving cannot
        # disagree about which recipe was approved.
        from app.services.ranking_contract import validate_recipe
        try:
            validate_recipe(recipe)
        except ValueError as exc:
            raise RankingStoreError("unsupported_recipe") from exc
    daily, account = _money(daily_usd), _money(account_daily_usd)
    if (serving or provider) and not approved:
        raise RankingStoreError("recipe_not_approved")
    if provider:
        prices = recipe.get("pricing", {})
        if (recipe.get("model") != SUPPORTED_MODEL or not isinstance(prices, dict)
                or (_money(prices.get("input_usd_per_million")),
                    _money(prices.get("output_usd_per_million"))) != SUPPORTED_PRICES):
            raise RankingStoreError("unsupported_model_or_pricing")
        if daily <= 0 or account <= 0 or account > daily:
            raise RankingStoreError("positive_budgets_required")
    with _transaction(conn):
        return conn.execute("""UPDATE public.ranking_control SET epoch=epoch+1,
          recipe=%s,recipe_hash=%s,approved=%s,serving=%s,provider=%s,
          daily_usd=%s,account_daily_usd=%s,updated_at=clock_timestamp()
          WHERE singleton RETURNING *""", (Jsonb(recipe), recipe_hash, approved,
          serving, provider, daily, account)).fetchone()


def _control_locked(conn, *, write=False):
    row = conn.execute("SELECT * FROM public.ranking_control WHERE singleton FOR "
                       + ("UPDATE" if write else "SHARE")).fetchone()
    if not row or not row["approved"]:
        raise RankingStoreError("ranking_not_approved")
    return row


def claim_build(conn, user_id, identity, recipe_hash, *, lease_seconds=30):
    user_id, identity_hash = _uuid(user_id), _identity(identity)
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 30:
        raise RankingStoreError("invalid_lease")
    with _transaction(conn):
        # Account deletion must take this lock first, before its cascading rows.
        user = conn.execute("""SELECT id FROM public.users WHERE id=%s
          AND NOT COALESCE(is_deleted,false) FOR SHARE""", (user_id,)).fetchone()
        if not user:
            raise RankingStoreError("account_unavailable")
        state = _control_locked(conn)
        if state["recipe_hash"] != recipe_hash:
            raise RankingStoreError("recipe_changed")
        build_id, token = str(uuid.uuid4()), str(uuid.uuid4())
        return conn.execute("""INSERT INTO public.ranking_builds
          (user_id,build_id,token,epoch,recipe_hash,identity,identity_hash,expires_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+%s*interval '1 second')
          ON CONFLICT(user_id) DO UPDATE SET build_id=EXCLUDED.build_id,
          token=EXCLUDED.token,epoch=EXCLUDED.epoch,recipe_hash=EXCLUDED.recipe_hash,
          identity=EXCLUDED.identity,identity_hash=EXCLUDED.identity_hash,
          expires_at=EXCLUDED.expires_at,published=false
          WHERE ranking_builds.expires_at<=clock_timestamp() OR ranking_builds.published
          RETURNING *""", (user_id, build_id, token, state["epoch"], recipe_hash,
          Jsonb(identity), identity_hash, lease_seconds)).fetchone()


def _claim_locked(conn, user_id, build_id, token, state):
    row = conn.execute("""SELECT *,expires_at>clock_timestamp() AS live
      FROM public.ranking_builds WHERE user_id=%s FOR UPDATE""", (user_id,)).fetchone()
    if (not row or str(row["build_id"]) != build_id or str(row["token"]) != token
            or row["epoch"] != state["epoch"] or row["recipe_hash"] != state["recipe_hash"]
            or not row["live"] or row["published"]):
        raise RankingStoreError("stale_claim")
    return row


def reserve(conn, user_id, build_id, token, attempt, reserved_usd):
    user_id, build_id, token = map(_uuid, (user_id, build_id, token))
    amount = _money(reserved_usd)
    if type(attempt) is not int or not 1 <= attempt <= 6 or amount <= 0:
        raise RankingStoreError("invalid_reservation")
    with _transaction(conn):
        # Reservation insertion takes a user FK lock. Acquire it before control
        # and build locks so account deletion cannot invert that order.
        user = conn.execute("""SELECT id FROM public.users WHERE id=%s
          AND NOT COALESCE(is_deleted,false) FOR SHARE""", (user_id,)).fetchone()
        if not user:
            raise RankingStoreError("account_unavailable")
        # A single global control lock serializes admissions across all processes.
        state = _control_locked(conn, write=True)
        if not state["provider"] or state["daily_usd"] <= 0 or state["account_daily_usd"] <= 0:
            raise RankingStoreError("provider_disabled")
        _claim_locked(conn, user_id, build_id, token, state)
        old = conn.execute("""SELECT * FROM public.ranking_reservations
          WHERE build_id=%s AND attempt=%s""", (build_id, attempt)).fetchone()
        if old:
            if str(old["user_id"]) != user_id or old["reserved_usd"] != amount:
                raise RankingStoreError("reservation_reused")
            return old
        day = conn.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date AS day").fetchone()["day"]
        rows = conn.execute("""SELECT account,committed_usd FROM public.ranking_budget
          WHERE day=%s AND account=ANY(%s)""", (day, ["*", user_id])).fetchall()
        spent = {row["account"]: row["committed_usd"] for row in rows}
        if (spent.get("*", 0)+amount > state["daily_usd"]
                or spent.get(user_id, 0)+amount > state["account_daily_usd"]):
            raise RankingStoreError("budget_exhausted")
        for account in ("*", user_id):
            conn.execute("""INSERT INTO public.ranking_budget(day,account,committed_usd)
              VALUES(%s,%s,%s) ON CONFLICT(day,account) DO UPDATE
              SET committed_usd=ranking_budget.committed_usd+EXCLUDED.committed_usd""",
              (day, account, amount))
        return conn.execute("""INSERT INTO public.ranking_reservations
          (reservation_id,user_id,build_id,attempt,day,reserved_usd)
          VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""",
          (str(uuid.uuid4()), user_id, build_id, attempt, day, amount)).fetchone()


def settle(conn, reservation_id, actual_usd):
    """Only settle a definite charge. Ambiguous timeout/cancellation: do not call.

    An over-reservation charge is recorded, disables provider/serving and advances
    the epoch, invalidating work. Return overrun=True (raising would roll it back).
    Stale claims may settle; they still cannot publish. Identical retries are safe.
    """
    reservation_id, actual = _uuid(reservation_id), _money(actual_usd)
    with _transaction(conn):
        # Resolve ownership without a lock, then follow the same user-first
        # order as admission. Account deletion cascades reservations and clears
        # account counters; settlement must not race those writes in reverse.
        owner = conn.execute("SELECT user_id FROM public.ranking_reservations WHERE reservation_id=%s",
                             (reservation_id,)).fetchone()
        if not owner:
            raise RankingStoreError("reservation_missing")
        user = conn.execute("SELECT id FROM public.users WHERE id=%s FOR SHARE",
                            (owner["user_id"],)).fetchone()
        if not user:
            raise RankingStoreError("reservation_missing")
        conn.execute("SELECT singleton FROM public.ranking_control WHERE singleton FOR UPDATE")
        row = conn.execute("SELECT * FROM public.ranking_reservations WHERE reservation_id=%s FOR UPDATE",
                           (reservation_id,)).fetchone()
        if not row:
            raise RankingStoreError("reservation_missing")
        if row["actual_usd"] is not None:
            if row["actual_usd"] != actual:
                raise RankingStoreError("settlement_conflict")
            return {**row, "overrun": actual > row["reserved_usd"]}
        delta = actual-row["reserved_usd"]
        for account in ("*", str(row["user_id"])):
            conn.execute("""UPDATE public.ranking_budget SET committed_usd=committed_usd+%s
              WHERE day=%s AND account=%s""", (delta, row["day"], account))
        conn.execute("UPDATE public.ranking_reservations SET actual_usd=%s WHERE reservation_id=%s",
                     (actual, reservation_id))
        overrun = actual > row["reserved_usd"]
        if overrun:
            conn.execute("""UPDATE public.ranking_control SET provider=false,serving=false,
              epoch=epoch+1,updated_at=clock_timestamp() WHERE singleton""")
        return {**row, "actual_usd": actual, "overrun": overrun}


def publish(conn, user_id, build_id, token, identity, envelope, expires_at):
    """CAS an already freshly authorized envelope inside caller's reader guard."""
    user_id, build_id, token = map(_uuid, (user_id, build_id, token))
    digest = _identity(identity)
    if (not isinstance(expires_at, datetime) or expires_at.tzinfo is None
            or expires_at.utcoffset() is None):
        raise RankingStoreError("invalid_expiry")
    try:
        encoded = json.dumps(envelope, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RankingStoreError("invalid_envelope") from exc
    if not isinstance(envelope, dict) or len(encoded.encode()) > 8_000_000:
        raise RankingStoreError("invalid_envelope")
    with _transaction(conn):
        state = _control_locked(conn)
        if not state['serving']:
            raise RankingStoreError('serving_disabled')
        claim = _claim_locked(conn, user_id, build_id, token, state)
        if claim["identity_hash"] != digest:
            raise RankingStoreError("identity_changed")
        # Guard against arbitrarily persistent cached model output.
        valid = conn.execute("""SELECT %s>clock_timestamp() AND
          %s<=clock_timestamp()+interval '15 minutes' AS valid""", (expires_at, expires_at)).fetchone()
        if not valid["valid"]:
            raise RankingStoreError("result_expired")
        sequence = conn.execute("""INSERT INTO public.ranking_publication_counters(user_id,sequence)
          VALUES(%s,1) ON CONFLICT(user_id) DO UPDATE
          SET sequence=ranking_publication_counters.sequence+1
          WHERE ranking_publication_counters.sequence<9007199254740991
          RETURNING sequence""", (user_id,)).fetchone()
        if not sequence:
            raise RankingStoreError('publication_sequence_exhausted')
        row = conn.execute("""INSERT INTO public.ranking_results
          (user_id,build_id,epoch,recipe_hash,identity,identity_hash,envelope,expires_at,publication_sequence)
          SELECT user_id,build_id,epoch,recipe_hash,identity,identity_hash,%s,%s,%s
          FROM public.ranking_builds WHERE user_id=%s AND token=%s
            AND expires_at>clock_timestamp() AND NOT published
          ON CONFLICT(user_id) DO UPDATE SET build_id=EXCLUDED.build_id,
          epoch=EXCLUDED.epoch,recipe_hash=EXCLUDED.recipe_hash,identity=EXCLUDED.identity,
          identity_hash=EXCLUDED.identity_hash,envelope=EXCLUDED.envelope,
          expires_at=EXCLUDED.expires_at,publication_sequence=EXCLUDED.publication_sequence,
          created_at=clock_timestamp()
          RETURNING build_id,publication_sequence,created_at,expires_at""",
          (Jsonb(envelope), expires_at, sequence['sequence'], user_id, token)).fetchone()
        if not row:
            raise RankingStoreError("stale_claim")
        conn.execute("UPDATE public.ranking_builds SET published=true WHERE user_id=%s AND token=%s", (user_id, token))
        return row


def latest(conn, user_id):
    """Raw internal cache only. Caller MUST freshly authorize before delivery."""
    user_id = _uuid(user_id)
    with _transaction(conn):
        return conn.execute("""SELECT r.* FROM public.ranking_results r
          JOIN public.ranking_control c ON c.singleton AND c.approved AND c.serving
            AND c.epoch=r.epoch AND c.recipe_hash=r.recipe_hash
          JOIN public.users u ON u.id=r.user_id AND NOT COALESCE(u.is_deleted,false)
          WHERE r.user_id=%s AND r.expires_at>clock_timestamp()""", (user_id,)).fetchone()


def latest_rank(conn, user_id):
    """Build-only raw rank reuse, including an expired shorter-lived S4 edition.

    The caller MUST validate the RankBatch TTL, complete reader identity and all
    current S6/S7 evidence. This function never authorizes a feed/cache response.
    """
    user_id = _uuid(user_id)
    with _transaction(conn):
        return conn.execute("""SELECT r.* FROM public.ranking_results r
          JOIN public.ranking_control c ON c.singleton AND c.approved AND c.serving
            AND c.epoch=r.epoch AND c.recipe_hash=r.recipe_hash
          JOIN public.users u ON u.id=r.user_id AND NOT COALESCE(u.is_deleted,false)
          WHERE r.user_id=%s AND r.created_at>clock_timestamp()-interval '15 minutes'""",
          (user_id,)).fetchone()


def invalidate(conn, user_id):
    """Call inside reader edit/reset transaction; no control lock is acquired."""
    user_id = _uuid(user_id)
    with _transaction(conn):
        conn.execute("DELETE FROM public.ranking_builds WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM public.ranking_results WHERE user_id=%s", (user_id,))


def release_claim(conn, user_id, build_id, token):
    """Release only the caller's lease. Never refund ambiguous provider spend."""
    user_id, build_id, token = map(_uuid, (user_id, build_id, token))
    with _transaction(conn):
        return conn.execute("""DELETE FROM public.ranking_builds
          WHERE user_id=%s AND build_id=%s AND token=%s RETURNING build_id""",
          (user_id, build_id, token)).fetchone() is not None


def prune(conn, *, limit=1000):
    """Bound each explicit maintenance run. Never release today's ambiguous spend."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise RankingStoreError("invalid_prune_limit")
    with _transaction(conn):
        conn.execute("SELECT singleton FROM public.ranking_control WHERE singleton FOR UPDATE")
        for table, predicate in (
            ("ranking_reservations", "created_at<clock_timestamp()-interval '30 days'"),
            ("ranking_budget", "day<(clock_timestamp() AT TIME ZONE 'UTC')::date-30"),
            ("ranking_builds", "expires_at<clock_timestamp()"),
            ("ranking_results", "expires_at<clock_timestamp()"),
        ):
            conn.execute(f"DELETE FROM public.{table} WHERE ctid IN "
                         f"(SELECT ctid FROM public.{table} WHERE {predicate} LIMIT %s)", (limit,))
