import os
import hashlib
import base64
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import jwt
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import JSONResponse
import psycopg
from psycopg.rows import dict_row
from app.services.openai_service import get_openai_service

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")


# ---------------------------------------------------------------------------
# Background ingestion loop
# ---------------------------------------------------------------------------

async def _ingestion_loop():
    """Background task: fetch RSS feeds, extract content, clean up old articles."""
    from app.services.news_ingestion import fetch_rss_feeds
    from app.services.content_extractor import extract_article_content

    # Wait a few seconds for the app to fully start
    await asyncio.sleep(5)
    print("Ingestion worker started")

    while True:
        try:
            # 1. Fetch RSS feeds
            with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
                _ensure_tables(conn)
                new_count = await fetch_rss_feeds(conn)
                print(f"Ingestion: {new_count} new articles from RSS")

                # 2. Extract content for articles that don't have it yet (batch of 10)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, url FROM public.articles
                        WHERE content_extracted = false AND url IS NOT NULL
                        ORDER BY ingested_at DESC
                        LIMIT 10
                        """
                    )
                    pending = cur.fetchall()

                for row in pending:
                    try:
                        extracted = await extract_article_content(row["url"])
                        if extracted.get("content"):
                            with conn.cursor() as cur:
                                cur.execute(
                                    """
                                    UPDATE public.articles
                                    SET content = %s,
                                        summary = COALESCE(summary, %s),
                                        image_url = COALESCE(image_url, %s),
                                        content_extracted = true
                                    WHERE id = %s
                                    """,
                                    (
                                        extracted["content"],
                                        extracted.get("summary"),
                                        extracted.get("image_url"),
                                        row["id"],
                                    ),
                                )
                        else:
                            # Mark as extracted even if empty to avoid retrying
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE public.articles SET content_extracted = true WHERE id = %s",
                                    (row["id"],),
                                )
                    except Exception as e:
                        print(f"Ingestion: Error extracting content for {row['url'][:60]}: {e}")

                # 3. Clean up articles older than 7 days
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM public.articles WHERE ingested_at < now() - interval '7 days'"
                    )
                    if cur.rowcount > 0:
                        print(f"Ingestion: Cleaned up {cur.rowcount} old articles")

        except Exception as e:
            print(f"Ingestion loop error: {e}")
            import traceback
            traceback.print_exc()

        # Wait 5 minutes before next cycle
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app):
    """Start background ingestion on startup, cancel on shutdown."""
    task = asyncio.create_task(_ingestion_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Daily API", version="0.2.0", lifespan=lifespan)


def get_db():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def _ensure_tables(conn) -> None:
    """Ensure all required database tables exist."""
    with conn.cursor() as cur:
        # Core user tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.users (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                email text,
                display_name text,
                photo_url text,
                is_deleted boolean DEFAULT false,
                last_login timestamptz,
                created_at timestamptz DEFAULT now(),
                updated_at timestamptz DEFAULT now()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.user_identities (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                provider text NOT NULL,
                provider_user_id text NOT NULL,
                email text,
                raw_profile jsonb,
                created_at timestamptz DEFAULT now(),
                UNIQUE (provider, provider_user_id)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.sessions (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                token_hash text NOT NULL UNIQUE,
                created_at timestamptz DEFAULT now(),
                last_seen_at timestamptz DEFAULT now(),
                expires_at timestamptz
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.user_preferences (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id uuid NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
                interests text,
                ai_profile text,
                completed boolean DEFAULT false,
                completed_at timestamptz,
                created_at timestamptz DEFAULT now(),
                updated_at timestamptz DEFAULT now()
            );
        """)

        # Shared articles pool
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.articles (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                url text NOT NULL UNIQUE,
                title text NOT NULL,
                summary text,
                content text,
                author text,
                source_name text,
                image_url text,
                published_at timestamptz,
                ingested_at timestamptz NOT NULL DEFAULT now(),
                category text,
                content_extracted boolean DEFAULT false
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_published ON public.articles (published_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_ingested ON public.articles (ingested_at DESC);")

        # Per-user feed cache
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.user_feed_cache (
                user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
                relevance_score float NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (user_id, article_id)
            );
        """)




async def _verify_google_id_token(id_token: str) -> dict:
    """Verify Google ID token and extract user info"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    data = r.json()
    return {
        "provider": "google",
        "provider_user_id": data.get("sub"),
        "email": data.get("email"),
        "name": data.get("name"),
        "picture": data.get("picture"),
        "raw": data,  # Store raw response for raw_profile
    }


async def _verify_apple_identity_token(identity_token: str) -> dict:
    """Verify Apple identity token and extract user info"""
    APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
    async with httpx.AsyncClient(timeout=10) as client:
        jwks = (await client.get(APPLE_JWKS_URL)).json()
    try:
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
            options={"verify_aud": False},  # Apple doesn't always include aud
        )
        return {
            "provider": "apple",
            "provider_user_id": decoded.get("sub"),
            "email": decoded.get("email"),
            "name": None,  # Apple doesn't provide name in identity token
            "picture": None,
            "raw": decoded,  # Store raw decoded token for raw_profile
        }
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid Apple token")


def _upsert_user_from_oauth(conn, oauth_data: dict) -> dict:
    """Create or update user from OAuth provider data"""
    email = oauth_data.get("email")
    name = oauth_data.get("name")
    picture = oauth_data.get("picture")
    provider = oauth_data["provider"]
    provider_user_id = oauth_data["provider_user_id"]
    
    with conn.cursor() as cur:
        # Check if user exists by email
        if email:
            cur.execute(
                """
                SELECT id, email, display_name, photo_url FROM public.users
                WHERE lower(email) = lower(%s) AND is_deleted = false
                """,
                (email,),
            )
            existing = cur.fetchone()
            if existing:
                user_id = existing["id"]
                # Update user info
                cur.execute(
                    """
                    UPDATE public.users 
                    SET display_name = COALESCE(%s, display_name), 
                        photo_url = COALESCE(%s, photo_url), 
                        last_login = now(), 
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (name, picture, user_id),
                )
            else:
                # Create new user
                cur.execute(
                    """
                    INSERT INTO public.users (email, display_name, photo_url, last_login)
                    VALUES (LOWER(%s), %s, %s, now())
                    RETURNING id, email, display_name, photo_url
                    """,
                    (email, name, picture),
                )
                row = cur.fetchone()
                user_id = row["id"]
        else:
            # No email - create anonymous user
            cur.execute(
                """
                INSERT INTO public.users (display_name, photo_url, last_login)
                VALUES (%s, %s, now())
                RETURNING id, email, display_name, photo_url
                """,
                (name, picture),
            )
            row = cur.fetchone()
            user_id = row["id"]
        
        # Upsert identity - convert dict to jsonb
        import json
        raw_profile_json = json.dumps(oauth_data.get("raw", {}))
        cur.execute(
            """
            INSERT INTO public.user_identities (user_id, provider, provider_user_id, email, raw_profile)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (provider, provider_user_id)
            DO UPDATE SET user_id = EXCLUDED.user_id, email = EXCLUDED.email
            """,
            (user_id, provider, provider_user_id, email, raw_profile_json),
        )
        
        # Get final user data
        cur.execute(
            "SELECT id, email, display_name, photo_url FROM public.users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return {
            "id": str(row["id"]),  # Convert UUID to string for JSON
            "email": row.get("email"),
            "display_name": row.get("display_name"),
            "photo_url": row.get("photo_url"),
        }


@app.post("/auth/google")
async def auth_google(payload: dict, conn=Depends(get_db)):
    """Authenticate with Google - verify token and create/update user"""
    try:
        id_token = payload.get("id_token")
        if not id_token:
            raise HTTPException(status_code=400, detail="id_token is required")
        
        # Verify Google token and get user info
        oauth_data = await _verify_google_id_token(id_token)
        
        # Create or update user in database
        user = _upsert_user_from_oauth(conn, oauth_data)
        
        # Generate a simple session token
        token_data = f"{user['id']}:{oauth_data['provider_user_id']}:{int(time.time())}"
        session_token = base64.urlsafe_b64encode(hashlib.sha256(token_data.encode()).digest()).decode()[:32]
        
        # Store session - convert string ID back to UUID for database
        import uuid
        user_uuid = uuid.UUID(user['id'])
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()
        
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.sessions (user_id, token_hash, created_at, last_seen_at, expires_at)
                VALUES (%s, %s, now(), now(), now() + interval '30 days')
                ON CONFLICT (token_hash) DO UPDATE SET last_seen_at = now()
                """,
                (user_uuid, token_hash),
            )
        
        return {"token": session_token, "user": user}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/auth/apple")
async def auth_apple(payload: dict, conn=Depends(get_db)):
    """Authenticate with Apple - verify token and create/update user"""
    try:
        identity_token = payload.get("identity_token")
        if not identity_token:
            raise HTTPException(status_code=400, detail="identity_token is required")
        
        # Verify Apple token and get user info
        oauth_data = await _verify_apple_identity_token(identity_token)
        
        # Create or update user in database
        user = _upsert_user_from_oauth(conn, oauth_data)
        
        # Generate a simple session token
        token_data = f"{user['id']}:{oauth_data['provider_user_id']}:{int(time.time())}"
        session_token = base64.urlsafe_b64encode(hashlib.sha256(token_data.encode()).digest()).decode()[:32]
        
        # Store session - convert string ID back to UUID for database
        import uuid
        user_uuid = uuid.UUID(user['id'])
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()
        
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.sessions (user_id, token_hash, created_at, last_seen_at, expires_at)
                VALUES (%s, %s, now(), now(), now() + interval '30 days')
                ON CONFLICT (token_hash) DO UPDATE SET last_seen_at = now()
                """,
                (user_uuid, token_hash),
            )
        
        return {"token": session_token, "user": user}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


def _require_auth(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    return authorization.split(" ", 1)[1]


def _get_user_id_from_token(conn, token: str) -> str:
    """Resolve user_id (UUID as string) from session token"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.id
            FROM public.sessions s
            JOIN public.users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND (s.expires_at IS NULL OR s.expires_at > now())
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return str(row["id"])


@app.get("/me")
async def me(Authorization: str | None = Header(default=None), conn=Depends(get_db)):
    """Get current user by verifying session token"""
    token = _require_auth(Authorization)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
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
        return {
            "id": str(row["id"]),
            "email": row.get("email"),
            "display_name": row.get("display_name"),
            "photo_url": row.get("photo_url"),
        }


@app.post("/chat")
async def chat(payload: dict, Authorization: str | None = Header(default=None)):
    """
    General chat with AI - requires authentication.
    Supports optional conversation history and article context for the
    "Discuss Article" feature.
    """
    token = _require_auth(Authorization)

    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    history = payload.get("history") or []
    article_context = payload.get("article_context")

    try:
        from app.services.openai_service import get_openai_service

        openai_service = get_openai_service()

        system_prompt = (
            "You are Daily's AI — a sharp, knowledgeable news analyst built into a personalized news app.\n\n"
            "Your role:\n"
            "- Help users understand the news: explain context, implications, who's involved, and why it matters.\n"
            "- When discussing a specific article, reference its details naturally. Offer analysis, not just summaries.\n"
            "- Give balanced perspectives. Flag when something is opinion vs fact.\n"
            "- Be conversational but substantive — like a smart friend who reads everything.\n"
            "- Keep responses concise (2-4 paragraphs max) unless the user asks for depth.\n"
            "- Use plain language. No jargon unless the user clearly knows the domain.\n\n"
            "You can:\n"
            "- Compare current events to historical parallels\n"
            "- Explain technical/financial/political concepts simply\n"
            "- Identify what's missing from a story or what to watch next\n"
            "- Give \"so what?\" analysis — why should the reader care?\n\n"
            "Never:\n"
            "- Make up facts or statistics\n"
            "- Give financial, legal, or medical advice\n"
            "- Be preachy or condescending"
        )

        messages = [{"role": "system", "content": system_prompt}]

        # If discussing a specific article, inject its content as context
        if article_context and isinstance(article_context, dict):
            ctx_title = article_context.get("title", "")
            ctx_source = article_context.get("source", "")
            ctx_summary = article_context.get("summary", "")
            ctx_content = (article_context.get("content") or "")[:3000]

            article_msg = (
                "The user is reading this article and wants to discuss it:\n\n"
                f"Title: {ctx_title}\n"
                f"Source: {ctx_source}\n"
                f"Summary: {ctx_summary}\n\n"
                f"Full text:\n{ctx_content}"
            )
            messages.append({"role": "system", "content": article_msg})

        # Append conversation history
        for h in history:
            role = h.get("role")
            content = h.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # Append current message
        messages.append({"role": "user", "content": message})

        import asyncio

        response = await asyncio.to_thread(
            openai_service.client.chat.completions.create,
            model=openai_service.model,
            messages=messages,
            temperature=0.7,
        )

        ai_response = response.choices[0].message.content

        return {
            "response": ai_response,
            "model": openai_service.model,
        }
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error chatting with AI: {str(e)}")


@app.get("/user/preferences")
async def get_user_preferences(
    Authorization: str | None = Header(default=None), conn=Depends(get_db)
):
    """Fetch current user's news preferences and onboarding completion flag."""
    token = _require_auth(Authorization)

    user_id = _get_user_id_from_token(conn, token)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, interests, ai_profile, completed, completed_at
            FROM public.user_preferences
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        # Default: not completed, no preferences yet
        return {
            "user_id": user_id,
            "completed": False,
            "interests": None,
            "ai_profile": None,
            "completed_at": None,
        }

    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "interests": row.get("interests"),
        "ai_profile": row.get("ai_profile"),
        "completed": row.get("completed", False),
        "completed_at": row.get("completed_at").isoformat()
        if row.get("completed_at")
        else None,
    }


