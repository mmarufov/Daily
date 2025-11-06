import os
import hashlib
import base64
import time
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
    """Chat with AI - requires authentication"""
    token = _require_auth(Authorization)
    
    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    
    try:
        from app.services.openai_service import get_openai_service
        
        openai_service = get_openai_service()
        
        # Simple chat - just send the user message
        system_prompt = "You are a helpful AI assistant. Be concise and friendly."
        
        # Use OpenAI service to get response
        import asyncio
        response = await asyncio.to_thread(
            openai_service.client.chat.completions.create,
            model=openai_service.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.7,
        )
        
        ai_response = response.choices[0].message.content
        
        return {
            "response": ai_response,
            "model": openai_service.model
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error chatting with AI: {str(e)}")


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


