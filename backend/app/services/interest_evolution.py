"""
Interest evolution service: analyzes reading patterns to suggest new topics.
Triggered when a user has 20+ reading events. Runs every 6 hours.
"""
import json
import logging

logger = logging.getLogger(__name__)

MIN_EVENTS_THRESHOLD = 20
CATEGORY_APPEARANCE_THRESHOLD = 5
MAX_DISMISS_COUNT = 5


async def check_interest_evolution(conn) -> int:
    """
    Check all eligible users for interest evolution suggestions.
    Eligible: 20+ reading events, no check in last 24 hours.
    Returns number of suggestions created.
    """
    try:
        with conn.cursor() as cur:
            # Find users with enough reading events and no recent suggestions
            cur.execute("""
                SELECT re.user_id, COUNT(*) as event_count
                FROM public.reading_events re
                WHERE re.event_type IN ('tap', 'read')
                  AND re.created_at > now() - interval '14 days'
                GROUP BY re.user_id
                HAVING COUNT(*) >= %s
            """, (MIN_EVENTS_THRESHOLD,))
            eligible_users = cur.fetchall()

        suggestions_created = 0
        for user_row in eligible_users:
            user_id = user_row["user_id"]

            # Skip if user has dismissed 5+ suggestions in a row
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as dismiss_count
                    FROM (
                        SELECT status FROM public.interest_suggestions
                        WHERE user_id = %s
                        ORDER BY created_at DESC LIMIT %s
                    ) recent
                    WHERE recent.status = 'dismissed'
                """, (user_id, MAX_DISMISS_COUNT))
                dismiss_row = cur.fetchone()
                if dismiss_row and dismiss_row["dismiss_count"] >= MAX_DISMISS_COUNT:
                    continue

            count = await _check_user_evolution(conn, user_id)
            suggestions_created += count

        if suggestions_created:
            logger.info("Interest evolution: created %d suggestions for %d users",
                        suggestions_created, len(eligible_users))
        return suggestions_created

    except Exception as e:
        logger.warning("Interest evolution check failed: %s", e)
        return 0


async def _check_user_evolution(conn, user_id: str) -> int:
    """Check a single user for potential new interests based on reading patterns."""
    try:
        # Get reading patterns by category
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.category, COUNT(*) as engagement_count
                FROM public.reading_events re
                JOIN public.articles a ON a.id = re.article_id
                WHERE re.user_id = %s
                  AND re.event_type IN ('tap', 'read')
                  AND re.created_at > now() - interval '14 days'
                  AND a.category IS NOT NULL
                GROUP BY a.category
                HAVING COUNT(*) >= %s
                ORDER BY engagement_count DESC
            """, (user_id, CATEGORY_APPEARANCE_THRESHOLD))
            engaged_categories = cur.fetchall()

        if not engaged_categories:
            return 0

        # Get current interests
        with conn.cursor() as cur:
            cur.execute(
                "SELECT interests FROM public.user_preferences WHERE user_id = %s AND completed = true",
                (user_id,),
            )
            pref_row = cur.fetchone()

        current_topics = set()
        if pref_row and pref_row.get("interests"):
            try:
                interests = json.loads(pref_row["interests"]) if isinstance(pref_row["interests"], str) else pref_row["interests"]
                for term in interests.get("topics", []):
                    current_topics.add(str(term).lower().strip())
            except (ValueError, TypeError):
                pass

        # Find categories the user engages with but hasn't explicitly listed
        suggestions_created = 0
        for cat_row in engaged_categories:
            category = cat_row["category"]
            if category.lower() in current_topics or category == "general":
                continue

            # Check if we already suggested this
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM public.interest_suggestions WHERE user_id = %s AND topic = %s",
                    (user_id, category),
                )
                if cur.fetchone():
                    continue

            # Calculate confidence based on engagement count
            confidence = min(cat_row["engagement_count"] / 20.0, 1.0)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.interest_suggestions (user_id, topic, confidence)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, topic) DO NOTHING
                    """,
                    (user_id, category, confidence),
                )
                if cur.rowcount == 1:
                    suggestions_created += 1

        return suggestions_created

    except Exception as e:
        logger.warning("Interest evolution check for user %s failed: %s", user_id, e)
        return 0
