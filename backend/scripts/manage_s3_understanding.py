#!/usr/bin/env python3
"""Explicit S3 migration/control. Status and dry-run are read-only defaults.

Credentials are read from an environment variable, never command-line values.
No schema, model processing or consumer promotion is performed on API startup.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.services import understanding_repository as repo
from app.services.understanding_contract import DEFAULT_RECIPE, recipe_id


def validate_promotion(doc, identifier):
    if (not isinstance(doc, dict) or doc.get('recipe_id')!=identifier
        or doc.get('quality_gates_passed') is not True or doc.get('blockers') != []):
        raise ValueError('matching recipe with passing quality report required')
    ops=doc.get('operations')
    if (not isinstance(ops, dict)
        or not isinstance(ops.get('build_sha'), str) or not ops['build_sha'].strip()
        or type(ops.get('schema_version')) is not int or ops['schema_version'] < 1
        or ops.get('s1_s2_verified') is not True or ops.get('rollback_verified') is not True
        or ops.get('quiet_and_burst_verified') is not True):
        raise ValueError('missing build/schema/prerequisite/rollback evidence')
    limits={'observation_hours':72,'reviewed_articles':600,'holdout_articles':150,
            'ready_fraction':.99,'filtered_ann_recall_at_50':.98,'load_multiplier':2}
    for key,minimum in limits.items():
        value=ops.get(key)
        if type(value) not in (float,int) or not minimum<=value<float('inf'):
            raise ValueError('operational gate failed: '+key)
        if key in ('ready_fraction','filtered_ann_recall_at_50') and value > 1:
            raise ValueError('operational fraction exceeds one: '+key)
        if key in ('reviewed_articles','holdout_articles') and type(value) is not int:
            raise ValueError('article counts must be integers: '+key)
    if ops['holdout_articles'] > ops['reviewed_articles']:
        raise ValueError('holdout articles cannot exceed reviewed articles')
    if any(type(ops.get(k)) is not int or ops[k]!=0
           for k in ('stale_publications','wrong_article_evidence','private_text_leaks','mixed_spaces')):
        raise ValueError('integrity counters must all be zero')
    slices = doc.get('supported_slices')
    if (ops.get('budget_verified') is not True or not isinstance(slices, list) or not slices
        or any(not isinstance(value, str) or not value.strip() for value in slices)):
        raise ValueError('budget and supported slices must be verified')


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['status','migrate','register','backfill','enable','disable','pause','configure','promote','revoke','restore'])
    p.add_argument('--database-env',default='DATABASE_URL')
    p.add_argument('--apply',action='store_true')
    p.add_argument('--recipe',default=None)
    p.add_argument('--recipe-file',type=Path)
    p.add_argument('--max-rows',type=int,default=100)
    p.add_argument('--after',default=None)
    p.add_argument('--daily-budget-usd',type=float,default=0)
    p.add_argument('--evidence',type=Path)
    p.add_argument('--article-id')
    p.add_argument('--build-index',action='store_true')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if not 1<=args.max_rows<=10000: raise ValueError('max rows must be 1..10000')
    definition=json.loads(args.recipe_file.read_text()) if args.recipe_file else dict(DEFAULT_RECIPE)
    identifier=args.recipe or recipe_id(definition)
    with psycopg.connect(os.environ[args.database_env],autocommit=True,row_factory=dict_row) as conn:
        if args.command=='status':
            print(json.dumps(repo.status(conn),default=str,indent=2)); return
        if not args.apply:
            with conn.transaction():
                conn.execute('SET TRANSACTION READ ONLY')
                rows=conn.execute('SELECT count(*) AS count FROM public.articles').fetchone()['count']
                vector=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
                print(json.dumps({'mode':'dry_run','command':args.command,'recipe':identifier,
                  'articles':rows,'max_rows':args.max_rows,'vector':vector},default=str)); return
        if args.command=='migrate':
            repo.ensure_schema(conn)
            if args.build_index:
                # Separate autocommit operation; interruption leaves resumable invalid index.
                state=conn.execute("""SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
                  WHERE c.relname='s3_embedding_hnsw' AND c.relnamespace='public'::regnamespace""").fetchone()
                if state and not state['indisvalid']:
                    conn.execute('DROP INDEX CONCURRENTLY public.s3_embedding_hnsw')
                conn.execute("""CREATE INDEX CONCURRENTLY IF NOT EXISTS s3_embedding_hnsw
                  ON public.article_understanding_results USING hnsw(embedding vector_cosine_ops)
                  WHERE stage='embedding'""")
        elif args.command=='register': repo.register_recipe(conn,definition)
        elif args.command in ('enable','disable'): repo.set_recipe_enabled(conn,identifier,args.command=='enable')
        elif args.command in ('pause','configure'):
            repo.configure(conn,submissions_enabled=args.command=='configure',daily_budget_usd=args.daily_budget_usd)
        elif args.command=='backfill':
            scanned=inserted=0; cursor=args.after
            while scanned<args.max_rows:
                batch=repo.reconcile(conn,identifier,limit=min(100,args.max_rows-scanned),after=cursor)
                scanned+=batch['scanned']; inserted+=batch['inserted']; cursor=batch['next_cursor']
                print(json.dumps({'scanned':scanned,'inserted':inserted,'next_cursor':cursor}),flush=True)
                if not batch['scanned']: break
        elif args.command in ('revoke','restore'):
            if not args.article_id: raise ValueError('article id required')
            repo.revoke(conn,args.article_id,args.command=='revoke')
        elif args.command=='promote':
            if not args.evidence: raise ValueError('reviewed promotion evidence required')
            doc=json.loads(args.evidence.read_text()); validate_promotion(doc,identifier)
            with conn.transaction():
                conn.execute('SELECT singleton FROM public.understanding_control FOR UPDATE')
                changed=conn.execute("""UPDATE public.understanding_recipes SET approved=true,evaluation=%s
                  WHERE id=%s AND enabled""",(Jsonb(doc),identifier)).rowcount
                if not changed: raise ValueError('recipe must be enabled')
                conn.execute('UPDATE public.understanding_control SET serving_recipe=%s,updated_at=now()', (identifier,))
        print(json.dumps({'command':args.command,'recipe':identifier,'applied':True}))


if __name__=='__main__':
    try: main()
    except Exception as exc:
        # Drivers may include connection secrets in exception messages.
        print(json.dumps({'error':type(exc).__name__,'status':'failed','note':'Earlier committed batches may remain applied.'}),file=sys.stderr)
        raise SystemExit(1)
