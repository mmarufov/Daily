"""Bounded canonical-reader retrieval; private rows MUST cross S2/policy gates.

Independent intent legs use RRF, then a round-robin union so a popular interest
cannot consume every candidate slot. RRF is an ordering score, never a relevance
probability. Semantic retrieval only uses cached vectors and an explicitly set
abstention threshold; the feature and paid worker are independently default off.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from contextlib import contextmanager

from psycopg.types.json import Jsonb

from .reader_worker import active_intents, intent_query, semantic_hash, space_id
from .understanding_consumers import semantic_rows, serving_recipe
from .understanding_repository import load_current

# S5 compatibility functions below remain available while the S6 handoff is in
# shadow. The S6 builder returns a CandidateBatch, never final feed relevance.

_ARTICLE_SELECT = '''SELECT a.*,
  artifact.kind AS artifact_kind,artifact.method AS artifact_method,
  artifact.origin_url AS artifact_origin_url,artifact.fetched_at AS artifact_fetched_at,
  artifact.extractor_version AS artifact_extractor_version,artifact.completeness AS artifact_completeness,
  artifact.confidence AS artifact_confidence,artifact.content_hash AS artifact_content_hash
  FROM public.articles a LEFT JOIN public.article_content_artifacts artifact
    ON artifact.id=a.display_content_artifact_id AND artifact.article_id=a.id'''


def semantic_threshold():
    if os.getenv('S5_SEMANTIC_ENABLED', 'false').lower() != 'true':
        return None
    # No invented universal cosine cutoff: promotion must explicitly choose a
    # threshold from held-out data. Missing/malformed configuration abstains.
    try:
        value = float(os.environ['S5_SEMANTIC_MIN_SIMILARITY'])
    except (KeyError, ValueError):
        return None
    return value if math.isfinite(value) and 0 <= value <= 1 else None


def fuse_intent_legs(legs):
    """Merge ranks, preserving evidence kinds without raw intent text."""
    scored, articles, kinds = defaultdict(float), {}, defaultdict(set)
    for kind, rows in legs.items():
        seen = set()
        for rank, row in enumerate(rows, 1):
            identifier = str(row['id'])
            if identifier in seen:
                continue
            seen.add(identifier)
            scored[identifier] += 1 / (60 + rank)
            articles.setdefault(identifier, dict(row))
            kinds[identifier].add(kind)
    result = []
    for identifier in sorted(scored, key=lambda key: (-scored[key], key)):
        row = articles[identifier]
        row['_reader_score'] = scored[identifier]
        row['_reader_match_kinds'] = sorted(kinds[identifier])
        row['_reader_semantic_only'] = kinds[identifier] == {'semantic'}
        result.append(row)
    return result


def balanced_union(intent_rows, *, limit=300):
    """Allocate after deduplication, not before an unbalanced final global sort.

    When limit is smaller than the number of nonempty intents, universal coverage
    is mathematically impossible; canonical priority orders those opportunities.
    Every selected row carries *all* matching intent IDs, including later rounds.
    """
    limit = max(0, min(int(limit), 300))
    ordered = sorted(intent_rows, key=lambda pair: (-float(pair[0].get('priority', 1)), str(pair[0]['id'])))
    metadata = {}
    for intent, rows in ordered:
        for row in rows:
            key = str(row['id'])
            entry = metadata.setdefault(key, {'intents': set(), 'kinds': set(), 'score': 0.0})
            entry['intents'].add(str(intent['id']))
            entry['kinds'].update(row.get('_reader_match_kinds', []))
            entry['score'] = max(entry['score'], row.get('_reader_score', 0.0))
    selected, seen = [], set()
    cursors = [0] * len(ordered)
    while len(selected) < limit:
        progress = False
        for index, (_, rows) in enumerate(ordered):
            while cursors[index] < len(rows) and str(rows[cursors[index]]['id']) in seen:
                cursors[index] += 1
            if cursors[index] >= len(rows):
                continue
            row = dict(rows[cursors[index]])
            cursors[index] += 1
            key = str(row['id'])
            seen.add(key)
            entry = metadata[key]
            row['_reader_intent_ids'] = sorted(entry['intents'])
            row['_reader_match_kinds'] = sorted(entry['kinds'])
            row['_reader_semantic_only'] = entry['kinds'] == {'semantic'}
            row['_reader_score'] = entry['score']
            selected.append(row)
            progress = True
            if len(selected) >= limit:
                break
        if not progress:
            break
    return selected


def lexical_rows(conn, intent, *, limit=40):
    # PostgreSQL's simple dictionary preserves original-script lexemes. The
    # plain query requires all terms, preserving qualified/conjunctive intent;
    # unlike substring matching, AI does not match retail or airline.
    #
    # Reads the generated/stored title_summary_tsv column, not an inline
    # to_tsvector(...) expression: a GIN index over a bare expression still
    # re-tokenizes raw title/summary text for every candidate row's Recheck
    # Cond (this table's bitmap scans are lossy at this row count) and again
    # for ts_rank_cd below -- measured live at ~900ms for a single moderately
    # common term. Reusing the already-computed value for both cuts that to
    # ~10ms; see manage_s5_reader.py's `index` command for the migration.
    return conn.execute(_ARTICLE_SELECT + '''
      WHERE COALESCE(a.published_at,a.ingested_at)>now()-interval '14 days'
        AND (a.content_quality>=0.4 OR NOT COALESCE(a.enrichment_completed,false))
        AND a.title_summary_tsv @@ plainto_tsquery('simple',%s)
      ORDER BY ts_rank_cd(a.title_summary_tsv,
          plainto_tsquery('simple',%s)) DESC, COALESCE(a.published_at,a.ingested_at) DESC,a.id LIMIT %s''',
      (intent_query(intent), intent_query(intent), max(1, min(int(limit), 100)))).fetchall()


def identity_rows(conn, intent, recipe, *, limit=40):
    identity = intent.get('resolved_id')
    if not identity or intent.get('kind') not in ('entity', 'place'):
        return []
    field, identifier = ('entities', 'resolved_id') if intent['kind'] == 'entity' else ('places', 'place_id')
    needle = {field: [{identifier: identity, 'resolution': 'resolved'}]}
    rows = conn.execute(_ARTICLE_SELECT + '''
      JOIN public.article_understanding_current u ON u.article_id=a.id
      WHERE u.recipe_id=%s AND u.stage='facets' AND u.payload @> %s
        AND COALESCE(a.published_at,a.ingested_at)>now()-interval '14 days'
      ORDER BY COALESCE(a.published_at,a.ingested_at) DESC,a.id LIMIT %s''',
      (recipe['id'], Jsonb(needle), max(1, min(int(limit), 100)) * 3)).fetchall()
    result = []
    for row in rows:
        card = load_current(conn, row['id'], recipe['id'])
        payload = (card.get('facets') or {}).get('payload') or {}
        # Card loading checks evidence hash and eligibility generation again. A
        # merely mentioned identity is not enough to assert topical relevance.
        if any(item.get(identifier) == identity and item.get('resolution') == 'resolved'
               and item.get('role') != 'mentioned' for item in payload.get(field, [])):
            result.append(row)
        if len(result) >= limit:
            break
    return result


def cached_vector(conn, user_id, snapshot, intent, recipe):
    row = conn.execute('''SELECT embedding::text AS embedding FROM public.reader_intent_embeddings
      WHERE user_id=%s AND generation=%s AND intent_id=%s AND semantic_hash=%s AND space_id=%s''',
      (user_id, snapshot['generation'], intent['id'], semantic_hash(intent), space_id(recipe['definition']))).fetchone()
    if not row:
        return None
    raw = row['embedding']
    return json.loads(raw) if isinstance(raw, str) else list(raw)


def _recipe_or_none(conn):
    # Unlike database/permission failures, a deliberately unpromoted S3 cohort
    # is a normal absence. Do not swallow errors inside an aborted transaction.
    present = conn.execute('''SELECT r.id FROM public.understanding_control c
      JOIN public.understanding_recipes r ON r.id=c.serving_recipe
      WHERE r.enabled AND r.approved''').fetchone()
    return serving_recipe(conn) if present else None


def build_reader_candidates(conn, user_id, snapshot, *, limit=300):
    """Return private article rows. Caller applies current policy and S2 output.

    All semantic queries share a stable S3 control lock: a promotion cannot use
    the old query vector against new document geometry midway through retrieval.
    A final reader publication guard remains the caller's responsibility.
    """
    limit = max(0, min(int(limit), 300))
    if not limit:
        return []
    intents = active_intents(snapshot)
    if not intents:
        rows = conn.execute(_ARTICLE_SELECT + '''
          WHERE COALESCE(a.published_at,a.ingested_at)>now()-interval '14 days'
            AND (a.content_quality>=0.4 OR NOT COALESCE(a.enrichment_completed,false))
          ORDER BY COALESCE(a.published_at,a.ingested_at) DESC,a.id LIMIT %s''', (limit,)).fetchall()
        return [{**row, '_reader_intent_ids': [], '_reader_match_kinds': [],
                 '_reader_score': 0.0, '_reader_semantic_only': False} for row in rows]
    threshold = semantic_threshold()
    grouped = []
    with conn.transaction():
        # Lexical retrieval does not require S3 installation or promotion. Only
        # explicit semantic activation may query its tables.
        recipe = None
        if threshold is not None:
            conn.execute('SELECT singleton FROM public.understanding_control FOR SHARE')
            recipe = _recipe_or_none(conn)
            if recipe:
                conn.execute('SELECT id FROM public.understanding_recipes WHERE id=%s FOR SHARE', (recipe['id'],))
                recipe = _recipe_or_none(conn)
            # Use exact search as the initial reference even if an article HNSW
            # index exists. ANN activation needs separate measured recall evidence.
            conn.execute('SET LOCAL enable_indexscan=off')
        for intent in intents:
            legs = {'lexical': lexical_rows(conn, intent)}
            if recipe:
                legs['identity'] = identity_rows(conn, intent, recipe)
                vector = cached_vector(conn, user_id, snapshot, intent, recipe)
                if vector is not None:
                    # Existing S3 consumer validates current evidence, revision,
                    # analysis permission and approved recipe for every result.
                    legs['semantic'] = [row for row in semantic_rows(conn, vector, limit=40, lookback_hours=336)
                        if math.isfinite(float(row.get('similarity', -1))) and float(row['similarity']) >= threshold]
            grouped.append((intent, fuse_intent_legs(legs)))
    return balanced_union(grouped, limit=limit)


def retrieval_configuration():
    from .retrieval_contract import RECIPE
    dense = os.getenv('S6_DENSE_ENABLED', 'false').lower() == 'true'
    threshold = None
    if dense:
        try:
            threshold = float(os.environ['S6_MIN_SIMILARITY'])
            if not math.isfinite(threshold) or not 0 <= threshold <= 1:
                threshold = None
        except (ValueError, KeyError):
            pass
    return {**RECIPE, 'dense_requested': dense, 'min_similarity': threshold,
            'ann': os.getenv('S6_ANN_ENABLED', 'false').lower() == 'true'}


class RetrievalDeadline(TimeoutError):
    pass


def _deadline_check(deadline, clock):
    """The cheap half of _remaining: raise if the deadline has already
    passed. Pure Python, no round trip -- safe to call once per state in a
    tight per-state loop, unlike _remaining itself (see its docstring)."""
    if deadline - clock() <= 0:
        raise RetrievalDeadline('retrieval deadline')


def _remaining(conn, deadline, clock):
    """Check the deadline, then tighten statement_timeout/lock_timeout to
    whatever's left, in one round trip.

    Called once per round (not once per state) in build_candidate_batch's
    round loop: measured live, calling this per state added a SET-config
    round trip for every one of a real profile's ~15 intents, on top of the
    per-state savepoint _s6_page already needs (roughly doubling the round
    trip count for that loop). Per-state deadline enforcement during the
    loop itself uses the cheaper _deadline_check instead -- pure Python, no
    round trip -- so a round that's actually out of time still stops
    promptly; only the Postgres-side timeout refresh moved to once per
    round. The outer asyncio.wait_for deadline (retrieval_runtime.py) is
    the enforcement that can never be loosened by this; this one only
    bounds how long any single query is allowed to run.
    """
    remaining = deadline - clock()
    if remaining <= 0:
        raise RetrievalDeadline('retrieval deadline')
    conn.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                 (str(max(1, int(remaining * 1000))), str(min(100, max(1, int(remaining * 1000))))))


def _s6_recipe(conn):
    installed = conn.execute("SELECT to_regclass('public.understanding_control') AS relation").fetchone()
    if not installed or not installed['relation']:
        return None
    # Facet/identity capability must not depend on embedding geometry or a dense flag.
    return conn.execute('''SELECT r.* FROM public.understanding_control c
      JOIN public.understanding_recipes r ON r.id=c.serving_recipe
      WHERE r.enabled AND r.approved''').fetchone()


def _s6_vectors(conn, request, intents, recipe, config):
    if not recipe or config['min_similarity'] is None:
        return {}, None
    from .understanding_contract import validate_embedding
    geometry = space_id(recipe['definition'])
    installed = conn.execute("SELECT to_regclass('public.reader_intent_embeddings') AS relation").fetchone()
    if not installed or not installed['relation']:
        return {}, geometry
    rows = conn.execute('''SELECT intent_id,semantic_hash,embedding::text AS embedding
      FROM public.reader_intent_embeddings WHERE user_id=%s AND generation=%s AND space_id=%s''',
      (request.user_id, request.generation, geometry)).fetchall()
    hashes = {i['id']: semantic_hash(i) for i in intents}
    result = {}
    for row in rows:
        key = str(row['intent_id'])
        if hashes.get(key) == row['semantic_hash']:
            try:
                result[key] = validate_embedding(json.loads(row['embedding']))
            except (TypeError, ValueError):
                continue
    return result, geometry


def _s6_page(conn, state, *, request, recipe, count, config):
    """Narrow indexable pages. SQL filters only proven-equivalent hard predicates.

    All other policies are evaluated on batched current evidence before allocation.
    Dense ANN expands a prefix; exact legs use stable snapshot-local keysets.
    """
    from datetime import timedelta
    from .reader_compiler import compile_reader
    policies = compile_reader(request.profile.model_dump(), now=request.as_of)['policies']
    blocked = [p['value'] for p in policies if p['kind'] == 'article']
    filters = '''a.ingested_at<=%s AND COALESCE(a.published_at,a.ingested_at)<=%s
      AND COALESCE(a.published_at,a.ingested_at)>%s AND NOT(a.id::text=ANY(%s::text[]))'''
    params = [request.as_of, request.as_of, request.as_of - timedelta(days=14), blocked]
    leg = state['leg']
    join = ''
    fields = ''
    if leg == 'lexical':
        # Reads the generated/stored title_summary_tsv column rather than an
        # inline to_tsvector(...) expression -- see lexical_rows above and
        # manage_s5_reader.py's `index` command for why (a ~900ms-per-term
        # re-tokenization cost measured live, cut to ~10ms).
        score = "ts_rank_cd(a.title_summary_tsv,plainto_tsquery('simple',%s))::double precision"
        prefix = [state['query']]
        filters += " AND a.title_summary_tsv @@ plainto_tsquery('simple',%s)"
        params.append(state['query'])
    elif leg == 'dense':
        score = '1-(u.embedding <=> %s::vector)'
        prefix = [str(state['vector'])]
        join = " JOIN public.article_understanding_current u ON u.article_id=a.id AND u.stage='embedding'"
        filters += ' AND u.recipe_id=%s'
        params.append(recipe['id'])
        fields = ',u.input_hash,u.semantic_revision,u.analysis_eligibility_generation'
    elif leg == 'identity':
        score = 'extract(epoch FROM COALESCE(a.published_at,a.ingested_at))::double precision'
        prefix = []
        join = " JOIN public.article_understanding_current u ON u.article_id=a.id AND u.stage='facets'"
        filters += ' AND u.recipe_id=%s AND u.payload @> %s'
        params += [recipe['id'], Jsonb(state['needle'])]
        fields = ',u.input_hash,u.semantic_revision,u.analysis_eligibility_generation'
    else:
        score = 'extract(epoch FROM COALESCE(a.published_at,a.ingested_at))::double precision'
        prefix = []
    base = f'SELECT a.id,{score} AS score{fields} FROM public.articles a{join} WHERE {filters}'
    if leg == 'dense' and config['ann']:
        from scripts.manage_s6_retrieval import DENSE, index_state
        index = index_state(conn, DENSE)
        if not index['valid'] or not index['matches']:
            raise ValueError('ANN requires the valid S6 cosine index')
        # The distance ORDER BY stays directly on the indexed relation. A second
        # deterministic sort is applied after bounded expansion, not in the ANN scan.
        depth = min(2400, state['depth'] + count, state['row_allowance'],
                    state.get('unique_allowance', 2400))
        sql = base + ' ORDER BY u.embedding <=> %s::vector LIMIT %s'
        values = [*prefix, *params, str(state['vector']), depth]
        old = conn.execute("SELECT current_setting('hnsw.iterative_scan',true) AS value").fetchone()
        if not old or old['value'] is None:
            raise ValueError('ANN requires iterative-scan-capable pgvector')
        with conn.transaction():
            settings = {name: conn.execute('SELECT current_setting(%s) AS value', (name,)).fetchone()['value']
                        for name in ('hnsw.ef_search', 'hnsw.max_scan_tuples')}
            conn.execute("SET LOCAL hnsw.iterative_scan='strict_order'")
            conn.execute('SET LOCAL hnsw.ef_search=100')
            conn.execute('SET LOCAL hnsw.max_scan_tuples=20000')
            rows = conn.execute(sql, values).fetchall()
            conn.execute("SELECT set_config('hnsw.iterative_scan',%s,true)", (old['value'],))
            for name, value in settings.items():
                conn.execute('SELECT set_config(%s,%s,true)', (name, value))
        state['depth'] = depth
        return sorted(rows, key=lambda r: (-r['score'], str(r['id'])))
    cursor = state.get('cursor')
    condition = ''
    values = [*prefix, *params]
    if cursor:
        condition = ' WHERE (score<%s OR (score=%s AND id>%s::uuid))'
        values += [cursor[0], cursor[0], cursor[1]]
    sql = 'SELECT * FROM (' + base + ') ranked' + condition + ' ORDER BY score DESC,id LIMIT %s'
    values.append(count)
    if leg == 'dense':
        # Scope exact mode to this query. Never disable lexical/identity index plans.
        old = conn.execute("SELECT current_setting('enable_indexscan') AS value").fetchone()['value']
        # Caller owns a savepoint: on failure rollback restores the setting.
        # Do not mask QueryCanceled by attempting SQL in an aborted transaction.
        conn.execute('SET LOCAL enable_indexscan=off')
        rows = conn.execute(sql, values).fetchall()
        conn.execute("SELECT set_config('enable_indexscan',%s,true)", (old,))
        return rows
    return conn.execute(sql, values).fetchall()


def _s6_hydrate(conn, identifiers, recipe):
    from .understanding_repository import load_current_batch
    import uuid
    result = {}
    for start in range(0, len(identifiers), 300):
        chunk = identifiers[start:start + 300]
        selection = _ARTICLE_SELECT.replace('SELECT a.*,',
            'SELECT a.*,to_jsonb(artifact) AS _s6_display_artifact,', 1)
        articles = conn.execute(selection + ' WHERE a.id=ANY(%s::uuid[])',
            ([uuid.UUID(i) for i in chunk],)).fetchall()
        cards = load_current_batch(conn, chunk, recipe['id']) if recipe else {}
        for row in articles:
            from .retrieval_contract import article_stamp
            row = dict(row)
            selected_artifact = row.pop('_s6_display_artifact', None)
            row['artifact_state_stamp'] = article_stamp(selected_artifact) if selected_artifact else None
            key = str(row['id'])
            current = cards.get(key, {})
            result[key] = {'article': dict(row), 'current': current,
                           'policy': current.get('policy_evidence') or {
                               'topic_ids': None, 'entity_ids': None, 'place_ids': None,
                               'sector_ids': None, 'language': None, 'content_language': None}}
    return result


def _s6_eligibility(request, hydrated):
    from .article_content import serialize_article
    from .reader_compiler import policy_allows, compile_reader
    article, evidence = hydrated['article'], hydrated['policy']
    # S2 rights decide display. Analysis revocation vetoes derived matches, not
    # otherwise permitted publisher metadata in ordinary lexical recommendations.
    public = serialize_article(article, include_body=False)
    if (public.get('presentation') or {}).get('mode') == 'unavailable':
        return 'display_unavailable'
    row = {**article, **evidence}
    profile = request.profile.model_dump()
    if not policy_allows(profile, row, now=request.as_of):
        compiled = compile_reader(profile, now=request.as_of)
        if (compiled['languages'] and not (row.get('language') or row.get('content_language'))
            or any(p['kind'] == 'subject' and not isinstance(row.get(p['scope'] + '_ids'), list)
                   for p in compiled['policies'])):
            return 'policy_unknown'
        return 'policy_denied'
    return None


def _s6_match_valid(state, hit, hydrated, recipe):
    if state['leg'] not in ('identity', 'dense'):
        return True
    current = hydrated['current']
    stage = 'embedding' if state['leg'] == 'dense' else 'facets'
    if not current.get(stage) or any(str(current.get(key)) != str(hit.get(key))
            for key in ('input_hash', 'semantic_revision', 'analysis_eligibility_generation')):
        return False
    if state['leg'] == 'identity':
        values = hydrated['policy'].get(state['scope'] + '_ids')
        return isinstance(values, list) and state['identity'] in values
    return True


def _s6_evidence_stamp(current):
    from .retrieval_contract import article_stamp
    return {**{key: current.get(key) for key in (
        'input_hash', 'semantic_revision', 'analysis_eligibility_generation', 'recipe_id')},
        'facets_digest': article_stamp(current['facets']) if current.get('facets') else None,
        'embedding_digest': article_stamp(current['embedding']) if current.get('embedding') else None}


def _s6_allocate(entries, intents, limit):
    """Dedup first; charge one actual intent, retaining every matching intent."""
    if not limit:
        return []
    weights = {i['id']: float(i['priority']) for i in intents} or {None: 1.0}
    order = sorted(weights, key=lambda key: (-weights[key], key or ''))
    pools = {}
    for key in order:
        scores = {}
        for article_id, entry in entries.items():
            families = {}
            for match in entry['matches'].values():
                if match.intent_id == key:
                    families[match.leg] = max(families.get(match.leg, 0), 1 / (60 + match.rank))
            if families:
                scores[article_id] = sum(families.values())
        pools[key] = sorted(scores, key=lambda aid: (-scores[aid], aid))
    selected, seen, served = [], set(), {key: 0 for key in order}
    while len(selected) < limit:
        for key in order:
            while pools[key] and pools[key][0] in seen:
                pools[key].pop(0)
        available = [key for key in order if pools[key]]
        if not available:
            break
        key = min(available, key=lambda key: (served[key] > 0, served[key] / weights[key], order.index(key)))
        identifier = pools[key].pop(0)
        seen.add(identifier)
        served[key] += 1
        selected.append((identifier, key))
    return selected


def build_candidate_batch(conn, user_id, snapshot, *, limit=300, as_of=None, deadline=None,
                          clock=None, configuration=None):
    """S6 service: exclusive idle connection, no provider, no delivery side effects.

    A repeatable read snapshot makes keyset pages/evidence coherent. Publication
    MUST use authorize_candidate_batch after this transaction ends.
    """
    import time
    import uuid
    from datetime import datetime, timezone
    from .reader_contract import canonical_hash
    from .retrieval_contract import RetrievalRequest, CandidateBatch, Candidate, Match, validity, article_stamp
    clock = clock or time.monotonic
    started = clock()
    deadline = min(started + 2 if deadline is None else deadline, started + 2)
    config = configuration or retrieval_configuration()
    if snapshot.get('migration_status') != 'ready':
        raise ValueError('reader review required')
    request = RetrievalRequest(user_id=str(user_id), profile=snapshot['profile'], limit=limit,
        as_of=as_of or datetime.now(timezone.utc), **{k: snapshot[k] for k in ('generation','revision','learning_revision')})
    intents = active_intents({'profile': request.profile.model_dump()}, now=request.as_of)
    diagnostics = {'unique_examined': 0, 'rows_returned': 0, 'rounds': 0, 'legs': [],
                   'rejected': {}, 'stop_reason': 'exhausted', 'requested': limit}
    entries, hydration, states, examined = {}, {}, [], set()
    recipe, geometry = None, None
    # Changing isolation after earlier SQL is an error, not an implicit weaker snapshot.
    if hasattr(conn, 'info'):
        from psycopg.pq import TransactionStatus
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise ValueError('retrieval requires an idle exclusively owned connection')
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        _remaining(conn, deadline, clock)
        recipe = _s6_recipe(conn)
        vectors = {}
        try:
            with conn.transaction():
                vectors, geometry = _s6_vectors(conn, request, intents, recipe, config)
        except Exception:
            # Optional geometry/cache failure cannot suppress lexical/identity.
            diagnostics['vector_setup'] = 'unavailable'
        for intent in intents:
            query = intent_query(intent)
            variants = [('strict', query)]
            if intent['label'] != query:
                variants.append(('label', intent['label']))
            for variant, text in variants:
                states.append({'intent': intent['id'], 'leg': 'lexical', 'variant': variant, 'query': text})
            scope = intent['kind']
            fields = {'entity': ('entities','resolved_id'), 'place': ('places','place_id'), 'topic': ('topics','topic_id')}
            if intent.get('resolved_id') and scope in fields:
                if recipe:
                    field, name = fields[scope]
                    item = {name: intent['resolved_id']}
                    if scope != 'topic':
                        item['resolution'] = 'resolved'
                    states.append({'intent': intent['id'], 'leg': 'identity', 'variant': scope,
                        'scope': scope, 'identity': intent['resolved_id'], 'needle': {field: [item]}})
                else:
                    diagnostics['legs'].append({'intent_id': intent['id'], 'leg': 'identity', 'status': 'missing_facets'})
            if intent['id'] in vectors:
                states.append({'intent': intent['id'], 'leg': 'dense', 'variant': 'ann' if config['ann'] else 'exact',
                               'vector': vectors[intent['id']], 'query': query})
            else:
                diagnostics['legs'].append({'intent_id': intent['id'], 'leg': 'dense',
                    'status': 'missing_vector' if config['dense_requested'] else 'disabled'})
        if not intents:
            states.append({'intent': None, 'leg': 'generic', 'variant': 'recent'})
        for state in states:
            state.update(cursor=None, seen=set(), rank=0, depth=0, status='available')
        for round_number in range(3 if limit else 0):
            diagnostics['rounds'] = round_number + 1
            available = [s for s in states if s['status'] == 'available']
            if not available:
                break
            # Tighten the Postgres-side timeout once per round, not once per
            # state: see _remaining's docstring. Per-state enforcement below
            # still uses the free, pure-Python _deadline_check every time.
            _remaining(conn, deadline, clock)
            # Round-level fair shares prevent the first broad interest exhausting
            # the raw budget. More query variants never earn more per-intent work.
            active_keys = {s['intent'] for s in available}
            remaining_ids = 2400 - len(examined)
            per_intent = max(1, min(800, remaining_ids) // len(active_keys))
            count_by_intent = {key: sum(s['intent'] == key for s in available) for key in active_keys}
            pending = []
            try:
                # All states this round share one savepoint, not one each:
                # every leg here is a read-only SELECT (the outer transaction
                # is REPEATABLE READ READ ONLY), so a savepoint's only job is
                # recovering from Postgres marking the transaction aborted
                # after one query errors/cancels -- it is not undoing any
                # data change. Measured live: a real 15-intent profile paid
                # a SAVEPOINT+RELEASE round trip per state, on top of the
                # actual query, roughly doubling the round trip count for
                # this loop. On any single state's failure, only that state
                # is blamed (matching the prior per-state behavior exactly);
                # every other state's results, already computed and already
                # applied to diagnostics/examined/pending before the failure,
                # are untouched by the rollback and are not recomputed --
                # only the remaining, not-yet-attempted states retry, under a
                # fresh savepoint.
                remaining_states = list(available)
                stop_round = False
                while remaining_states and not stop_round:
                    try:
                        with conn.transaction():
                            while remaining_states:
                                state = remaining_states[0]
                                _deadline_check(deadline, clock)
                                row_budget = 7200 - diagnostics['rows_returned']
                                state['row_allowance'] = row_budget
                                state['unique_allowance'] = 2400 - len(examined)
                                count = min(300, max(1, per_intent // count_by_intent[state['intent']]), row_budget,
                                            state['unique_allowance'])
                                if count <= 0 or len(examined) >= 2400:
                                    diagnostics['stop_reason'] = 'raw_budget'
                                    stop_round = True
                                    break
                                if state['leg'] == 'dense' and config['ann'] and min(row_budget, state['unique_allowance']) <= state['depth']:
                                    state['status'] = 'budget_limited'
                                    remaining_states.pop(0)
                                    continue
                                hits = _s6_page(conn, state, request=request, recipe=recipe, count=count, config=config)
                                remaining_states.pop(0)  # only after _s6_page succeeds
                                diagnostics['rows_returned'] += len(hits)
                                full_page = len(hits) >= (state['depth'] if state['leg'] == 'dense' and config['ann'] else count)
                                if not full_page:
                                    state['status'] = 'exhausted'
                                if hits:
                                    state['cursor'] = (hits[-1]['score'], str(hits[-1]['id']))
                                for hit in hits:
                                    key = str(hit['id'])
                                    if key not in examined and len(examined) >= 2400:
                                        diagnostics['stop_reason'] = 'raw_budget'
                                        stop_round = True
                                        break
                                    examined.add(key)
                                    if key in state['seen']:
                                        continue
                                    state['seen'].add(key)
                                    state['rank'] += 1
                                    if state['leg'] == 'dense' and hit['score'] < config['min_similarity']:
                                        continue
                                    pending.append((state, hit, state['rank']))
                    except RetrievalDeadline:
                        raise
                    except Exception as exc:
                        # SQL rollback completes before continuing any other leg.
                        # remaining_states[0] is always the state that was being
                        # attempted: it's only popped after _s6_page succeeds, so
                        # if _s6_page (or anything above it in this savepoint's
                        # current iteration) raised, it's still at index 0.
                        from psycopg.errors import QueryCanceled
                        if remaining_states:
                            failed_state = remaining_states.pop(0)
                            failed_state['status'] = 'timed_out' if isinstance(exc, (QueryCanceled, TimeoutError)) else 'failed'
                missing = list(dict.fromkeys(str(hit['id']) for _, hit, _ in pending if str(hit['id']) not in hydration))
                for start in range(0, len(missing), 300):
                    _remaining(conn, deadline, clock)
                    chunk = missing[start:start+300]
                    hydrated = _s6_hydrate(conn, chunk, recipe)
                    hydration.update({key: hydrated.get(key) for key in chunk})
                for state, hit, rank in pending:
                    if clock() >= deadline:
                        raise RetrievalDeadline()
                    identifier = str(hit['id'])
                    hydrated = hydration.get(identifier)
                    if not hydrated:
                        continue
                    reason = _s6_eligibility(request, hydrated)
                    if not reason and not _s6_match_valid(state, hit, hydrated, recipe):
                        reason = 'stale_or_unresolved_evidence'
                    if reason:
                        diagnostics['rejected'][reason] = diagnostics['rejected'].get(reason, 0) + 1
                        continue
                    match = Match(intent_id=state['intent'], leg=state['leg'], variant=state['variant'],
                        rank=rank, score=float(hit['score']), query_hash=canonical_hash(state.get('query') or state.get('needle') or {}),
                        recipe_id=recipe['id'] if state['leg'] in ('dense','identity') else None,
                        input_hash=hit.get('input_hash'), unresolved_qualifiers=state['variant'] == 'label')
                    entry = entries.setdefault(identifier, {'matches': {}, 'hydrated': hydrated})
                    entry['matches'][(state['intent'], state['leg'], state['variant'])] = match
                if len(_s6_allocate(entries, intents, limit)) >= limit:
                    diagnostics['stop_reason'] = 'target_reached'
                    break
                if len(examined) >= 2400 or diagnostics['rows_returned'] >= 7200:
                    diagnostics['stop_reason'] = 'raw_budget'
                    break
            except (RetrievalDeadline, TimeoutError):
                diagnostics['stop_reason'] = 'deadline'
                break
        else:
            if not limit:
                diagnostics['stop_reason'] = 'target_reached'
            elif any(s['status'] == 'available' for s in states):
                diagnostics['stop_reason'] = 'round_budget'
        diagnostics['legs'] += [{'intent_id': s['intent'], 'leg': s['leg'], 'variant': s['variant'],
            'status': 'budget_limited' if s['status'] == 'available' else s['status']} for s in states]
    candidates = []
    for identifier, allocation in _s6_allocate(entries, intents, limit):
        entry = entries[identifier]
        current = entry['hydrated']['current']
        matches = list(entry['matches'].values())
        candidates.append(Candidate(article_id=identifier, allocated_intent_id=allocation,
            matched_intent_ids=sorted({m.intent_id for m in matches if m.intent_id}), matches=matches,
            retrieval_score=sum(max(1/(60+m.rank) for m in matches if m.leg == family)
                                for family in {m.leg for m in matches}),
            article_stamp=article_stamp(entry['hydrated']['article']),
            evidence_stamp=_s6_evidence_stamp(current),
            policy_evidence=entry['hydrated']['policy'], article=entry['hydrated']['article']))
    diagnostics.update(unique_examined=len(examined), returned=len(candidates),
        elapsed_ms=round((clock()-started)*1000, 3), coverage={i['id']: sum(i['id'] in c.matched_intent_ids for c in candidates) for i in intents})
    degraded = bool(diagnostics['rejected'].get('policy_unknown')) or diagnostics['stop_reason'] in ('deadline','raw_budget','round_budget') or any(
        leg['status'] in ('failed','timed_out','missing_vector','missing_facets','budget_limited')
        and not (leg['status'] == 'budget_limited' and diagnostics['stop_reason'] == 'target_reached')
        for leg in diagnostics['legs'])
    return CandidateBatch(request_id=str(uuid.uuid4()), user_id=request.user_id,
        generation=request.generation, revision=request.revision, learning_revision=request.learning_revision,
        reader_hash=canonical_hash(request.profile.model_dump()), as_of=request.as_of, valid_until=validity(request),
        retrieval_recipe=canonical_hash(config), configuration=config, s3_recipe_id=recipe['id'] if recipe else None,
        space_id=geometry, status='degraded' if degraded else ('complete' if candidates else 'empty'),
        candidates=candidates, diagnostics=diagnostics)


def rank_candidate_batch(batch, scorer):
    """Explicit internal S7 adapter. No legacy prefilter, truncation or provider.

    The injected scorer owns its cost/output policy; nothing installs one or
    enables serving automatically. It sees every candidate, outside DB locks.
    A private deep copy prevents mutation of the later authorization stamps.
    """
    from .retrieval_contract import CandidateBatch, validate_decisions
    checked = CandidateBatch.model_validate(batch.model_dump())
    if checked.status == 'stale':
        raise ValueError('stale candidate batch')
    return validate_decisions(checked, scorer(checked.model_copy(deep=True)))


@contextmanager
def authorize_candidate_batch(conn, user_id, batch, decisions, *, now=None, clock=None,
                              additional_article_ids=(), before_article_locks=None):
    """Fresh S6 -> delivery fence; consume synchronously inside this context.

    No network/await is allowed here. Locks last through the caller's receipt
    writes and serialization, not model work. Lock order follows S2/S3 writers:
    user -> reader -> sorted articles -> control/recipe -> selected artifacts/results.
    Unknown/stale state rejects the batch; callers may start one new retrieval,
    never silently fall back to unchecked legacy recommendations.
    """
    import time
    from datetime import datetime, timezone
    from .reader_repository import publication_guard, ReaderConflict
    from .reader_contract import canonical_hash
    from .retrieval_contract import CandidateBatch, RetrievalRequest, article_stamp, validate_decisions
    batch = CandidateBatch.model_validate(batch.model_dump())
    decisions = validate_decisions(batch, decisions)
    clock = clock or time.monotonic
    deadline = clock() + 2
    utcnow = now or (lambda: datetime.now(timezone.utc))

    def current_time():
        value = utcnow()
        if value.tzinfo is None or not batch.as_of <= value < batch.valid_until:
            raise ReaderConflict('retrieval_expired')
        return value

    if str(user_id) != batch.user_id:
        raise ReaderConflict('retrieval_account_mismatch')
    if batch.status == 'stale' or batch.retrieval_recipe != canonical_hash(retrieval_configuration()):
        raise ReaderConflict('retrieval_configuration_changed')
    current_time()
    if hasattr(conn, 'info'):
        from psycopg.pq import TransactionStatus
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise ValueError('publication requires an idle exclusively owned connection')
    with conn.transaction():
        _remaining(conn, deadline, clock)
        with publication_guard(conn, user_id, batch.model_dump()) as snapshot:
            if snapshot['migration_status'] != 'ready' or canonical_hash(snapshot['profile']) != batch.reader_hash:
                raise ReaderConflict('reader_changed')
            # S7's final composition may add independently authorized S4 articles.
            # Lock the union once, in the same sorted order as ordinary candidates.
            # The callback acquires S4 source/control locks BEFORE these articles.
            if before_article_locks is not None:
                before_article_locks(conn)
            identifiers = sorted({candidate.article_id for candidate in batch.candidates} |
                                 {str(value) for value in additional_article_ids})
            if len(identifiers) > 600:
                raise ValueError('publication article limit exceeded')
            locked = conn.execute('''SELECT id,display_content_artifact_id,analysis_content_artifact_id
              FROM public.articles WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE''', (identifiers,)).fetchall()
            if len(locked) != len(identifiers):
                raise ReaderConflict('retrieval_article_deleted')
            installed = conn.execute("SELECT to_regclass('public.understanding_control') AS relation").fetchone()
            if installed and installed['relation']:
                conn.execute('SELECT serving_recipe FROM public.understanding_control FOR SHARE').fetchall()
            recipe = _s6_recipe(conn)
            if (recipe['id'] if recipe else None) != batch.s3_recipe_id:
                raise ReaderConflict('retrieval_recipe_changed')
            if recipe:
                conn.execute('SELECT id FROM public.understanding_recipes WHERE id=%s FOR SHARE', (recipe['id'],)).fetchall()
                # Recheck enabled/approved after any recipe writer has released its lock.
                if _s6_recipe(conn) is None:
                    raise ReaderConflict('retrieval_recipe_changed')
            artifacts = sorted({row[key] for row in locked
                for key in ('display_content_artifact_id', 'analysis_content_artifact_id') if row.get(key) is not None})
            if artifacts:
                conn.execute('SELECT id FROM public.article_content_artifacts WHERE id=ANY(%s) ORDER BY id FOR SHARE',
                             (artifacts,)).fetchall()
            if recipe and identifiers:
                conn.execute('''SELECT article_id FROM public.article_understanding_results
                  WHERE article_id=ANY(%s::uuid[]) AND recipe_id=%s ORDER BY article_id,stage FOR SHARE''',
                  (identifiers, recipe['id'])).fetchall()
            _remaining(conn, deadline, clock)
            fresh = _s6_hydrate(conn, identifiers, recipe)
            request = RetrievalRequest(user_id=batch.user_id, generation=batch.generation,
                revision=batch.revision, learning_revision=batch.learning_revision,
                profile=snapshot['profile'], limit=len(batch.candidates), as_of=current_time())
            for candidate in batch.candidates:
                row = fresh.get(candidate.article_id)
                if not row or article_stamp(row['article']) != candidate.article_stamp:
                    raise ReaderConflict('retrieval_article_changed')
                evidence = _s6_evidence_stamp(row['current'])
                if evidence != candidate.evidence_stamp or row['policy'] != candidate.policy_evidence:
                    raise ReaderConflict('retrieval_evidence_changed')
                if _s6_eligibility(request, row):
                    raise ReaderConflict('retrieval_policy_changed')
                for match in candidate.matches:
                    if match.leg in ('identity', 'dense'):
                        stage = 'facets' if match.leg == 'identity' else 'embedding'
                        if not row['current'].get(stage):
                            raise ReaderConflict('retrieval_evidence_changed')
            _remaining(conn, deadline, clock)
            current_time()
            # Only accepted candidates; S7 score is used as ordering, never as an
            # invented probability. The candidate provenance remains intact.
            candidates = {c.article_id: c for c in batch.candidates}
            yield [candidates[d.article_id] for d in sorted(decisions, key=lambda d: (-d.score, d.article_id)) if d.relevant]
            # Slow synchronous receipt/serialization work cannot commit after the
            # validity window or publication budget expired either.
            _remaining(conn, deadline, clock)
            current_time()