@app.post("/user/preferences")
async def save_user_preferences(
    payload: dict, Authorization: str | None = Header(default=None), conn=Depends(get_db)
):
    """
    Save user's interest onboarding result.

    Expected payload:
    - interests: arbitrary JSON structure describing user interests
    - ai_profile: string that summarizes user preferences / contains filtering prompt
    - completed: optional bool (defaults to true)

    This endpoint assumes ai_profile and interests are already computed on the client.
    For the main onboarding flow we instead recommend using /user/preferences/complete
    which asks the AI to summarize the chat history and store a compact profile.
    """
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    interests = payload.get("interests")
    ai_profile = payload.get("ai_profile")
    completed = bool(payload.get("completed", True))

    if not ai_profile:
        raise HTTPException(status_code=400, detail="ai_profile is required")

    # Prepare JSON for interests (can be None)
    import json
    interests_json = json.dumps(interests) if interests is not None else None

    with conn.cursor() as cur:
        # Upsert row for this user
        cur.execute(
            """
            INSERT INTO public.user_preferences (user_id, interests, ai_profile, completed, completed_at, updated_at)
            VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END, now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                interests = EXCLUDED.interests,
                ai_profile = EXCLUDED.ai_profile,
                completed = EXCLUDED.completed,
                completed_at = CASE WHEN EXCLUDED.completed THEN now() ELSE user_preferences.completed_at END,
                updated_at = now()
            RETURNING id, user_id, interests, ai_profile, completed, completed_at
            """,
            (user_id, interests_json, ai_profile, completed, completed),
        )
        row = cur.fetchone()

    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "interests": row.get("interests"),
        "ai_profile": row.get("ai_profile"),
        "completed": row.get("completed", False),
        "completed_at": row.get("completed_at").isoformat()
        if row.get("completed_at")
        else None,
    }


