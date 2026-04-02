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
from fastapi.responses import JSONResponse, StreamingResponse
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from app.services import chat_repository
from app.services.chat_service import ChatService
from app.services.openai_service import get_openai_service
from app.services.profile_model import (
    build_source_selection_brief,
    derive_profile_v2_from_preferences,
    dumps_json,
    loads_json,
    normalize_user_profile_v2,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")


# ---------------------------------------------------------------------------
# Background ingestion loop
# ---------------------------------------------------------------------------

async def _ingestion_loop():
    """Background task: fetch RSS feeds, extract content, clean up old articles."""
    from app.services.news_ingestion import fetch_rss_feeds, fetch_topic_feeds
    from app.services.content_extractor import extract_article_content
    from app.services.article_enrichment import enrich_articles
    from app.services.source_discovery import populate_seed_sources

    # Wait a few seconds for the app to fully start
    await asyncio.sleep(5)
    print("Ingestion worker started")

    while True:
        try:
            # 1. Fetch RSS feeds
            with pool.connection() as conn:
                _ensure_tables(conn)
                await populate_seed_sources(conn)
                new_count = await fetch_rss_feeds(conn)
                topic_count = await fetch_topic_feeds(conn)
                print(f"Ingestion: {new_count} from RSS, {topic_count} from topics")

                # 2. Extract content for articles that don't have it yet (batch of 20, 6 concurrent)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, url FROM public.articles
                        WHERE content_extracted = false AND url IS NOT NULL
                        ORDER BY ingested_at DESC
                        LIMIT 20
                        """
                    )
                    pending = cur.fetchall()

                extraction_semaphore = asyncio.Semaphore(6)

                async def _extract_one(row):
                    async with extraction_semaphore:
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
                                with conn.cursor() as cur:
                                    cur.execute(
                                        "UPDATE public.articles SET content_extracted = true WHERE id = %s",
                                        (row["id"],),
                                    )
                        except Exception as e:
                            print(f"Ingestion: Error extracting content for {row['url'][:60]}: {e}")

                if pending:
                    await asyncio.gather(*[_extract_one(row) for row in pending], return_exceptions=True)

                # 2b. Generate embeddings for articles with content but no embedding
                openai_svc = get_openai_service()
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, title, summary, content FROM public.articles
                        WHERE content IS NOT NULL AND embedding IS NULL
                        LIMIT 50
                    """)
                    embed_pending = cur.fetchall()

                if embed_pending:
                    embed_sem = asyncio.Semaphore(6)

                    async def _embed_one(row):
                        async with embed_sem:
                            text = f"{row['title']}. {row.get('summary') or ''}. {(row.get('content') or '')[:2000]}"
                            embedding = await openai_svc.generate_embedding(text)
                            if embedding:
                                with conn.cursor() as cur:
                                    cur.execute(
                                        "UPDATE public.articles SET embedding = %s::vector WHERE id = %s",
                                        (str(embedding), row["id"]),
                                    )

                    await asyncio.gather(*[_embed_one(r) for r in embed_pending], return_exceptions=True)
                    print(f"Ingestion: Generated embeddings for {len(embed_pending)} articles")

                # 3. Enrich articles (expand thin content, find missing images)
                enrichment_stats = await enrich_articles(conn)
                if enrichment_stats["content_enriched"] or enrichment_stats["images_found"]:
                    print(
                        f"Ingestion: Enriched {enrichment_stats['content_enriched']} thin articles, "
                        f"found {enrichment_stats['images_found']} images"
                    )

                # 4. Clean up articles older than 14 days (extended for behavioral learning)
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM public.articles WHERE ingested_at < now() - interval '14 days'"
                    )
                    if cur.rowcount > 0:
                        print(f"Ingestion: Cleaned up {cur.rowcount} old articles")

        except Exception as e:
            print(f"Ingestion loop error: {e}")
            import traceback
            traceback.print_exc()

        # Wait 3 minutes before next cycle
        await asyncio.sleep(180)


pool: ConnectionPool | None = None


async def _source_quality_loop():
    """Background task: update global source quality scores every 30 min."""
    from app.services.source_quality import update_source_quality
    await asyncio.sleep(60)  # Let ingestion get some data first
    while True:
        try:
            with pool.connection() as conn:
                await update_source_quality(conn)
        except Exception as e:
            print(f"Source quality loop error: {e}")
        await asyncio.sleep(1800)  # 30 minutes


async def _interest_evolution_loop():
    """Background task: check for interest evolution every 6 hours."""
    from app.services.interest_evolution import check_interest_evolution
    await asyncio.sleep(300)  # Let reading events accumulate
    while True:
        try:
            with pool.connection() as conn:
                await check_interest_evolution(conn)
        except Exception as e:
            print(f"Interest evolution loop error: {e}")
        await asyncio.sleep(21600)  # 6 hours


