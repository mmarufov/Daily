import os
import hashlib
import base64
from datetime import datetime, timedelta, timezone

import jwt
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
import psycopg
from psycopg.rows import dict_row

load_dotenv()

NEON_DATABASE_URL = os.getenv("NEON_DATABASE_URL", "")
GOOGLE_AUDIENCE = os.getenv("GOOGLE_AUDIENCE", "")
APPLE_AUDIENCE = os.getenv("APPLE_AUDIENCE", "")
APP_TOKEN_TTL_HOURS = int(os.getenv("APP_TOKEN_TTL_HOURS", "720"))  # 30 days

app = FastAPI(title="Daily Auth API", version="0.1.0")


def get_db():
    with psycopg.connect(NEON_DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def _hash_token(raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


async def _verify_google_id_token(id_token: str) -> dict:
    # Minimal verification via Google tokeninfo (server-to-server, rate-limited but sufficient for MVP)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    data = r.json()
    aud = data.get("aud")
    if GOOGLE_AUDIENCE and aud != GOOGLE_AUDIENCE:
        raise HTTPException(status_code=401, detail="Google token audience mismatch")
    return {
        "provider": "google",
        "provider_user_id": data.get("sub"),
        "email": data.get("email"),
        "email_verified": data.get("email_verified") == "true",
        "name": data.get("name"),
        "picture": data.get("picture"),
        "raw": data,
    }


APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


async def _verify_apple_identity_token(identity_token: str) -> dict:
    # Lightweight validation using Apple JWKS via PyJWT (no full nonce/state flow here)
    async with httpx.AsyncClient(timeout=10) as client:
        jwks = (await client.get(APPLE_JWKS_URL)).json()
    try:
        # PyJWT can accept a JWKS mapping via algorithms+options; we manually select keys
        unverified = jwt.get_unverified_header(identity_token)
        kid = unverified.get("kid")
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not key:
            raise HTTPException(status_code=401, detail="Apple key not found")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        decoded = jwt.decode(
            identity_token,
            key=public_key,
            algorithms=["RS256"],
            audience=APPLE_AUDIENCE or None,
            options={"verify_aud": bool(APPLE_AUDIENCE)},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid Apple token")
    return {
        "provider": "apple",
        "provider_user_id": decoded.get("sub"),
        "email": decoded.get("email"),
        "email_verified": decoded.get("email_verified", False),
        "name": None,
        "picture": None,
        "raw": decoded,
    }


def _upsert_user_and_identity(conn, identity: dict) -> dict:
    email = identity.get("email")
    display_name = identity.get("name")
    photo_url = identity.get("picture")
    provider = identity["provider"]
    provider_user_id = identity["provider_user_id"]

    with conn.cursor() as cur:
        # Upsert user by email if present; else create anonymous user
        if email:
            cur.execute(
                """
                INSERT INTO public.users (email, display_name, photo_url, updated_at, last_login)
                VALUES (LOWER(%s), %s, %s, now(), now())
                ON CONFLICT (id) DO NOTHING
                RETURNING id, email, display_name, photo_url
                """,
                (email, display_name, photo_url),
            )
            row = cur.fetchone()
            if not row:
                # If user with email exists (unique partial index), fetch it and update
                cur.execute(
                    """
                    SELECT id, email, display_name, photo_url FROM public.users
                    WHERE lower(email) = lower(%s) AND is_deleted = false
                    """,
                    (email,),
                )
                row = cur.fetchone()
                cur.execute(
                    "UPDATE public.users SET display_name = COALESCE(%s, display_name), photo_url = COALESCE(%s, photo_url), last_login = now(), updated_at = now() WHERE id = %s",
                    (display_name, photo_url, row["id"]),
                )
        else:
            cur.execute(
                """
                INSERT INTO public.users (display_name, photo_url, last_login)
                VALUES (%s, %s, now())
                RETURNING id, email, display_name, photo_url
                """,
                (display_name, photo_url),
            )
            row = cur.fetchone()

        user_id = row["id"]

        # Upsert identity
        cur.execute(
            """
            INSERT INTO public.user_identities (user_id, provider, provider_user_id, email, raw_profile)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (provider, provider_user_id)
            DO UPDATE SET user_id = EXCLUDED.user_id, email = EXCLUDED.email, raw_profile = EXCLUDED.raw_profile
            RETURNING id
            """,
            (user_id, provider, provider_user_id, email, identity.get("raw")),
        )
        _ = cur.fetchone()

        return {
            "id": user_id,
            "email": row.get("email"),
            "display_name": row.get("display_name"),
            "photo_url": row.get("photo_url"),
        }


def _create_session(conn, user_id: str) -> str:
    raw_token = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=APP_TOKEN_TTL_HOURS)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.sessions (user_id, token_hash, created_at, last_seen_at, expires_at)
            VALUES (%s, %s, now(), now(), %s)
            RETURNING id
            """,
            (user_id, token_hash, expires_at),
        )
        _ = cur.fetchone()
    return raw_token


@app.post("/auth/google")
async def auth_google(payload: dict, conn=Depends(get_db)):
    id_token = payload.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="id_token is required")
    identity = await _verify_google_id_token(id_token)
    user = _upsert_user_and_identity(conn, identity)
    app_token = _create_session(conn, user["id"])
    return {"token": app_token, "user": user}


@app.post("/auth/apple")
async def auth_apple(payload: dict, conn=Depends(get_db)):
    identity_token = payload.get("identity_token")
    if not identity_token:
        raise HTTPException(status_code=400, detail="identity_token is required")
    identity = await _verify_apple_identity_token(identity_token)
    user = _upsert_user_and_identity(conn, identity)
    app_token = _create_session(conn, user["id"])
    return {"token": app_token, "user": user}


def _require_auth(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    return authorization.split(" ", 1)[1]


@app.get("/me")
def me(Authorization: str | None = Header(default=None), conn=Depends(get_db)):
    token = _require_auth(Authorization)
    token_hash = _hash_token(token)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.email, u.display_name, u.photo_url
            FROM public.sessions s
            JOIN public.users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND (s.expires_at IS NULL OR s.expires_at > now())
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return row


