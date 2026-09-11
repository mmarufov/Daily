"""Authenticated S5 API adapters; all state transitions use the Reader repository."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException


def router(get_db, authenticate):
    api = APIRouter()

    def user(conn, authorization):
        from .reader_integration import enabled
        if not enabled():
            raise HTTPException(404, "Reader model is not enabled")
        return authenticate(conn, authorization)

    def call(fn, *args, **kwargs):
        from .reader_repository import ReaderConflict, ReaderNotFound
        try:
            return fn(*args, **kwargs)
        except ReaderConflict as exc:
            raise HTTPException(409, {"code": exc.code, "current": exc.current}) from exc
        except ReaderNotFound as exc:
            raise HTTPException(404, "Reader not found") from exc
        except (ValueError, TypeError) as exc:
            # Do not expose a Pydantic exception's raw input/private profile.
            raise HTTPException(422, "Invalid reader request; reload your profile and check the supported fields") from exc

    @api.get("/user/reader")
    async def get(Authorization: str | None = Header(default=None), conn=Depends(get_db)):
        from .reader_repository import load_reader
        return call(load_reader, conn, user(conn, Authorization))

    @api.patch("/user/reader")
    async def patch(payload: dict, Authorization: str | None = Header(default=None), conn=Depends(get_db)):
        from .reader_repository import mutate_reader
        return call(mutate_reader, conn, user(conn, Authorization), payload)

    @api.get("/user/reader/operations/{operation_id}")
    async def operation(operation_id: str, Authorization: str | None = Header(default=None), conn=Depends(get_db)):
        from .reader_repository import get_operation
        result = call(get_operation, conn, user(conn, Authorization), operation_id)
        if result is None:
            raise HTTPException(404, "Reader operation not found or expired")
        return result

    @api.post("/user/reader/proposals")
    async def proposal(payload: dict, Authorization: str | None = Header(default=None), conn=Depends(get_db)):
        from .reader_repository import load_reader, publication_guard
        from .reader_contract import ReaderMutation, canonical_hash, apply_patch
        from .reader_integration import propose
        import json
        uid = user(conn, Authorization)
        def make():
            if set(payload) != {"operation_id", "base_generation", "base_revision", "text"}:
                raise ValueError("Invalid proposal request")
            identity = ReaderMutation.model_validate({k: payload[k] for k in ("operation_id", "base_generation", "base_revision")} | {"patch": {}})
            snapshot = load_reader(conn, uid)
            with publication_guard(conn, uid, snapshot):
                conn.execute("DELETE FROM public.reader_proposals WHERE user_id=%s AND created_at < now()-interval '1 day'", (uid,))
                # Separate typed operation namespace; proposal is deterministic and free,
                # so exact replay needs no provider lease or uncertain billing recovery.
                digest = canonical_hash(payload)
                old = conn.execute("SELECT request_hash,result FROM public.reader_proposals WHERE user_id=%s AND operation_id=%s",
                                   (uid, identity.operation_id)).fetchone()
                if old:
                    if old["request_hash"] != digest:
                        raise ValueError("Proposal identity reused")
                    return old["result"]
                if (snapshot["generation"], snapshot["revision"]) != (identity.base_generation, identity.base_revision):
                    raise HTTPException(409, "Reader changed; review a new proposal")
                try:
                    result = propose(snapshot["profile"], payload["text"], operation_id=identity.operation_id)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
                apply_patch(snapshot["profile"], result["patch"])
                result.update(operation_id=identity.operation_id, base_generation=identity.base_generation,
                              base_revision=identity.base_revision)
                conn.execute("INSERT INTO public.reader_proposals(user_id,operation_id,request_hash,result) VALUES (%s,%s,%s,%s::jsonb)",
                             (uid, identity.operation_id, digest, json.dumps(result)))
                return result
        return call(make)

    @api.post("/user/reader/reset-learning")
    async def reset(payload: dict, Authorization: str | None = Header(default=None), conn=Depends(get_db)):
        from .reader_repository import reset_learning
        def cleanup(conn, uid):
            for table in ("reader_learned_signals", "reader_delivery_receipts", "reader_proposals"):
                conn.execute(f"DELETE FROM public.{table} WHERE user_id=%s", (uid,))
            # Passive legacy history must not regenerate weights after reset.
            conn.execute("DELETE FROM public.reading_events WHERE user_id=%s", (uid,))
            for table in ("reader_intent_embeddings", "reader_embedding_jobs"):
                exists = conn.execute("SELECT to_regclass(%s) AS relation", ("public." + table,)).fetchone()
                if exists and exists["relation"]:
                    conn.execute(f"DELETE FROM public.{table} WHERE user_id=%s", (uid,))
        return call(reset_learning, conn, user(conn, Authorization), {"patch": {}, **payload}, cleanup=cleanup)

    return api
