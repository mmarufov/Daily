"""Conservative specific-development grouping, independently revisioned.

The initial verifier requires supported resolved actors, a dated action/object,
and compatible locations in addition to vector similarity. Unknown evidence
stays singleton. This is a provisional recipe, never proof of semantic recall.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import date

from app.services import understanding_repository as repo


def event_key(card):
    hints = card.get('event_hints') or []
    if len(hints) != 1 or card.get('kind') in {'roundup','listicle','opinion','satire','promo','unknown'}:
        return None
    hint = hints[0]
    try:
        day = date.fromisoformat(hint['date']).isoformat()
    except (ValueError,TypeError,KeyError):
        return None
    entities = {}
    for entity in card.get('entities', []):
        mention = entity.get('mention')
        resolved = entity.get('resolved_id') if entity.get('resolution') == 'resolved' else None
        if mention in entities and entities[mention] != resolved:
            return None
        entities[mention] = resolved
    actors = hint.get('actors') or []
    action, target = hint.get('action'), hint.get('object')
    if not actors or any(not entities.get(a) for a in actors) or \
            not isinstance(action, str) or not action.strip() or \
            not isinstance(target, str) or not target.strip():
        return None
    return (tuple(sorted({entities[a] for a in actors})),action.casefold().strip(),
            target.casefold().strip(),day,tuple(sorted(set(hint.get('place_ids') or []))))


def cosine(left, right):
    try:
        if isinstance(left,str): left=json.loads(left)
        if isinstance(right,str): right=json.loads(right)
    except (ValueError, TypeError):
        return -1.0
    if not isinstance(left,(list,tuple)) or not isinstance(right,(list,tuple)):
        return -1.0
    if len(left)!=len(right): return -1.0
    if not all(type(x) in (int,float) and math.isfinite(x) for x in [*left,*right]): return -1.0
    left_norm,right_norm=math.hypot(*left),math.hypot(*right)
    if not left_norm or not right_norm or not math.isfinite(left_norm+right_norm): return -1.0
    return max(-1.0,min(1.0,sum((a/left_norm)*(b/right_norm) for a,b in zip(left,right))))


def compatible(card, vector, other_card, other_vector, *, threshold):
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        return False
    key=event_key(card)
    return key is not None and key==event_key(other_card) and cosine(vector,other_vector)>=threshold


@repo.lease_fenced
def assign_story(conn, job, bundle):
    # Serialize only cluster assignment transactions, not model work/ingestion.
    # Discover candidates before locks, then lock all affected articles in UUID
    # order. Revalidate everything afterwards; no job -> article lock inversion.
    candidates=conn.execute("""SELECT other.article_id FROM public.article_understanding_current target
      JOIN public.article_understanding_current other ON other.recipe_id=target.recipe_id
      JOIN public.articles a ON a.id=other.article_id
      WHERE target.article_id=%s AND target.recipe_id=%s AND target.stage='embedding'
        AND other.stage='embedding' AND COALESCE(a.published_at,a.ingested_at)>now()-interval '7 days'
      ORDER BY other.embedding <=> target.embedding,other.article_id LIMIT 80""",
      (job['article_id'],job['recipe_id'])).fetchall()
    ids=sorted({job['article_id'],*(r['article_id'] for r in candidates)},key=str)
    with conn.transaction():
        conn.execute('SELECT id FROM public.articles WHERE id=ANY(%s) ORDER BY id FOR UPDATE', (ids,)).fetchall()
        current_bundle=repo.evidence_for_article(conn,job['article_id'])
        current_job=repo._locked_job(conn,job)
        if not current_job:
            return False
        if not current_bundle or current_bundle['input_hash']!=bundle['input_hash']:
            repo._finish_job(conn,job,'superseded','input_changed')
            return False
        conn.execute('SELECT pg_advisory_xact_lock(731203002)')
        current=repo.load_current(conn,job['article_id'],job['recipe_id'])
        if current['state']!='ready':
            repo._finish_job(conn,job,'failed_terminal','missing_compatible_results')
            return False
        card=current['facets']['payload']
        vector=current['embedding']['embedding']
        matching=set()
        # No universal similarity threshold: uncalibrated recipes only produce
        # explicit singleton assignments until evaluation supplies this value.
        threshold=job['definition'].get('cluster_cosine_threshold')
        for article_id in ids:
            if article_id==job['article_id']: continue
            other=repo.load_current(conn,article_id,job['recipe_id'])
            membership=other.get('membership')
            if other['state']=='ready' and membership and compatible(card,vector,
                    other['facets']['payload'],other['embedding']['embedding'],threshold=threshold):
                matching.add(membership['cluster_id'])
        cluster_id=None
        if len(matching)==1:
            candidate=next(iter(matching))
            members=conn.execute('SELECT article_id FROM public.story_memberships WHERE cluster_id=%s',
                                 (candidate,)).fetchall()
            # A bounded candidate window cannot certify unseen members. Require
            # every current member, not transitive similarity through one bridge.
            if all(m['article_id'] in ids for m in members):
                all_compatible=True
                for member in members:
                    if member['article_id']==job['article_id']: continue
                    other=repo.load_current(conn,member['article_id'],job['recipe_id'])
                    if other['state']!='ready' or not compatible(card,vector,other['facets']['payload'],
                          other['embedding']['embedding'],threshold=threshold):
                        all_compatible=False
                        break
                if all_compatible: cluster_id=candidate
        reason='verified_same_development' if cluster_id else 'singleton_insufficient_or_ambiguous'
        if cluster_id is None:
            cluster_id=uuid.uuid5(uuid.NAMESPACE_URL,f"daily:s3:{job['recipe_id']}:{job['article_id']}:{bundle['input_hash']}")
        _set_membership(conn,job,bundle,cluster_id,reason)
        repo.finish_publication(conn,job)
        return True


def _set_membership(conn,job,bundle,cluster_id,reason):
    conn.execute('INSERT INTO public.story_clusters(id,recipe_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',
                 (cluster_id,job['recipe_id']))
    old=conn.execute('SELECT * FROM public.story_memberships WHERE article_id=%s AND recipe_id=%s',
                     (job['article_id'],job['recipe_id'])).fetchone()
    if old and old['cluster_id']==cluster_id and old['input_hash']==bundle['input_hash']:
        return
    version=(old['version'] if old else 0)+1
    conn.execute("""INSERT INTO public.story_memberships(article_id,recipe_id,cluster_id,semantic_revision,
      eligibility_generation,input_hash,version,reason) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT(article_id,recipe_id) DO UPDATE SET cluster_id=EXCLUDED.cluster_id,
      semantic_revision=EXCLUDED.semantic_revision,eligibility_generation=EXCLUDED.eligibility_generation,
      input_hash=EXCLUDED.input_hash,version=EXCLUDED.version,reason=EXCLUDED.reason,updated_at=now()""",
      (job['article_id'],job['recipe_id'],cluster_id,job['semantic_revision'],job['eligibility_generation'],
       bundle['input_hash'],version,reason))
    conn.execute("""INSERT INTO public.story_membership_events(article_id,recipe_id,previous_cluster,
      cluster_id,version,reason) VALUES(%s,%s,%s,%s,%s,%s)""",
      (job['article_id'],job['recipe_id'],old['cluster_id'] if old else None,cluster_id,version,reason))
    conn.execute('UPDATE public.story_clusters SET version=version+1 WHERE id=ANY(%s)',
                 ([cluster_id]+([old['cluster_id']] if old else []),))
    conn.execute("""INSERT INTO public.understanding_outbox(article_id,semantic_revision,
      eligibility_generation,recipe_id,kind) VALUES(%s,%s,%s,%s,'membership_changed')""",
      (job['article_id'],job['semantic_revision'],job['eligibility_generation'],job['recipe_id']))


def split_to_singleton(conn,article_id,recipe_id,*,expected_version,reason):
    if not reason.strip(): raise ValueError('correction reason required')
    with conn.transaction():
        bundle=repo.evidence_for_article(conn,article_id,lock=True)
        if not bundle: return False
        conn.execute('SELECT pg_advisory_xact_lock(731203002)')
        membership=conn.execute('SELECT version FROM public.story_memberships WHERE article_id=%s AND recipe_id=%s',
                                (article_id,recipe_id)).fetchone()
        if not membership or membership['version']!=expected_version: return False
        job={'article_id':article_id,'recipe_id':recipe_id,'semantic_revision':bundle['semantic_revision'],
             'eligibility_generation':bundle['analysis_eligibility_generation']}
        _set_membership(conn,job,bundle,uuid.uuid4(),'reviewed_split:'+reason[:100])
        return True
