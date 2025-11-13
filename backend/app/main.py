import os
import hashlib
import base64
import time
import asyncio
from datetime import datetime, timezone

import jwt
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
import psycopg
from psycopg.rows import dict_row

load_dotenv()

NEON_DATABASE_URL = os.getenv("NEON_DATABASE_URL", "")

app = FastAPI(title="Daily Auth API", version="0.1.0")


def get_db():
    with psycopg.connect(NEON_DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        yield conn


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
    Kept as a simple, non-onboarding chat.
    """
    token = _require_auth(Authorization)

    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    try:
        from app.services.openai_service import get_openai_service

        openai_service = get_openai_service()

        system_prompt = "You are a helpful AI assistant. Be concise and friendly."

        import asyncio

        response = await asyncio.to_thread(
            openai_service.client.chat.completions.create,
            model=openai_service.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
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


@app.get("/news/headlines")
async def get_headlines(Authorization: str | None = Header(default=None), limit: int = 5):
    """Get top headlines - requires authentication"""
    token = _require_auth(Authorization)
    
    try:
        from app.services.newsapi_service import get_newsapi_service
        import uuid
        from datetime import datetime
        
        newsapi_service = get_newsapi_service()
        
        # Fetch top headlines
        result = await newsapi_service.get_top_headlines(
            country="us",
            page_size=min(limit, 100)  # Cap at 100
        )
        
        # Format articles to match NewsArticle structure
        articles = []
        for article in result.get("articles", [])[:limit]:
            if not article.get("title"):  # Skip articles without titles
                continue
                
            formatted = newsapi_service.format_article(article)
            
            # Parse published date - NewsAPI uses ISO 8601 format
            published_at_str = None
            if formatted.get("published_at"):
                try:
                    # NewsAPI format: "2024-01-01T12:00:00Z" or "2024-01-01T12:00:00+00:00"
                    date_str = str(formatted["published_at"])
                    if date_str.endswith("Z"):
                        date_str = date_str.replace("Z", "+00:00")
                    published_at = datetime.fromisoformat(date_str)
                    published_at_str = published_at.isoformat()
                except Exception as e:
                    print(f"Error parsing date: {e}, date string: {formatted.get('published_at')}")
                    published_at_str = None
            
            # Create article dict matching NewsArticle model
            article_dict = {
                "id": str(uuid.uuid4()),  # Generate unique ID
                "title": formatted.get("title", "") or "Untitled",
                "summary": formatted.get("description"),
                "content": formatted.get("content"),
                "author": formatted.get("author"),
                "source": formatted.get("source") or "Unknown",
                "image_url": formatted.get("image_url"),
                "url": formatted.get("url"),
                "published_at": published_at_str,
                "category": formatted.get("category"),
            }
            articles.append(article_dict)
        
        return articles
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching headlines: {str(e)}")


@app.post("/news/curate")
async def curate_news(
    Authorization: str | None = Header(default=None),
    limit: int = 10,
    topic: str | None = None,
    conn=Depends(get_db),
):
    """
    Fetch news from NewsAPI, analyze with AI, and return top selected articles.

    If the user has completed onboarding and has a saved ai_profile, that will be used
    as the primary filtering logic. Otherwise, an optional fallback `topic` can be used.
    """
    token = _require_auth(Authorization)

    try:
        from app.services.newsapi_service import get_newsapi_service
        from app.services.openai_service import get_openai_service
        import uuid
        from datetime import datetime

        # 1) Load user preferences (if any)
        user_id = _get_user_id_from_token(conn, token)
        ai_profile = None
        interests = None
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT interests, ai_profile, completed
                FROM public.user_preferences
                WHERE user_id = %s
                """,
                (user_id,),
            )
            pref = cur.fetchone()
            if pref and pref.get("completed"):
                ai_profile = pref.get("ai_profile")
                interests = pref.get("interests")

        # 2) Build curation prompt
        if ai_profile:
            # Fully personalized prompt using saved profile
            CURATION_PROMPT = f"""
You are a strict personalized news filter for a single user.

User profile (from onboarding chat):
{ai_profile}

Instructions:
- ONLY select articles that match this user's interests and preferences.
- Respect any topics or categories the user said they do NOT want.
- Prefer highly relevant, recent, high-quality sources.

Return JSON with:
- selected: true or false
- relevance_score: 0.0-1.0 (0.0 if not relevant)
- reasoning: brief explanation
"""
            print("DEBUG: Using personalized curation prompt from user_preferences")
        else:
            # Fallback: topic-based prompt as before (kept simple)
            topic = topic or "general"
            CURATION_PROMPT = f"""
You are a strict news filter for topic: {topic}.

Select only articles that are strongly about this topic.
Be conservative. If it is not clearly about this topic, set selected=false and relevance_score=0.0.

Return JSON with:
- selected: true or false
- relevance_score: 0.0-1.0 (0.0 if not relevant)
- reasoning: brief explanation
"""
            print(f"DEBUG: Using fallback topic-based curation prompt for topic={topic}")

        newsapi_service = get_newsapi_service()
        openai_service = get_openai_service()

        # 3) Build NewsAPI query
        if ai_profile and isinstance(interests, dict):
            # Very simple keyword strategy: join main interest keywords if present
            keywords = interests.get("keywords") or interests.get("topics") or []
            if isinstance(keywords, list) and keywords:
                # Use first keyword as primary query; NewsAPI free tier works best with one term
                query_variations = [str(keywords[0])]
            else:
                query_variations = ["news"]
        else:
            # Generic fallback queries
            if topic and topic not in ("general", ""):
                query_variations = [topic]
            else:
                query_variations = ["news"]

        print(f"DEBUG: Will try query variations for NewsAPI: {query_variations}")
        
        # Try queries in order until we get results
        articles = []
        total_results = 0
        search_query = query_variations[0]  # Default to first variation

        for query_variant in query_variations:
            print(f"DEBUG: Trying NewsAPI search with query: {query_variant}")
            try:
                result = await newsapi_service.search_everything(
                    query=query_variant,
                    language="en",
                    sort_by="publishedAt",
                    page_size=100,
                )
                
                articles = result.get("articles", [])
                total_results = result.get("totalResults", 0)
                search_query = query_variant
                
                print(f"DEBUG: NewsAPI search returned {len(articles)} articles (total available: {total_results}) for query: {query_variant}")
                
                if articles:
                    print(f"DEBUG: First article title: {articles[0].get('title', 'N/A')[:100]}")
                    print(f"DEBUG: First article description: {articles[0].get('description', 'N/A')[:200] if articles[0].get('description') else 'N/A'}")
                    break  # Found results, stop trying other variations
                else:
                    print(f"DEBUG: No articles found for query: {query_variant}, trying next variation...")
                    
            except Exception as e:
                print(f"Error fetching from NewsAPI with query '{query_variant}': {str(e)}")
                # Continue to next query variation
                continue
        
        if not articles:
            print(f"ERROR: No articles returned from NewsAPI for any query variation: {query_variations}")
            # Try a fallback: use top headlines for the country if it's a location-based topic
            if topic in ["new_york", "san_francisco"]:
                print(f"DEBUG: Attempting fallback to US top headlines...")
                try:
                    result = await newsapi_service.get_top_headlines(
                        country="us",
                        page_size=100
                    )
                    articles = result.get("articles", [])
                    total_results = result.get("totalResults", 0)
                    print(f"DEBUG: Fallback returned {len(articles)} US headlines")
                except Exception as e:
                    print(f"Fallback also failed: {str(e)}")
            
            if not articles:
                raise HTTPException(
                    status_code=404, 
                    detail=f"No articles found for '{topic}'. NewsAPI may not have recent articles for this topic, or you may have hit the rate limit (100 requests/day on free tier). Try again later or consider upgrading your NewsAPI plan."
                )
        
        print(f"Fetched {len(articles)} articles from NewsAPI, starting analysis...")
        
        # Filter articles with titles and basic content
        valid_articles = [a for a in articles if a.get("title") and (a.get("description") or a.get("content"))]
        print(f"DEBUG: {len(valid_articles)} articles have title and (description or content)")
        print(f"DEBUG: {len(articles) - len(valid_articles)} articles were filtered out")
        
        if not valid_articles:
            print("ERROR: No valid articles to process after filtering")
            # TEMPORARY: Return first 5 articles even without description/content to test
            print("TEMPORARY: Trying to return articles with just titles...")
            valid_articles = [a for a in articles if a.get("title")][:5]
            if not valid_articles:
                return []
            print(f"TEMPORARY: Found {len(valid_articles)} articles with titles")
        
        # Process articles in parallel batches (10 at a time to avoid rate limits)
        analyzed_articles = []
        errors_count = 0
        batch_size = 10
        
        async def analyze_single_article(article):
            """Helper function to analyze a single article"""
            try:
                formatted = newsapi_service.format_article(article)
                print(f"DEBUG: Analyzing article: {formatted.get('title', 'No title')[:50]}...")
                analysis = await openai_service.analyze_article(formatted, CURATION_PROMPT)
                
                relevance_score = float(analysis.get("relevance_score", 0.0))
                is_selected = analysis.get("selected", False)
                print(f"DEBUG: Article '{formatted.get('title', 'No title')[:50]}...' - score: {relevance_score}, selected: {is_selected}")
                
                # Parse published date
                published_at_str = None
                if formatted.get("published_at"):
                    try:
                        date_str = str(formatted["published_at"])
                        if date_str.endswith("Z"):
                            date_str = date_str.replace("Z", "+00:00")
                        published_at = datetime.fromisoformat(date_str)
                        published_at_str = published_at.isoformat()
                    except Exception as e:
                        pass  # Date parsing errors are non-critical
                
                return {
                    "success": True,
                    "article": {
                        "id": str(uuid.uuid4()),
                        "title": formatted.get("title", "") or "Untitled",
                        "summary": formatted.get("description"),
                        "content": formatted.get("content"),
                        "author": formatted.get("author"),
                        "source": formatted.get("source") or "Unknown",
                        "image_url": formatted.get("image_url"),
                        "url": formatted.get("url"),
                        "published_at": published_at_str,
                        "category": formatted.get("category"),
                        "_relevance_score": relevance_score,
                        "_is_selected": is_selected,
                    }
                }
            except Exception as e:
                print(f"Error in analyze_single_article: {str(e)}")
                import traceback
                traceback.print_exc()
                return {
                    "success": False,
                    "error": str(e),
                    "title": article.get("title", "Unknown")
                }
        
        # Process in batches
        print(f"DEBUG: Starting to process {len(valid_articles)} articles in batches of {batch_size}")
        for i in range(0, len(valid_articles), batch_size):
            batch = valid_articles[i:i + batch_size]
            batch_num = i//batch_size + 1
            total_batches = (len(valid_articles) + batch_size - 1)//batch_size
            print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} articles)...")
            
            try:
                # Analyze batch in parallel
                results = await asyncio.gather(*[analyze_single_article(article) for article in batch])
                print(f"DEBUG: Batch {batch_num} completed, got {len(results)} results")
            except Exception as e:
                print(f"ERROR in batch {batch_num}: {str(e)}")
                import traceback
                traceback.print_exc()
                # Continue with other batches
                continue
            
            # Collect successful analyses
            for result in results:
                if result.get("success"):
                    analyzed_articles.append(result["article"])
                else:
                    errors_count += 1
                    print(f"Error analyzing article '{result.get('title', 'Unknown')}': {result.get('error', 'Unknown error')}")
        
        print(f"Analysis complete: {len(analyzed_articles)} articles successfully analyzed, {errors_count} errors")
        
        if not analyzed_articles:
            print("ERROR: No articles were successfully analyzed")
            print("This could mean:")
            print("1. All articles failed AI analysis")
            print("2. NewsAPI returned no articles")
            print("3. Articles were filtered out before analysis")
            # REMOVED BYPASS - we only want articles that AI confirms mention Trump
            raise HTTPException(status_code=500, detail="Failed to analyze articles. Please check backend logs for details.")
        
        # Sort by relevance score (highest first) - this ensures we get articles closest to prompt
        analyzed_articles.sort(key=lambda x: x.get("_relevance_score", 0.0), reverse=True)
        
        # Log top scores for debugging
        top_scores = [a.get("_relevance_score", 0.0) for a in analyzed_articles[:min(10, len(analyzed_articles))]]
        print(f"Top {len(top_scores)} relevance scores: {top_scores}")
        
        # Clamp limit between 5 and 10
        actual_limit = max(5, min(10, limit))
        
        # Strategy: Always return articles closest to the prompt (by relevance score)
        # Articles are already sorted by relevance_score (highest first)
        # This ensures we get the articles that best match what the prompt wants
        # 
        # Rules:
        # - Minimum 5 articles (or all if we have fewer than 5 analyzed)
        # - Maximum is the requested limit (clamped between 5-10)
        # - Always prioritize by relevance score (closest to prompt)
        
        # Determine how many articles to return
        # - If we have 5+ analyzed articles: return at least 5, up to actual_limit
        # - If we have fewer than 5: return all of them
        min_articles_to_return = min(5, len(analyzed_articles))
        max_articles_to_return = min(actual_limit, len(analyzed_articles))
        
        # Strategy: ONLY return articles that AI explicitly selected as topic-related
        # Articles are sorted by relevance score (highest first)
        # We ONLY return articles that AI said contain topic mentions
        
        # ONLY get articles that were explicitly selected by AI
        selected_articles = [a for a in analyzed_articles if a.get("_is_selected", False)]
        print(f"Found {len(selected_articles)} articles explicitly selected by AI as containing {topic} mentions")
        
        # If AI rejected everything, log some examples to help debug
        if len(selected_articles) == 0 and len(analyzed_articles) > 0:
            print(f"WARNING: AI rejected all {len(analyzed_articles)} articles for topic {topic}")
            print(f"Sample rejected articles (top 3 by relevance score):")
            for i, article in enumerate(analyzed_articles[:3]):
                print(f"  {i+1}. Title: {article.get('title', 'N/A')[:80]}")
                print(f"     Relevance: {article.get('_relevance_score', 0.0):.2f}, Selected: {article.get('_is_selected', False)}")
        
        # Strategy: Use AI-selected articles, but if none selected, use top articles by relevance score
        # This handles cases where AI is too strict but NewsAPI returned relevant articles
        if len(selected_articles) >= 5:
            curated_articles = selected_articles[:min(actual_limit, len(selected_articles))]
            print(f"Using {len(curated_articles)} AI-selected {topic} articles")
        elif len(selected_articles) > 0:
            # If we have some but less than 5, return what we have
            curated_articles = selected_articles
            print(f"Using {len(curated_articles)} AI-selected {topic} articles (less than 5 found)")
        elif len(analyzed_articles) > 0:
            # FALLBACK: If AI rejected everything but we have analyzed articles, 
            # use top articles by relevance score (they're already sorted)
            # This helps when AI is too strict but NewsAPI search was good
            print(f"WARNING: AI rejected all articles, but using top {min(5, len(analyzed_articles))} by relevance score as fallback")
            curated_articles = analyzed_articles[:min(actual_limit, len(analyzed_articles))]
        else:
            # If no articles were analyzed at all
            curated_articles = []
            print(f"ERROR: No articles were successfully analyzed for topic {topic}")
        
        print(f"Selected {len(curated_articles)} articles (min {min_articles_to_return}, max {max_articles_to_return}, from {len(analyzed_articles)} analyzed)")
        if curated_articles:
            scores = [a.get('_relevance_score', 0.0) for a in curated_articles]
            print(f"Relevance scores of selected articles: {scores}")
            print(f"Average relevance score: {sum(scores)/len(scores) if scores else 0:.3f}")
        else:
            print("WARNING: No articles selected! This should not happen if articles were analyzed.")
        
        # Remove internal fields before returning (keep only fields that match NewsArticle model)
        final_articles = []
        for article in curated_articles:
            final_article = {
                "id": article.get("id"),
                "title": article.get("title", "") or "Untitled",
                "summary": article.get("summary"),
                "content": article.get("content"),
                "author": article.get("author"),
                "source": article.get("source") or "Unknown",
                "image_url": article.get("image_url"),
                "url": article.get("url"),
                "published_at": article.get("published_at"),
                "category": article.get("category"),
            }
            final_articles.append(final_article)
        
        if len(final_articles) == 0:
            print(f"INFO: No articles with {topic} mentions found. Returning empty list.")
            print(f"Debug info: analyzed_articles={len(analyzed_articles) if 'analyzed_articles' in locals() else 'N/A'}, curated_articles={len(curated_articles) if 'curated_articles' in locals() else 'N/A'}")
            # NO FALLBACK - only return articles that explicitly mention the topic

        print(f"Returning {len(final_articles)} curated articles (only articles that mention {topic})")
        return final_articles
        
    except ValueError as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error curating news: {str(e)}")


@app.get("/news/test")
async def test_news_api(Authorization: str | None = Header(default=None)):
    """Test NewsAPI integration - requires authentication"""
    token = _require_auth(Authorization)
    
    try:
        from app.services.newsapi_service import get_newsapi_service
        
        newsapi_service = get_newsapi_service()
        
        # Fetch top headlines as a test
        result = await newsapi_service.get_top_headlines(
            country="us",
            page_size=5
        )
        
        # Format articles
        articles = [newsapi_service.format_article(article) for article in result.get("articles", [])]
        
        return {
            "status": "ok",
            "total_results": result.get("totalResults", 0),
            "articles": articles
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching news: {str(e)}")


