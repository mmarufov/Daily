"""Opt-in S3 lookup for current search/chat consumers; feed migration is S6.

All outputs must still cross the existing S2 public serializer. The private chat
loader uses only the exact evidence bundle that produced the current result.
"""
import os

from app.services.understanding_contract import DEFAULT_RECIPE, validate_embedding
from app.services.understanding_repository import evidence_for_article, load_current


def enabled():
    return os.getenv('S3_CONSUMERS_ENABLED','false').lower() == 'true'


def serving_recipe(conn):
    row=conn.execute("""SELECT r.* FROM public.understanding_control c
      JOIN public.understanding_recipes r ON r.id=c.serving_recipe
      WHERE r.enabled AND r.approved""").fetchone()
    if not row:
        raise RuntimeError('S3 consumer flag requires an approved serving recipe')
    if any(row['definition'].get(k)!=DEFAULT_RECIPE[k] for k in
           ('embedding_model','dimensions','query_recipe','schema_hash','input_version')):
        raise RuntimeError('serving recipe is incompatible with this API build')
    return row


async def query_vector(conn,query):
    from app.services.understanding_provider import OpenAIUnderstandingProvider
    recipe=serving_recipe(conn)
    provider=OpenAIUnderstandingProvider(os.environ['OPENAI_API_KEY'])
    try:
        outcome=await provider.query_embedding(query,recipe['definition'])
        return outcome.payload['vector']
    finally:
        await provider.aclose()


def semantic_rows(conn,vector,*,limit=8,lookback_hours=168,private=False):
    recipe=serving_recipe(conn)
    vector=validate_embedding(vector)
    limit=max(1,min(int(limit),100))
    hours=max(1,min(int(lookback_hours),24*14))
    # Oversample because application evidence hashes can invalidate a result
    # after an S2 artifact changes in place; never refill using obsolete vectors.
    rows=conn.execute("""SELECT a.*,
      artifact.kind AS artifact_kind,artifact.method AS artifact_method,
      artifact.origin_url AS artifact_origin_url,artifact.fetched_at AS artifact_fetched_at,
      artifact.extractor_version AS artifact_extractor_version,artifact.completeness AS artifact_completeness,
      artifact.confidence AS artifact_confidence,artifact.content_hash AS artifact_content_hash,
      u.input_hash AS understanding_input_hash,u.semantic_revision AS understanding_revision,
      u.analysis_eligibility_generation AS understanding_eligibility_generation,
      1-(u.embedding <=> %s::vector) AS similarity
      FROM public.article_understanding_current u JOIN public.articles a ON a.id=u.article_id
      LEFT JOIN public.article_content_artifacts artifact ON artifact.id=a.display_content_artifact_id
        AND artifact.article_id=a.id
      WHERE u.recipe_id=%s AND u.stage='embedding'
        AND COALESCE(a.published_at,a.ingested_at)>now()-(%s*interval '1 hour')
      ORDER BY u.embedding <=> %s::vector,a.id LIMIT %s""",
      (str(vector),recipe['id'],hours,str(vector),limit*5)).fetchall()
    accepted=[]
    for row in rows:
        current=load_current(conn,row['id'],recipe['id'])
        if (not current.get('embedding') or current.get('input_hash')!=row['understanding_input_hash']
            or current.get('semantic_revision')!=row['understanding_revision']
            or current.get('analysis_eligibility_generation')!=row['understanding_eligibility_generation']):
            continue
        if private:
            evidence=evidence_for_article(conn,row['id'])
            if not evidence or evidence['input_hash']!=current['input_hash']:
                continue
            row['content']=evidence['fields']['body']
            row['summary']=evidence['fields']['summary']
        accepted.append(row)
        if len(accepted)>=limit: break
    # Promotion/disable can change mid-query; reject the old cohort atomically
    # from the caller's perspective instead of falling back to unversioned vectors.
    if serving_recipe(conn)['id']!=recipe['id']:
        return []
    return accepted