@app.post("/user/preferences/complete")
async def complete_user_preferences(
    payload: dict, Authorization: str | None = Header(default=None), conn=Depends(get_db)
):
    """
    Take the full onboarding chat history, ask AI to summarize it into a compact
    filtering prompt and structured interests, then save that profile for the user.

    Expected payload:
    - history: list of { "role": "user" | "assistant", "content": "..." }
    """
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    history = payload.get("history") or []
    if not isinstance(history, list) or not history:
        raise HTTPException(status_code=400, detail="history is required and must be a non-empty list")

    try:
        from app.services.openai_service import get_openai_service
        import json

        openai_service = get_openai_service()

        # Convert history into readable transcript
        transcript_lines = []
        for turn in history:
            role = turn.get("role", "")
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            label = "User" if role == "user" else "Assistant"
            transcript_lines.append(f"{label}: {content}")

        transcript = "\n".join(transcript_lines)

        system_prompt = """
You are helping configure a personalized news feed for a single user.
You will read the full chat transcript between the user and an assistant.

Your task:
- Extract what topics, people, locations, industries, and themes the user WANTS to see.
- Extract what they explicitly do NOT want to see.
- Produce a compact, robust prompt that another AI can use later to filter news.

Output STRICTLY valid JSON with this exact shape:
{
  "ai_profile": "string - a single prompt the AI will use to filter and rank news for this user",
  "interests": {
    "topics": ["string"],
    "people": ["string"],
    "locations": ["string"],
    "industries": ["string"],
    "excluded_topics": ["string"],
    "notes": "string - any extra nuance"
  }
}

Do not include any other top-level keys. Do not wrap in backticks. Do not explain.
"""

        user_prompt = f"Here is the full transcript of our onboarding chat:\n\n{transcript}\n\nNow produce the JSON as specified."

        import asyncio

        response = await asyncio.to_thread(
            openai_service.client.chat.completions.create,
            model=openai_service.model,
            messages=[
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        content = response.choices[0].message.content

        try:
            summary = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: treat whole content as ai_profile, keep interests minimal
            summary = {
                "ai_profile": content,
                "interests": {
                    "topics": [],
                    "people": [],
                    "locations": [],
                    "industries": [],
                    "excluded_topics": [],
                    "notes": "Failed to parse structured JSON; using raw summary text only.",
                },
            }

        ai_profile = summary.get("ai_profile")
        interests = summary.get("interests")

        if not ai_profile or not isinstance(ai_profile, str):
            raise HTTPException(status_code=500, detail="AI did not return a valid ai_profile")

        interests_json = json.dumps(interests) if interests is not None else None

        # Save to database
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.user_preferences (user_id, interests, ai_profile, completed, completed_at, updated_at)
                VALUES (%s, %s, %s, true, now(), now())
                ON CONFLICT (user_id)
                DO UPDATE SET
                    interests = EXCLUDED.interests,
                    ai_profile = EXCLUDED.ai_profile,
                    completed = true,
                    completed_at = now(),
                    updated_at = now()
                RETURNING id, user_id, interests, ai_profile, completed, completed_at
                """,
                (user_id, interests_json, ai_profile,),
            )
            row = cur.fetchone()

        return {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "interests": row.get("interests"),
            "ai_profile": row.get("ai_profile"),
            "completed": row.get("completed", False),
            "completed_at": row.get("completed_at").isoformat()
            if row.get("completed_at")
            else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error completing user preferences: {str(e)}")


@app.post("/chat/interests")
async def chat_interests(payload: dict, Authorization: str | None = Header(default=None)):
    """
    Onboarding chat specifically about user's news interests.

    This endpoint does NOT save anything by itself; the client will call
    /user/preferences with the final summary when user taps Save.
    """
    token = _require_auth(Authorization)

    message = payload.get("message")
    history = payload.get("history") or []

    if not message and not history:
        raise HTTPException(status_code=400, detail="message or history is required")

    try:
        from app.services.openai_service import get_openai_service

        openai_service = get_openai_service()

        system_prompt = """
You are an onboarding assistant helping a user configure their personal news feed.

Your goal:
- Ask friendly, short questions to understand what kind of news they want to see.
- Clarify topics, categories, locations, people, industries, and things they do NOT want.
- Keep replies concise and conversational.

IMPORTANT:
- Do NOT output JSON or code.
- Do NOT summarize their preferences here. Just continue the conversation.
- The app will later summarize this chat into a profile.
"""

        messages = [{"role": "system", "content": system_prompt.strip()}]

        # Optional: include prior chat turns
        # history: [{ "role": "user"/"assistant", "content": "..." }, ...]
        for h in history:
            role = h.get("role")
            content = h.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        if message:
            messages.append({"role": "user", "content": message})

        import asyncio

        response = await asyncio.to_thread(
            openai_service.client.chat.completions.create,
            model=openai_service.model,
            messages=messages,
            temperature=0.7,
        )

        ai_response = response.choices[0].message.content

        return {
            "response": ai_response,
            "model": openai_service.model,
        }
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Error chatting about interests: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Feed endpoints (new architecture)
# ---------------------------------------------------------------------------

@app.get("/feed")
async def get_feed(
    Authorization: str | None = Header(default=None),
    limit: int = 20,
    conn=Depends(get_db),
):
    """Return a personalized news feed from the shared article pool."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    try:
        from app.services.feed_service import get_personalized_feed

        _ensure_tables(conn)
        articles = await get_personalized_feed(user_id, conn, limit=limit)
        return articles
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error loading feed: {str(e)}")


@app.get("/feed/{article_id}")
async def get_feed_article(
    article_id: str,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Return a single article with full content (extracts on-demand if needed)."""
    token = _require_auth(Authorization)

    try:
        from app.services.feed_service import get_article_by_id

        article = await get_article_by_id(article_id, conn)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        return article
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error loading article: {str(e)}")


@app.post("/feed/refresh")
async def refresh_feed(
    Authorization: str | None = Header(default=None),
    limit: int = 20,
    conn=Depends(get_db),
):
    """Force re-score articles for this user (ignores cache)."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    try:
        from app.services.feed_service import get_personalized_feed

        _ensure_tables(conn)
        articles = await get_personalized_feed(user_id, conn, limit=limit, force_refresh=True)
        return articles
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error refreshing feed: {str(e)}")


# ---------------------------------------------------------------------------
# Legacy endpoints removed — the old /news/* endpoints are replaced by /feed
# ---------------------------------------------------------------------------

