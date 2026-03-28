"""
Global source quality scoring based on aggregate reading events.
Runs periodically (every 30 min) to update source_quality table.
"""
import logging

logger = logging.getLogger(__name__)


async def update_source_quality(conn) -> int:
    """
    Recalculate global source quality scores from reading events.

    quality_score = weighted combination of:
    - tap_rate = taps / impressions (weight: 0.5)
    - read_rate = reads / taps (weight: 0.3)
    - avg_duration_score = min(avg_duration / 120, 1.0) (weight: 0.2)

    Returns number of sources updated.
    """
    try:
        with conn.cursor() as cur:
            # Get the latest update timestamp for incremental processing
            cur.execute("SELECT MAX(updated_at) as last_update FROM public.source_quality")
            row = cur.fetchone()
            last_update = row["last_update"] if row else None

            # Aggregate reading events per source domain
            time_filter = ""
            params = ()
            if last_update:
                # Only process events since last update (ENG-11: incremental)
                time_filter = "AND re.created_at > %s"
                params = (last_update,)

            cur.execute(f"""
                SELECT
                    LOWER(TRIM(a.source_name)) as source_domain,
                    SUM(CASE WHEN re.event_type = 'impression' THEN 1 ELSE 0 END) as impressions,
                    SUM(CASE WHEN re.event_type = 'tap' THEN 1 ELSE 0 END) as taps,
                    SUM(CASE WHEN re.event_type = 'read' THEN 1 ELSE 0 END) as reads,
                    AVG(CASE WHEN re.event_type = 'read' THEN re.duration_seconds END) as avg_duration
                FROM public.reading_events re
                JOIN public.articles a ON a.id = re.article_id
                WHERE a.source_name IS NOT NULL {time_filter}
                GROUP BY LOWER(TRIM(a.source_name))
                HAVING SUM(CASE WHEN re.event_type = 'impression' THEN 1 ELSE 0 END) >= 5
            """, params)
            rows = cur.fetchall()

        if not rows:
            return 0

        updated = 0
        with conn.cursor() as cur:
            for row in rows:
                domain = row["source_domain"]
                impressions = row["impressions"] or 0
                taps = row["taps"] or 0
                reads = row["reads"] or 0
                avg_duration = row["avg_duration"] or 0

                # Compute quality score
                tap_rate = taps / max(impressions, 1)
                read_rate = reads / max(taps, 1)
                duration_score = min(avg_duration / 120.0, 1.0) if avg_duration else 0

                quality_score = 0.5 * tap_rate + 0.3 * read_rate + 0.2 * duration_score
                quality_score = max(0.0, min(1.0, quality_score))

                cur.execute(
                    """
                    INSERT INTO public.source_quality
                        (source_domain, impressions, taps, reads, avg_read_duration, quality_score, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (source_domain) DO UPDATE SET
                        impressions = source_quality.impressions + EXCLUDED.impressions,
                        taps = source_quality.taps + EXCLUDED.taps,
                        reads = source_quality.reads + EXCLUDED.reads,
                        avg_read_duration = EXCLUDED.avg_read_duration,
                        quality_score = EXCLUDED.quality_score,
                        updated_at = now()
                    """,
                    (domain, impressions, taps, reads, avg_duration, quality_score),
                )
                updated += 1

        if updated:
            logger.info("Source quality: updated %d sources", updated)
        return updated

    except Exception as e:
        logger.warning("Source quality update failed: %s", e)
        return 0