async def _per_user_refresh_loop():
    """Background task: refresh articles from per-user sources every 30 minutes."""
    from app.services.user_source_pipeline import build_feed_for_user

    await asyncio.sleep(120)  # Let startup settle
    print("Per-user refresh loop started")

    user_semaphore = asyncio.Semaphore(3)  # Max 3 users refreshed concurrently

    while True:
        try:
            with pool.connection() as conn:
                # Find users who have sources and were active in the last 24 hours
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT us.user_id
                        FROM public.user_sources us
                        WHERE us.active = true
                        AND EXISTS (
                            SELECT 1 FROM public.users u
                            WHERE u.id::text = us.user_id
                            AND u.last_active_at > now() - interval '24 hours'
                        )
                    """)
                    active_users = [row["user_id"] for row in cur.fetchall()]

            if active_users:
                async def _refresh_one(uid: str):
                    async with user_semaphore:
                        try:
                            with pool.connection() as conn:
                                await build_feed_for_user(conn, uid, limit=50)
                        except Exception as e:
                            print(f"Per-user refresh error for {uid[:8]}...: {e}")

                await asyncio.gather(
                    *[_refresh_one(uid) for uid in active_users],
                    return_exceptions=True,
                )
                print(f"Per-user refresh: processed {len(active_users)} users")

        except Exception as e:
            print(f"Per-user refresh loop error: {e}")

        await asyncio.sleep(1800)  # 30 minutes


@asynccontextmanager
async def lifespan(app):
    """Start connection pool and background tasks on startup."""
    global pool
    pool = ConnectionPool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        kwargs={"row_factory": dict_row, "autocommit": True},
    )
    ingestion_task = asyncio.create_task(_ingestion_loop())
    quality_task = asyncio.create_task(_source_quality_loop())
    evolution_task = asyncio.create_task(_interest_evolution_loop())
    per_user_task = asyncio.create_task(_per_user_refresh_loop())
    yield
    for t in (ingestion_task, quality_task, evolution_task, per_user_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    pool.close()


app = FastAPI(title="Daily API", version="0.2.0", lifespan=lifespan)
chat_service = ChatService()


def get_db():
    with pool.connection() as conn:
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
                user_profile_v2 text,
                source_selection_brief text,
                completed boolean DEFAULT false,
                completed_at timestamptz,
                created_at timestamptz DEFAULT now(),
                updated_at timestamptz DEFAULT now()
            );
        """)
        cur.execute("ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS user_profile_v2 text;")
        cur.execute("ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS source_selection_brief text;")

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
                relevant boolean DEFAULT false,
                relevance_reason text,
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (user_id, article_id)
            );
        """)
        # Migration: add columns for existing databases
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS relevant boolean DEFAULT false;")
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS relevance_reason text;")
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS feed_role text;")
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS why_this_story text;")
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS why_now text;")
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS matched_profile_signals jsonb DEFAULT '[]'::jsonb;")
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS cluster_id text;")
        cur.execute("ALTER TABLE public.user_feed_cache ADD COLUMN IF NOT EXISTS importance_score float DEFAULT 0.0;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_feed_cache_user_created ON public.user_feed_cache (user_id, created_at DESC);")

        # Migration: add enrichment tracking columns
        cur.execute("ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS enrichment_completed boolean DEFAULT false;")
        cur.execute("ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS enrichment_attempts integer DEFAULT 0;")

        # Migration: pgvector for semantic search
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS embedding vector(1536);")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_embedding
            ON public.articles USING hnsw (embedding vector_cosine_ops);
        """)

        # Migration: behavior_cache on user_preferences (ENG-5)
        cur.execute("ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS behavior_cache text;")

        # Curated seed sources (global, maintained by system)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.seed_sources (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                url TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                category TEXT,
                quality_tier TEXT DEFAULT 'standard',
                active BOOLEAN DEFAULT true,
                failure_count INTEGER DEFAULT 0,
                last_validated_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)

        # Per-user discovered sources
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.user_sources (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                source_url TEXT NOT NULL,
                source_name TEXT,
                category TEXT,
                discovery_method TEXT DEFAULT 'seed',
                active BOOLEAN DEFAULT true,
                failure_count INTEGER DEFAULT 0,
                last_fetched_at TIMESTAMPTZ,
                validated_at TIMESTAMPTZ,
                next_fetch_at TIMESTAMPTZ DEFAULT now(),
                etag TEXT,
                last_modified TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE(user_id, source_url)
            );
        """)
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS scope TEXT DEFAULT 'supporting';")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS source_kind TEXT DEFAULT 'publisher';")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS matched_targets JSONB DEFAULT '[]'::jsonb;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS discovery_score FLOAT DEFAULT 0.0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS selection_rank INTEGER DEFAULT 0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS last_discovered_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS selection_reason TEXT;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS coverage_role TEXT DEFAULT 'adjacent';")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS matched_topics JSONB DEFAULT '[]'::jsonb;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS matched_entities JSONB DEFAULT '[]'::jsonb;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS precision_score FLOAT DEFAULT 0.0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS breadth_score FLOAT DEFAULT 0.0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS last_article_yield INTEGER DEFAULT 0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS last_relevant_yield INTEGER DEFAULT 0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS article_diversity FLOAT DEFAULT 0.0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS duplicate_rate FLOAT DEFAULT 0.0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS image_coverage FLOAT DEFAULT 0.0;")
        cur.execute("ALTER TABLE public.user_sources ADD COLUMN IF NOT EXISTS engagement_yield FLOAT DEFAULT 0.0;")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_sources_user_active
            ON public.user_sources (user_id, active) WHERE active = true;
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_sources_next_fetch
            ON public.user_sources (next_fetch_at) WHERE active = true;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.article_source_links (
                article_id UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
                source_url TEXT NOT NULL,
                fetched_at TIMESTAMPTZ DEFAULT now(),
                published_at TIMESTAMPTZ,
                PRIMARY KEY (article_id, source_url)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_article_source_links_source
            ON public.article_source_links (source_url, fetched_at DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_article_source_links_article
            ON public.article_source_links (article_id);
        """)

        # Reading events for behavioral learning
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.reading_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                article_id UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                duration_seconds INTEGER,
                feed_request_id UUID,
                position_in_feed INTEGER,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reading_events_user
            ON public.reading_events (user_id, created_at DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reading_events_article
            ON public.reading_events (article_id);
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reading_events_dedup
            ON public.reading_events (user_id, article_id, event_type, feed_request_id);
        """)

        # Global source quality scoring
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.source_quality (
                source_domain TEXT PRIMARY KEY,
                impressions INTEGER DEFAULT 0,
                taps INTEGER DEFAULT 0,
                reads INTEGER DEFAULT 0,
                avg_read_duration FLOAT DEFAULT 0,
                quality_score FLOAT DEFAULT 0.5,
                updated_at TIMESTAMPTZ DEFAULT now()
            );
        """)

        # Entity pins for tracking people/companies/topics
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.entity_pins (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                entity_name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'topic',
                created_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE(user_id, entity_name)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_pins_user
            ON public.entity_pins (user_id);
        """)

        # Briefing cache
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.briefing_cache (
                user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                source_article_ids UUID[],
                generated_at TIMESTAMPTZ DEFAULT now()
            );
        """)

        # Interest evolution suggestions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.interest_suggestions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                confidence FLOAT NOT NULL,
                source_articles UUID[],
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE(user_id, topic)
            );
        """)
    chat_repository.ensure_chat_tables(conn)




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


def _format_datetime_iso(dt) -> str | None:
    """Format datetime to ISO8601 with millisecond precision and explicit timezone.

    Python's datetime.isoformat() can produce microsecond precision (6 digits)
    and may omit timezone for naive datetimes — both break Apple's
    ISO8601DateFormatter.  This helper normalises to 3-digit fractional seconds
    with an explicit UTC offset.
    """
    if dt is None:
        return None
    from datetime import timezone

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="milliseconds")


def _parse_interests(raw) -> dict | None:
    """Parse interests from DB text column (JSON string) into a dict."""
    import json
    if raw and isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict):
        return raw
    return None


def _parse_profile_v2(raw) -> dict | None:
    return loads_json(raw)


def _has_interest_values(interests: dict | None) -> bool:
    if not isinstance(interests, dict):
        return False

    for key in ("topics", "people", "locations", "industries", "excluded_topics"):
        values = interests.get(key)
        if isinstance(values, list) and any(str(value).strip() for value in values):
            return True

    notes = interests.get("notes")
    return isinstance(notes, str) and bool(notes.strip())


def _clear_user_feed_cache(conn, user_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.user_feed_cache WHERE user_id = %s", (user_id,))


def _clear_user_source_graph(conn, user_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.user_sources WHERE user_id = %s", (user_id,))


def _serialize_user_source(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "source_url": row.get("source_url"),
        "source_name": row.get("source_name"),
        "category": row.get("category"),
        "discovery_method": row.get("discovery_method"),
        "source_kind": row.get("source_kind"),
        "scope": row.get("scope"),
        "selection_reason": row.get("selection_reason"),
        "coverage_role": row.get("coverage_role"),
        "matched_targets": row.get("matched_targets") or [],
        "matched_topics": row.get("matched_topics") or [],
        "matched_entities": row.get("matched_entities") or [],
        "precision_score": row.get("precision_score"),
        "breadth_score": row.get("breadth_score"),
        "discovery_score": row.get("discovery_score"),
        "selection_rank": row.get("selection_rank"),
        "last_article_yield": row.get("last_article_yield"),
        "last_relevant_yield": row.get("last_relevant_yield"),
        "article_diversity": row.get("article_diversity"),
        "duplicate_rate": row.get("duplicate_rate"),
        "image_coverage": row.get("image_coverage"),
        "engagement_yield": row.get("engagement_yield"),
        "last_discovered_at": _format_datetime_iso(row.get("last_discovered_at")),
        "last_fetched_at": _format_datetime_iso(row.get("last_fetched_at")),
    }


def _load_user_sources_snapshot(conn, user_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source_url, source_name, category, discovery_method, source_kind,
                   scope, selection_reason, coverage_role, matched_targets, matched_topics,
                   matched_entities, precision_score, breadth_score, discovery_score,
                   selection_rank, last_article_yield, last_relevant_yield, article_diversity,
                   duplicate_rate, image_coverage, engagement_yield, last_discovered_at,
                   last_fetched_at
            FROM public.user_sources
            WHERE user_id = %s AND active = true
            ORDER BY selection_rank ASC, discovery_score DESC
            """,
            (user_id,),
        )
        return [_serialize_user_source(row) for row in cur.fetchall()]


