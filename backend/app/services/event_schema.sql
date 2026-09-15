-- Explicit additive S4 migration; never run by an API request/startup.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(731204001);
ALTER TABLE public.understanding_control ADD COLUMN IF NOT EXISTS serving_generation bigint NOT NULL DEFAULT 1;
ALTER TABLE public.understanding_recipes ADD COLUMN IF NOT EXISTS serving_generation bigint NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS public.event_schema_version (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), version integer NOT NULL CHECK(version=1)
);
INSERT INTO public.event_schema_version VALUES(true,1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.event_upstream_notices (
  id bigserial PRIMARY KEY, kind text NOT NULL, identity text NOT NULL,
  generation bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- No trigger locks a control, article, event or job owned by another system.
CREATE OR REPLACE FUNCTION public.s4_s3_generation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.serving_generation := OLD.serving_generation + 1;
  IF TG_TABLE_NAME = 'understanding_recipes' THEN
    IF NOT NEW.enabled THEN NEW.approved := false; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.s4_s3_notice() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO public.event_upstream_notices(kind,identity,generation)
  VALUES(TG_TABLE_NAME,COALESCE(to_jsonb(NEW)->>'id','control'),NEW.serving_generation);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS s4_s3_generation ON public.understanding_control;
CREATE TRIGGER s4_s3_generation BEFORE UPDATE ON public.understanding_control
  FOR EACH ROW EXECUTE FUNCTION public.s4_s3_generation();
DROP TRIGGER IF EXISTS s4_s3_notice ON public.understanding_control;
CREATE TRIGGER s4_s3_notice AFTER UPDATE ON public.understanding_control
  FOR EACH ROW EXECUTE FUNCTION public.s4_s3_notice();
DROP TRIGGER IF EXISTS s4_s3_generation ON public.understanding_recipes;
CREATE TRIGGER s4_s3_generation BEFORE UPDATE ON public.understanding_recipes
  FOR EACH ROW EXECUTE FUNCTION public.s4_s3_generation();
DROP TRIGGER IF EXISTS s4_s3_notice ON public.understanding_recipes;
CREATE TRIGGER s4_s3_notice AFTER UPDATE ON public.understanding_recipes
  FOR EACH ROW EXECUTE FUNCTION public.s4_s3_notice();

CREATE TABLE IF NOT EXISTS public.event_recipes (
  id text PRIMARY KEY, definition jsonb NOT NULL, enabled boolean NOT NULL DEFAULT false,
  approved boolean NOT NULL DEFAULT false, evaluation jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS public.event_control (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), generation bigint NOT NULL DEFAULT 1 CHECK(generation>0),
  submissions_enabled boolean NOT NULL DEFAULT false, delivery_enabled boolean NOT NULL DEFAULT false,
  serving_recipe text REFERENCES public.event_recipes(id),
  daily_budget_usd numeric(16,8) NOT NULL DEFAULT 0 CHECK(daily_budget_usd>=0),
  monthly_budget_usd numeric(16,8) NOT NULL DEFAULT 0 CHECK(monthly_budget_usd>=0),
  circuit_until timestamptz, circuit_reason text,
  coverage_observed_through timestamptz, coverage_verified boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK(NOT submissions_enabled OR (daily_budget_usd>0 AND monthly_budget_usd>=daily_budget_usd)),
  CHECK(NOT delivery_enabled OR serving_recipe IS NOT NULL)
);
INSERT INTO public.event_control(singleton) VALUES(true) ON CONFLICT DO NOTHING;
-- Provenance is per article/acquisition, not inferred from publisher ownership.
CREATE TABLE IF NOT EXISTS public.event_source_registry (
  id text PRIMARY KEY, article_id uuid NOT NULL UNIQUE,
  generation bigint NOT NULL DEFAULT 1 CHECK(generation>0), source_domain text NOT NULL,
  metadata jsonb NOT NULL, reviewed_by text, updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS public.events (
  id uuid PRIMARY KEY, recipe_id text NOT NULL REFERENCES public.event_recipes(id), seed_key text NOT NULL,
  generation bigint NOT NULL DEFAULT 1 CHECK(generation>0), member_generation bigint NOT NULL DEFAULT 1 CHECK(member_generation>0),
  lifecycle text NOT NULL DEFAULT 'candidate' CHECK(lifecycle IN ('candidate','active','inactive','withdrawn','merged')),
  redirect_id uuid REFERENCES public.events(id), current_assessment uuid, input_generation text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(recipe_id,seed_key), CHECK(redirect_id IS NULL OR redirect_id<>id)
);
CREATE TABLE IF NOT EXISTS public.event_developments (
  id uuid PRIMARY KEY, event_id uuid NOT NULL REFERENCES public.events(id), version bigint NOT NULL DEFAULT 1 CHECK(version>0),
  fingerprint text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(event_id,fingerprint)
);
CREATE TABLE IF NOT EXISTS public.development_versions (
  development_id uuid NOT NULL REFERENCES public.event_developments(id), version bigint NOT NULL CHECK(version>0),
  claim_hash text NOT NULL, change_kind text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(development_id,version)
);
-- Version-specific equivalence preserves explicit read acknowledgments across
-- exact-development merges without suppressing a later correction/version.
CREATE TABLE IF NOT EXISTS public.event_development_aliases (
  development_id uuid NOT NULL, version bigint NOT NULL,
  target_id uuid NOT NULL, target_version bigint NOT NULL,
  PRIMARY KEY(development_id,version),
  FOREIGN KEY(development_id,version) REFERENCES public.development_versions(development_id,version),
  FOREIGN KEY(target_id,target_version) REFERENCES public.development_versions(development_id,version),
  CHECK(development_id<>target_id)
);
CREATE TABLE IF NOT EXISTS public.event_evidence (
  event_id uuid NOT NULL REFERENCES public.events(id), evidence_id text NOT NULL,
  development_id uuid NOT NULL REFERENCES public.event_developments(id),
  article_id uuid NOT NULL, dependency jsonb NOT NULL, payload jsonb,
  active boolean NOT NULL DEFAULT true, refined boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(event_id,evidence_id)
);
-- No article/result FK: content-free reverse links survive deletion/cascades upstream.
CREATE INDEX IF NOT EXISTS s4_evidence_article ON public.event_evidence(article_id,event_id);
CREATE INDEX IF NOT EXISTS s4_evidence_current ON public.event_evidence(event_id) WHERE active;
CREATE TABLE IF NOT EXISTS public.event_refinements (
  event_id uuid NOT NULL REFERENCES public.events(id), evidence_id text NOT NULL, input_hash text NOT NULL,
  recipe_id text NOT NULL REFERENCES public.event_recipes(id), payload jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(event_id,evidence_id,input_hash,recipe_id)
);
CREATE TABLE IF NOT EXISTS public.event_snapshots (
  id text PRIMARY KEY, event_id uuid NOT NULL REFERENCES public.events(id), generation bigint NOT NULL,
  payload jsonb, dependency_digest text NOT NULL, dependency_count integer NOT NULL CHECK(dependency_count>=0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS s4_snapshots_event ON public.event_snapshots(event_id,generation);
CREATE TABLE IF NOT EXISTS public.event_assessments (
  id uuid PRIMARY KEY, event_id uuid NOT NULL REFERENCES public.events(id), snapshot_id text NOT NULL REFERENCES public.event_snapshots(id),
  recipe_id text NOT NULL REFERENCES public.event_recipes(id), generation bigint NOT NULL,
  payload jsonb NOT NULL, valid_until timestamptz, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(snapshot_id,recipe_id)
);
CREATE TABLE IF NOT EXISTS public.event_jobs (
  id bigserial PRIMARY KEY, recipe_id text NOT NULL REFERENCES public.event_recipes(id),
  stage text NOT NULL CHECK(stage IN ('ingest','refine','group','assess')),
  subject_id uuid NOT NULL, revision text NOT NULL,
  state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','retry_wait','ready','insufficient','unsupported','failed_terminal','superseded','quarantined')),
  source_key text NOT NULL DEFAULT 'unknown', attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
  lease_token uuid, lease_until timestamptz, input_hash text, snapshot_id text REFERENCES public.event_snapshots(id),
  retry_at timestamptz NOT NULL DEFAULT clock_timestamp(), deadline timestamptz NOT NULL DEFAULT clock_timestamp()+interval '24 hours',
  failure_reason text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(recipe_id,stage,subject_id,revision),
  CHECK((state='running')=(lease_token IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS s4_jobs_due ON public.event_jobs(retry_at,id) WHERE state IN ('pending','retry_wait','running');
CREATE TABLE IF NOT EXISTS public.event_changes (
  id bigserial PRIMARY KEY, event_id uuid NOT NULL REFERENCES public.events(id), generation bigint NOT NULL,
  kind text NOT NULL, details jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS public.event_outbox (
  id bigserial PRIMARY KEY, event_id uuid NOT NULL, generation bigint NOT NULL, kind text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS public.event_inbox_receipts (
  stream text NOT NULL, event_id bigint NOT NULL, acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(stream,event_id)
);
CREATE TABLE IF NOT EXISTS public.event_scan_state (
  name text PRIMARY KEY, after_id uuid, updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS public.event_spend (
  id uuid PRIMARY KEY, job_id bigint NOT NULL, attempt integer NOT NULL, stage text NOT NULL,
  request_hash text NOT NULL, day date NOT NULL DEFAULT (clock_timestamp() AT TIME ZONE 'UTC')::date,
  reserved_usd numeric(16,8) NOT NULL CHECK(reserved_usd>0), actual_usd numeric(16,8) CHECK(actual_usd>=0),
  settled boolean NOT NULL DEFAULT false, request_id text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(job_id,attempt)
);
CREATE INDEX IF NOT EXISTS s4_spend_day ON public.event_spend(day);
-- Content-free delivery attribution. A response is NOT a read acknowledgment.
-- Suppression requires a later explicit user reading event bound to this tuple.
CREATE TABLE IF NOT EXISTS public.event_delivery_receipts (
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  feed_request_id uuid NOT NULL, article_id uuid NOT NULL,
  event_id uuid NOT NULL, development_id uuid NOT NULL, development_version bigint NOT NULL CHECK(development_version>0),
  assessment_id uuid NOT NULL, valid_until timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(user_id,feed_request_id,article_id)
);
CREATE INDEX IF NOT EXISTS s4_deliveries_reader ON public.event_delivery_receipts(user_id,created_at);
