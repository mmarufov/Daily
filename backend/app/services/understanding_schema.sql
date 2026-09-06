-- S3 additive schema. Applied explicitly, never by API startup.
SELECT pg_advisory_xact_lock(731203001);
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS semantic_revision bigint NOT NULL DEFAULT 1;
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS analysis_eligibility_generation bigint NOT NULL DEFAULT 1;
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS analysis_revoked boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS public.understanding_recipes (
  id text PRIMARY KEY,
  definition jsonb NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  approved boolean NOT NULL DEFAULT false,
  evaluation jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.understanding_control (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  submissions_enabled boolean NOT NULL DEFAULT false,
  serving_recipe text REFERENCES public.understanding_recipes(id),
  daily_budget_usd numeric(16,8) NOT NULL DEFAULT 0 CHECK(daily_budget_usd >= 0),
  circuit_until timestamptz,
  circuit_reason text,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.understanding_control(singleton) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.article_understanding_jobs (
  id bigserial PRIMARY KEY,
  article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
  semantic_revision bigint NOT NULL,
  eligibility_generation bigint NOT NULL,
  recipe_id text NOT NULL REFERENCES public.understanding_recipes(id),
  stage text NOT NULL CHECK(stage IN ('facets','embedding','cluster')),
  state text NOT NULL DEFAULT 'pending' CHECK(state IN
    ('pending','running','retry_wait','ready','insufficient','unsupported','failed_terminal','superseded','revoked')),
  input_hash text,
  source_key text NOT NULL DEFAULT 'unknown',
  fresh boolean NOT NULL DEFAULT true,
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0 AND attempts <= 5),
  lease_token uuid,
  lease_until timestamptz,
  retry_at timestamptz NOT NULL DEFAULT now(),
  deadline timestamptz NOT NULL DEFAULT now() + interval '24 hours',
  failure_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(article_id, semantic_revision, eligibility_generation, recipe_id, stage),
  CHECK ((state = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS s3_jobs_due ON public.article_understanding_jobs(fresh, retry_at, id)
  WHERE state IN ('pending','retry_wait','running');
CREATE TABLE IF NOT EXISTS public.article_understanding_results (
  id bigserial PRIMARY KEY,
  article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
  semantic_revision bigint NOT NULL,
  eligibility_generation bigint NOT NULL,
  recipe_id text NOT NULL REFERENCES public.understanding_recipes(id),
  stage text NOT NULL CHECK(stage IN ('facets','embedding')),
  input_hash text NOT NULL,
  evidence_manifest jsonb NOT NULL,
  payload jsonb NOT NULL,
  embedding vector(1536),
  provider_request_id text,
  usage_usd numeric(16,8) NOT NULL DEFAULT 0 CHECK(usage_usd >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(article_id,semantic_revision,eligibility_generation,recipe_id,stage),
  UNIQUE(id,article_id),
  CHECK ((stage = 'embedding') = (embedding IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS s3_results_lookup ON public.article_understanding_results
  (article_id,recipe_id,semantic_revision,eligibility_generation);
-- HNSW is built separately CONCURRENTLY by the migration command, outside this transaction.
CREATE TABLE IF NOT EXISTS public.story_clusters (
  id uuid PRIMARY KEY,
  recipe_id text NOT NULL REFERENCES public.understanding_recipes(id),
  version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.story_memberships (
  article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
  recipe_id text NOT NULL REFERENCES public.understanding_recipes(id),
  cluster_id uuid NOT NULL REFERENCES public.story_clusters(id),
  semantic_revision bigint NOT NULL,
  eligibility_generation bigint NOT NULL,
  input_hash text NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  reason text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(article_id,recipe_id)
);
CREATE INDEX IF NOT EXISTS s3_cluster_members ON public.story_memberships(cluster_id);
CREATE TABLE IF NOT EXISTS public.story_membership_events (
  id bigserial PRIMARY KEY,
  article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
  recipe_id text NOT NULL REFERENCES public.understanding_recipes(id),
  previous_cluster uuid,
  cluster_id uuid NOT NULL,
  version bigint NOT NULL,
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.understanding_outbox (
  id bigserial PRIMARY KEY,
  article_id uuid NOT NULL,
  semantic_revision bigint NOT NULL,
  eligibility_generation bigint NOT NULL,
  recipe_id text,
  kind text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.understanding_consumer_cursors (
  consumer text PRIMARY KEY,
  last_id bigint NOT NULL DEFAULT 0 CHECK(last_id >= 0)
);
-- Sequence IDs are not commit order. Per-event receipts prevent a late commit
-- with a smaller ID from being lost behind an acknowledged high-water cursor.
CREATE TABLE IF NOT EXISTS public.understanding_event_receipts (
  consumer text NOT NULL,
  event_id bigint NOT NULL REFERENCES public.understanding_outbox(id) ON DELETE CASCADE,
  acknowledged_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(consumer,event_id)
);
CREATE TABLE IF NOT EXISTS public.understanding_spend (
  id uuid PRIMARY KEY,
  -- No article/body/request data: accounting survives article deletion.
  job_id bigint NOT NULL,
  attempt integer NOT NULL,
  day date NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')::date,
  reserved_usd numeric(16,8) NOT NULL CHECK(reserved_usd > 0),
  actual_usd numeric(16,8) CHECK(actual_usd >= 0),
  settled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,attempt)
);
CREATE INDEX IF NOT EXISTS s3_spend_day ON public.understanding_spend(day);

CREATE OR REPLACE FUNCTION public.s3_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE before_input jsonb; after_input jsonb;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    before_input := jsonb_build_array(OLD.title,OLD.summary,OLD.url,OLD.source_name,
      OLD.author,OLD.published_at,OLD.analysis_content_artifact_id,OLD.analysis_content_version,
      OLD.analysis_text,to_jsonb(OLD)->'language',OLD.canonical_source_domain,
      to_jsonb(OLD)->'source_id',to_jsonb(OLD)->'source_acquisition_url',
      to_jsonb(OLD)->'source_acquisition_kind',to_jsonb(OLD)->'entity_candidates',
      to_jsonb(OLD)->'place_candidates',to_jsonb(OLD)->'analysis_allowed');
    after_input := jsonb_build_array(NEW.title,NEW.summary,NEW.url,NEW.source_name,
      NEW.author,NEW.published_at,NEW.analysis_content_artifact_id,NEW.analysis_content_version,
      NEW.analysis_text,to_jsonb(NEW)->'language',NEW.canonical_source_domain,
      to_jsonb(NEW)->'source_id',to_jsonb(NEW)->'source_acquisition_url',
      to_jsonb(NEW)->'source_acquisition_kind',to_jsonb(NEW)->'entity_candidates',
      to_jsonb(NEW)->'place_candidates',to_jsonb(NEW)->'analysis_allowed');
    NEW.semantic_revision := OLD.semantic_revision + CASE WHEN before_input IS DISTINCT FROM after_input THEN 1 ELSE 0 END;
    NEW.analysis_eligibility_generation := OLD.analysis_eligibility_generation +
      CASE WHEN NEW.analysis_revoked IS DISTINCT FROM OLD.analysis_revoked
        OR NEW.analysis_eligibility_generation IS DISTINCT FROM OLD.analysis_eligibility_generation THEN 1 ELSE 0 END;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.s3_schedule_article() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    INSERT INTO public.understanding_outbox(article_id,semantic_revision,eligibility_generation,kind)
      VALUES(OLD.id,OLD.semantic_revision,OLD.analysis_eligibility_generation,'deleted');
    RETURN OLD;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.semantic_revision = OLD.semantic_revision
       AND NEW.analysis_eligibility_generation = OLD.analysis_eligibility_generation THEN RETURN NEW; END IF;
  END IF;
  UPDATE public.article_understanding_jobs SET state='superseded',lease_token=NULL,lease_until=NULL,
    updated_at=now() WHERE article_id=NEW.id AND state IN ('pending','retry_wait','running');
  INSERT INTO public.understanding_outbox(article_id,semantic_revision,eligibility_generation,kind)
    VALUES(NEW.id,NEW.semantic_revision,NEW.analysis_eligibility_generation,
      CASE WHEN NEW.analysis_revoked THEN 'revoked' ELSE 'invalidated' END);
  IF NOT NEW.analysis_revoked THEN
    INSERT INTO public.article_understanding_jobs(article_id,semantic_revision,eligibility_generation,
      recipe_id,stage,source_key,fresh)
    SELECT NEW.id,NEW.semantic_revision,NEW.analysis_eligibility_generation,r.id,s.stage,
      COALESCE(NEW.canonical_source_domain,NEW.source_name,'unknown'),
      COALESCE(NEW.ingested_at,now()) > now()-interval '1 day'
    FROM public.understanding_recipes r CROSS JOIN (VALUES('facets'),('embedding')) s(stage)
    WHERE r.enabled ON CONFLICT DO NOTHING;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS s3_revision_guard ON public.articles;
CREATE TRIGGER s3_revision_guard BEFORE UPDATE ON public.articles
  FOR EACH ROW EXECUTE FUNCTION public.s3_revision_guard();
DROP TRIGGER IF EXISTS s3_schedule_article ON public.articles;
CREATE TRIGGER s3_schedule_article AFTER INSERT OR UPDATE OR DELETE ON public.articles
  FOR EACH ROW EXECUTE FUNCTION public.s3_schedule_article();

CREATE OR REPLACE VIEW public.article_understanding_current AS
SELECT a.id AS article_id,a.semantic_revision,a.analysis_eligibility_generation,
  r.recipe_id,r.stage,r.id AS result_id,r.input_hash,r.evidence_manifest,r.payload,r.embedding
FROM public.articles a JOIN public.article_understanding_results r ON r.article_id=a.id
JOIN public.understanding_recipes recipe ON recipe.id=r.recipe_id AND recipe.enabled
WHERE NOT a.analysis_revoked AND r.semantic_revision=a.semantic_revision
  AND r.eligibility_generation=a.analysis_eligibility_generation;