def _build_user_preferences_response(row: dict | None, *, user_id: str) -> dict:
    if not row:
        return {
            "user_id": user_id,
            "completed": False,
            "interests": None,
            "ai_profile": None,
            "user_profile_v2": None,
            "source_selection_brief": None,
            "completed_at": None,
        }

    user_profile_v2 = _parse_profile_v2(row.get("user_profile_v2"))
    source_selection_brief = loads_json(row.get("source_selection_brief"))

    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "interests": _parse_interests(row.get("interests")),
        "ai_profile": row.get("ai_profile"),
        "user_profile_v2": user_profile_v2,
        "source_selection_brief": source_selection_brief,
        "completed": row.get("completed", False),
        "completed_at": _format_datetime_iso(row.get("completed_at")),
    }


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


@app.get("/chat/threads")
async def list_chat_threads(
    Authorization: str | None = Header(default=None),
    limit: int = Query(default=40, ge=1, le=100),
    conn=Depends(get_db),
):
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    _ensure_tables(conn)
    threads = await chat_service.list_threads(conn, user_id=user_id, limit=limit)
    return {"threads": threads}


@app.post("/chat/threads")
async def create_chat_thread(
    payload: dict,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    _ensure_tables(conn)
    thread = await chat_service.create_thread(
        conn,
        user_id=user_id,
        kind=str(payload.get("kind") or "manual"),
        title=payload.get("title"),
        article_id=payload.get("article_id"),
        article_title=payload.get("article_title"),
        local_day=payload.get("local_day"),
    )
    return thread


@app.get("/chat/threads/{thread_id}")
async def get_chat_thread(
    thread_id: str,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    _ensure_tables(conn)
    return await chat_service.get_thread_detail(conn, user_id=user_id, thread_id=thread_id)


@app.post("/chat/threads/{thread_id}/messages/stream")
async def stream_chat_message(
    thread_id: str,
    payload: dict,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    _ensure_tables(conn)
    event_stream = await chat_service.stream_thread_message(
        conn,
        user_id=user_id,
        thread_id=thread_id,
        content=payload.get("content"),
        intent=payload.get("intent"),
    )
    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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

        # If multiple articles provided (e.g., from semantic search for chip prompts)
        articles_context = payload.get("articles_context")
        if articles_context and isinstance(articles_context, list):
            summaries = []
            for i, art in enumerate(articles_context[:10], 1):
                summaries.append(
                    f"{i}. [{art.get('source', 'Unknown')}] {art.get('title', '')}\n"
                    f"   {(art.get('summary') or '')[:200]}"
                )
            articles_msg = (
                "The user wants to discuss these articles from their news feed:\n\n"
                + "\n\n".join(summaries)
                + "\n\nReference specific articles by name/source when answering."
            )
            messages.append({"role": "system", "content": articles_msg})

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
        raise HTTPException(status_code=500, detail="Something went wrong — please try again.")


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
            SELECT id, user_id, interests, ai_profile, user_profile_v2, source_selection_brief,
                   completed, completed_at
            FROM public.user_preferences
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return _build_user_preferences_response(row, user_id=user_id)


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
    explicit_profile_v2 = payload.get("user_profile_v2")
    completed = bool(payload.get("completed", True))

    if not ai_profile:
        raise HTTPException(status_code=400, detail="ai_profile is required")

    normalized_interests = interests if isinstance(interests, dict) else None
    try:
        openai_service = get_openai_service()
        extracted_interests = await openai_service.extract_interests_from_profile(ai_profile)
        if _has_interest_values(extracted_interests):
            normalized_interests = extracted_interests
    except Exception:
        if normalized_interests is None:
            normalized_interests = None

    from app.services.source_discovery import determine_profile_specificity

    profile_specificity = determine_profile_specificity(normalized_interests, ai_profile)
    normalized_profile_v2 = normalize_user_profile_v2(
        explicit_profile_v2,
        fallback_specificity=profile_specificity,
    )
    if not any(normalized_profile_v2.get(key) for key in ("stable_interests", "current_interests", "people", "locations", "industries", "utility_priorities")):
        normalized_profile_v2 = derive_profile_v2_from_preferences(
            normalized_interests,
            ai_profile,
            explicit_context=explicit_profile_v2 if isinstance(explicit_profile_v2, dict) else None,
            specificity_level=profile_specificity,
        )
    source_selection_brief = build_source_selection_brief(
        normalized_interests,
        normalized_profile_v2,
        specificity_level=profile_specificity,
    )

    # Expand abstract exclusions into concrete matching phrases (one-time LLM cost)
    excluded_topics_list = (normalized_interests or {}).get("excluded_topics", [])
    if excluded_topics_list:
        try:
            expanded = await openai_service.expand_exclusion_patterns(
                excluded_topics_list, interests=normalized_interests,
            )
            if expanded:
                normalized_profile_v2["expanded_exclusions"] = expanded
        except Exception:
            logger.warning("Exclusion expansion failed; proceeding without expanded patterns")

    interests_json = dumps_json(normalized_interests)
    profile_json = dumps_json(normalized_profile_v2)
    source_brief_json = dumps_json(source_selection_brief)

    with conn.cursor() as cur:
        # Upsert row for this user
        cur.execute(
            """
            INSERT INTO public.user_preferences (
                user_id, interests, ai_profile, user_profile_v2, source_selection_brief,
                completed, completed_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END, now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                interests = EXCLUDED.interests,
                ai_profile = EXCLUDED.ai_profile,
                user_profile_v2 = EXCLUDED.user_profile_v2,
                source_selection_brief = EXCLUDED.source_selection_brief,
                completed = EXCLUDED.completed,
                completed_at = CASE WHEN EXCLUDED.completed THEN now() ELSE user_preferences.completed_at END,
                updated_at = now()
            RETURNING id, user_id, interests, ai_profile, user_profile_v2, source_selection_brief,
                      completed, completed_at
            """,
            (user_id, interests_json, ai_profile, profile_json, source_brief_json, completed, completed),
        )
        row = cur.fetchone()

    _clear_user_feed_cache(conn, user_id)
    _clear_user_source_graph(conn, user_id)
    response = _build_user_preferences_response(row, user_id=user_id)
    response["profile_specificity"] = profile_specificity
    response["setup_required"] = True
    response["source_selection_brief"] = source_selection_brief
    response["user_profile_v2"] = normalized_profile_v2
    return response


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
    explicit_context = payload.get("explicit_context")
    if not isinstance(history, list) or not history:
        raise HTTPException(status_code=400, detail="history is required and must be a non-empty list")

    try:
        openai_service = get_openai_service()
        summary = await openai_service.build_complete_user_preferences(
            history,
            explicit_context=explicit_context if isinstance(explicit_context, dict) else None,
        )

        ai_profile = summary.get("ai_profile")
        interests = summary.get("interests")
        user_profile_v2 = summary.get("user_profile_v2")
        source_selection_brief = summary.get("source_selection_brief")

        if not ai_profile or not isinstance(ai_profile, str):
            raise HTTPException(status_code=500, detail="AI did not return a valid ai_profile")

        from app.services.source_discovery import determine_profile_specificity

        profile_specificity = determine_profile_specificity(interests, ai_profile)
        normalized_profile_v2 = normalize_user_profile_v2(
            user_profile_v2,
            fallback_specificity=profile_specificity,
        )
        if not any(normalized_profile_v2.get(key) for key in ("stable_interests", "current_interests", "people", "locations", "industries", "utility_priorities")):
            normalized_profile_v2 = derive_profile_v2_from_preferences(
                interests,
                ai_profile,
                explicit_context=explicit_context if isinstance(explicit_context, dict) else None,
                specificity_level=profile_specificity,
            )
        source_selection_brief = build_source_selection_brief(
            interests,
            {**normalized_profile_v2, "source_selection_brief": source_selection_brief},
            specificity_level=profile_specificity,
        )

        # Expand abstract exclusions into concrete matching phrases (one-time LLM cost)
        excluded_topics_list = (interests or {}).get("excluded_topics", []) if isinstance(interests, dict) else []
        if excluded_topics_list:
            try:
                expanded = await openai_service.expand_exclusion_patterns(
                    excluded_topics_list, interests=interests if isinstance(interests, dict) else None,
                )
                if expanded:
                    normalized_profile_v2["expanded_exclusions"] = expanded
            except Exception:
                logger.warning("Exclusion expansion failed; proceeding without expanded patterns")

        interests_json = dumps_json(interests)
        profile_json = dumps_json(normalized_profile_v2)
        source_brief_json = dumps_json(source_selection_brief)

        # Save to database
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.user_preferences (
                    user_id, interests, ai_profile, user_profile_v2, source_selection_brief,
                    completed, completed_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, true, now(), now())
                ON CONFLICT (user_id)
                DO UPDATE SET
                    interests = EXCLUDED.interests,
                    ai_profile = EXCLUDED.ai_profile,
                    user_profile_v2 = EXCLUDED.user_profile_v2,
                    source_selection_brief = EXCLUDED.source_selection_brief,
                    completed = true,
                    completed_at = now(),
                    updated_at = now()
                RETURNING id, user_id, interests, ai_profile, user_profile_v2, source_selection_brief,
                          completed, completed_at
                """,
                (user_id, interests_json, ai_profile, profile_json, source_brief_json),
            )
            row = cur.fetchone()

        _clear_user_feed_cache(conn, user_id)
        _clear_user_source_graph(conn, user_id)
        response = _build_user_preferences_response(row, user_id=user_id)
        response["profile_specificity"] = profile_specificity
        response["setup_required"] = True
        response["user_profile_v2"] = normalized_profile_v2
        response["source_selection_brief"] = source_selection_brief
        return response
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
- Push for specificity before you stop asking questions.

Specificity gate:
- Broad inputs like "tech", "AI", "coding", "sports", or "business" are not enough by themselves.
- Ask follow-up questions until you have at least 3 concrete interests, entities, or subtopics.
- Examples:
  - "AI" -> ask whether they care about model launches, research, enterprise adoption, coding tools, or policy.
  - "Tech" -> ask whether they want startups, software engineering, gadgets, developer tools, or platform/company news.
  - "Sports" -> ask which league, sport, team, or athlete.
- If the user explicitly says they want broad/general headlines, accept that and stop pushing.

IMPORTANT:
- Keep replies concise and conversational.
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
            status_code=500, detail="Something went wrong — please try again."
        )


# ---------------------------------------------------------------------------
# Feed endpoints (new architecture)
# ---------------------------------------------------------------------------

_DISCOVERY_COOLDOWN_SECONDS = 300  # 5-minute cooldown between discoveries
_discovery_last_run: dict[str, float] = {}  # user_id -> timestamp


@app.post("/sources/discover")
async def discover_sources(
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Discover the source graph for the authenticated user."""
    import time

    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    # Cooldown: max 1 discovery per 5 minutes per user
    last_run = _discovery_last_run.get(user_id, 0)
    if time.time() - last_run < _DISCOVERY_COOLDOWN_SECONDS:
        remaining = int(_DISCOVERY_COOLDOWN_SECONDS - (time.time() - last_run))
        raise HTTPException(
            status_code=429,
            detail=f"Source discovery cooling down. Try again in {remaining}s.",
        )

    try:
        from app.services.source_discovery import discover_sources_for_user

        _ensure_tables(conn)

        # Advisory lock: prevent concurrent discovery for same user
        lock_key = abs(hash(user_id)) % (2**31)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
            acquired = cur.fetchone()["pg_try_advisory_lock"]

        if not acquired:
            raise HTTPException(status_code=409, detail="Discovery already in progress for this user")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ai_profile, interests, user_profile_v2, source_selection_brief
                    FROM public.user_preferences
                    WHERE user_id = %s AND completed = true
                    """,
                    (user_id,),
                )
                row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=400, detail="Complete onboarding before discovering sources")

            interests = _parse_interests(row.get("interests"))
            ai_profile = row.get("ai_profile") or ""
            user_profile_v2 = _parse_profile_v2(row.get("user_profile_v2"))
            source_selection_brief = loads_json(row.get("source_selection_brief"))
            result = await discover_sources_for_user(
                conn,
                user_id,
                interests or {},
                ai_profile,
                user_profile_v2=user_profile_v2,
                source_selection_brief=source_selection_brief,
            )
            _discovery_last_run[user_id] = time.time()
            return result
        finally:
            # Always release the advisory lock
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error discovering sources: {str(e)}")


@app.get("/sources")
async def list_sources(
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    _ensure_tables(conn)
    return {"sources": _load_user_sources_snapshot(conn, user_id)}


@app.post("/feed/build")
async def build_feed(
    Authorization: str | None = Header(default=None),
    limit: int = 50,
    conn=Depends(get_db),
):
    """Build the authenticated user's feed from their active source graph."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    try:
        import uuid
        from app.services.user_source_pipeline import build_feed_for_user

        _ensure_tables(conn)
        result = await build_feed_for_user(conn, user_id, limit=limit)
        if result["status"] == "ready":
            result["feed_request_id"] = str(uuid.uuid4())
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error building feed: {str(e)}")


@app.get("/feed")
async def get_feed(
    Authorization: str | None = Header(default=None),
    limit: int = 50,
    conn=Depends(get_db),
):
    """Return cached feed state for the authenticated user."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    try:
        import uuid
        from app.services.user_source_pipeline import get_feed_state

        _ensure_tables(conn)
        result = get_feed_state(conn, user_id, limit=limit)
        if result["status"] == "ready":
            result["feed_request_id"] = str(uuid.uuid4())
        return result
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
    limit: int = 50,
    conn=Depends(get_db),
):
    """Refresh the authenticated user's feed from their current source graph."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    try:
        import uuid
        from app.services.user_source_pipeline import build_feed_for_user

        _ensure_tables(conn)
        result = await build_feed_for_user(conn, user_id, limit=limit)
        if result["status"] == "ready":
            result["feed_request_id"] = str(uuid.uuid4())
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error refreshing feed: {str(e)}")


# ---------------------------------------------------------------------------
# Semantic search & categories
# ---------------------------------------------------------------------------


@app.post("/search/semantic")
async def semantic_search(
    payload: dict,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Search articles by semantic similarity using pgvector embeddings."""
    _require_auth(Authorization)

    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    limit = min(int(payload.get("limit", 8)), 20)

    try:
        openai_service = get_openai_service()
        embedding = await openai_service.generate_embedding(query)
        if not embedding:
            raise HTTPException(status_code=500, detail="Failed to generate query embedding")

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, url, title, summary, content, source_name, image_url,
                       published_at, category, author,
                       1 - (embedding <=> %s::vector) as similarity
                FROM public.articles
                WHERE embedding IS NOT NULL
                  AND published_at > now() - interval '7 days'
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (str(embedding), str(embedding), limit),
            )
            rows = cur.fetchall()

        articles = []
        for row in rows:
            articles.append({
                "id": str(row["id"]),
                "url": row["url"],
                "title": row["title"],
                "summary": row.get("summary"),
                "content": row.get("content"),
                "source": row.get("source_name"),
                "image_url": row.get("image_url"),
                "published_at": row["published_at"].isoformat() if row.get("published_at") else None,
                "category": row.get("category"),
                "author": row.get("author"),
                "similarity": round(row["similarity"], 4) if row.get("similarity") else None,
            })

        return {"articles": articles}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Search failed — please try again.")


@app.get("/categories")
async def get_categories(
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Return article categories with counts from the last 24 hours."""
    _require_auth(Authorization)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT category, COUNT(*) as count
            FROM public.articles
            WHERE published_at > now() - interval '24 hours'
              AND category IS NOT NULL AND category != 'general'
            GROUP BY category
            ORDER BY count DESC
        """)
        rows = cur.fetchall()

    return {"categories": [{"name": row["category"], "count": row["count"]} for row in rows]}


# ---------------------------------------------------------------------------
# Reading events (behavioral learning)
# ---------------------------------------------------------------------------

@app.post("/reading-events")
async def submit_reading_events(
    payload: dict,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Batch submit reading events from iOS client."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    allowed_event_types = {
        "impression",
        "tap",
        "read",
        "skip",
        "not_relevant",
        "more_like_this",
        "less_like_this",
        "important",
        "already_knew",
    }

    events = payload.get("events", [])
    if not events or len(events) > 100:
        raise HTTPException(400, "Events must be 1-100 items")

    inserted = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for event in events:
                event_type = event.get("type")
                if event_type not in allowed_event_types:
                    continue
                article_id = event.get("article_id")
                if not article_id:
                    continue
                duration = event.get("duration_seconds")
                feed_request_id = event.get("feed_request_id")
                position = event.get("position")
                try:
                    cur.execute(
                        """
                        INSERT INTO public.reading_events
                        (user_id, article_id, event_type, duration_seconds, feed_request_id, position_in_feed)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (user_id, article_id, event_type, duration,
                         feed_request_id, position),
                    )
                    inserted += cur.rowcount
                except Exception as e:
                    logger.warning("Failed to insert reading event: %s", e)

    # Recompute behavioral signals cache after new events
    if inserted > 0:
        _recompute_behavior_signals(conn, user_id)

    return {"inserted": inserted}


@app.post("/feed/feedback")
async def submit_feed_feedback(
    payload: dict,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    article_id = payload.get("article_id")
    action = str(payload.get("action") or "").strip()
    if not article_id or action not in {"not_relevant", "more_like_this", "less_like_this", "important", "already_knew", "hide_source"}:
        raise HTTPException(status_code=400, detail="article_id and a valid action are required")

    if action == "hide_source":
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.user_sources us
                SET active = false
                FROM public.article_source_links asl
                WHERE us.user_id = %s
                  AND asl.article_id = %s
                  AND us.source_url = asl.source_url
                """,
                (user_id, article_id),
            )
        _clear_user_feed_cache(conn, user_id)
        return {"status": "ok", "action": action}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.reading_events
            (user_id, article_id, event_type, feed_request_id, position_in_feed)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                user_id,
                article_id,
                action,
                payload.get("feed_request_id"),
                payload.get("position"),
            ),
        )

    if action in {"not_relevant", "less_like_this"}:
        _clear_user_feed_cache(conn, user_id)

    return {"status": "ok", "action": action}


def _recompute_behavior_signals(conn, user_id: str):
    """Recompute and cache behavioral signals from reading events."""
    import json as _json
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.category, a.source_name, re.event_type, COUNT(*) as count
                FROM public.reading_events re
                JOIN public.articles a ON a.id = re.article_id
                WHERE re.user_id = %s AND re.created_at > now() - interval '14 days'
                GROUP BY a.category, a.source_name, re.event_type
            """, (user_id,))
            rows = cur.fetchall()

        if not rows:
            return

        # Compute category affinity: tap_rate = taps / impressions per category
        cat_impressions: dict[str, int] = {}
        cat_taps: dict[str, int] = {}
        src_impressions: dict[str, int] = {}
        src_taps: dict[str, int] = {}

        for row in rows:
            cat = row.get("category") or "general"
            src = row.get("source_name") or ""
            count = row["count"]
            if row["event_type"] == "impression":
                cat_impressions[cat] = cat_impressions.get(cat, 0) + count
                src_impressions[src] = src_impressions.get(src, 0) + count
            elif row["event_type"] in ("tap", "read"):
                cat_taps[cat] = cat_taps.get(cat, 0) + count
                src_taps[src] = src_taps.get(src, 0) + count

        # Compute boost values (capped at 0.15)
        cat_boost = {}
        for cat, imps in cat_impressions.items():
            if imps >= 5:  # Need at least 5 impressions for signal
                rate = cat_taps.get(cat, 0) / imps
                cat_boost[cat] = min(round(rate * 0.3, 3), 0.15)

        src_boost = {}
        for src, imps in src_impressions.items():
            if imps >= 3 and src:
                rate = src_taps.get(src, 0) / imps
                src_boost[src] = min(round(rate * 0.2, 3), 0.1)

        signals = {"category_boost": cat_boost, "source_boost": src_boost}
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.user_preferences SET behavior_cache = %s WHERE user_id = %s",
                (_json.dumps(signals), user_id),
            )
    except Exception as e:
        logger.warning("Failed to recompute behavior signals for %s: %s", user_id, e)


# ---------------------------------------------------------------------------
# Entity pins (track people/companies/topics)
# ---------------------------------------------------------------------------

@app.get("/entities")
async def list_entity_pins(
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """List user's pinned entities."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, entity_name, entity_type, created_at FROM public.entity_pins WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,),
        )
        pins = cur.fetchall()
    return {"entities": [{"id": str(p["id"]), "name": p["entity_name"], "type": p["entity_type"], "created_at": _format_datetime_iso(p["created_at"])} for p in pins]}


@app.post("/entities")
async def create_entity_pin(
    payload: dict,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Pin a new entity for tracking."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    name = (payload.get("name") or "").strip()
    entity_type = payload.get("type", "topic")
    if not name or len(name) < 3:
        raise HTTPException(400, "Entity name must be at least 3 characters")
    if entity_type not in ("person", "company", "topic"):
        raise HTTPException(400, "Entity type must be person, company, or topic")

    # Check max pins
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM public.entity_pins WHERE user_id = %s", (user_id,))
        if cur.fetchone()["cnt"] >= 20:
            raise HTTPException(400, "Maximum 20 pinned entities")

        try:
            cur.execute(
                """
                INSERT INTO public.entity_pins (user_id, entity_name, entity_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, entity_name) DO NOTHING
                RETURNING id, entity_name, entity_type, created_at
                """,
                (user_id, name, entity_type),
            )
            row = cur.fetchone()
        except Exception as e:
            raise HTTPException(500, f"Error creating entity pin: {e}")

    if not row:
        raise HTTPException(409, "Entity already pinned")
    return {"id": str(row["id"]), "name": row["entity_name"], "type": row["entity_type"], "created_at": _format_datetime_iso(row["created_at"])}


@app.delete("/entities/{entity_id}")
async def delete_entity_pin(
    entity_id: str,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Unpin an entity."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM public.entity_pins WHERE id = %s AND user_id = %s",
            (entity_id, user_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Entity pin not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Briefing (AI morning briefing)
# ---------------------------------------------------------------------------

@app.get("/briefing")
async def get_briefing(
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Return the user's morning briefing. Cached for 4 hours."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    # Check cache
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content, generated_at FROM public.briefing_cache WHERE user_id = %s",
            (user_id,),
        )
        cached = cur.fetchone()

    if cached and cached.get("generated_at"):
        age = datetime.now(timezone.utc) - cached["generated_at"]
        if age.total_seconds() < 4 * 3600:
            return {"content": cached["content"], "generated_at": _format_datetime_iso(cached["generated_at"])}

    # Generate new briefing from top relevant articles
    from app.services.feed_service import get_personalized_feed
    articles = await get_personalized_feed(user_id, conn, limit=5)
    if len(articles) < 3:
        return {"content": None}

    # Load user profile for personalized briefing
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ai_profile FROM public.user_preferences WHERE user_id = %s AND completed = true",
            (user_id,),
        )
        pref_row = cur.fetchone()
    ai_profile = pref_row.get("ai_profile", "") if pref_row else ""

    try:
        from app.services.openai_service import get_openai_service
        openai_svc = get_openai_service()
        briefing = await openai_svc.generate_briefing(articles, ai_profile)
        if not briefing:
            return {"content": None}

        # Cache the briefing
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.briefing_cache (user_id, content, source_article_ids, generated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    source_article_ids = EXCLUDED.source_article_ids,
                    generated_at = now()
                """,
                (user_id, briefing, [a.get("id") for a in articles[:5]]),
            )

        return {"content": briefing, "generated_at": _format_datetime_iso(datetime.now(timezone.utc))}
    except Exception as e:
        logger.warning("Briefing generation failed for %s: %s", user_id, e)
        return {"content": None}


# ---------------------------------------------------------------------------
# Interest evolution suggestions
# ---------------------------------------------------------------------------

@app.get("/interests/suggestions")
async def list_interest_suggestions(
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """List pending interest suggestions for a user."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, topic, confidence, created_at FROM public.interest_suggestions WHERE user_id = %s AND status = 'pending' ORDER BY confidence DESC",
            (user_id,),
        )
        rows = cur.fetchall()
    return {"suggestions": [{"id": str(r["id"]), "topic": r["topic"], "confidence": r["confidence"], "created_at": _format_datetime_iso(r["created_at"])} for r in rows]}


@app.post("/interests/suggestions/{suggestion_id}/accept")
async def accept_interest_suggestion(
    suggestion_id: str,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Accept an interest suggestion — adds it to user's interests."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE public.interest_suggestions SET status = 'accepted' WHERE id = %s AND user_id = %s RETURNING topic",
            (suggestion_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Suggestion not found")

        # Add topic to user's interests
        cur.execute("SELECT interests FROM public.user_preferences WHERE user_id = %s", (user_id,))
        pref_row = cur.fetchone()
        if pref_row and pref_row.get("interests"):
            import json as _json
            try:
                interests = _json.loads(pref_row["interests"]) if isinstance(pref_row["interests"], str) else pref_row["interests"]
            except (ValueError, TypeError):
                interests = {}
            topics = interests.get("topics", [])
            if row["topic"] not in topics:
                topics.append(row["topic"])
                interests["topics"] = topics
                cur.execute(
                    "UPDATE public.user_preferences SET interests = %s, updated_at = now() WHERE user_id = %s",
                    (_json.dumps(interests), user_id),
                )

    _clear_user_feed_cache(conn, user_id)
    _clear_user_source_graph(conn, user_id)
    return {"accepted": True, "topic": row["topic"]}


@app.post("/interests/suggestions/{suggestion_id}/dismiss")
async def dismiss_interest_suggestion(
    suggestion_id: str,
    Authorization: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Dismiss an interest suggestion."""
    token = _require_auth(Authorization)
    user_id = _get_user_id_from_token(conn, token)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE public.interest_suggestions SET status = 'dismissed' WHERE id = %s AND user_id = %s",
            (suggestion_id, user_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Suggestion not found")
    return {"dismissed": True}


# ---------------------------------------------------------------------------
# Legacy endpoints removed — the old /news/* endpoints are replaced by /feed
# ---------------------------------------------------------------------------
