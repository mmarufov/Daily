-- Additive S5 embedding schema. Install explicitly AFTER reader_schema.sql/S3.
SELECT pg_advisory_xact_lock(731205002);
CREATE TABLE IF NOT EXISTS public.reader_embedding_control (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  enabled boolean NOT NULL DEFAULT false,
  daily_global_tokens bigint NOT NULL DEFAULT 0 CHECK(daily_global_tokens >= 0),
  daily_user_tokens bigint NOT NULL DEFAULT 0 CHECK(daily_user_tokens >= 0)
);
INSERT INTO public.reader_embedding_control(singleton) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.reader_intent_embeddings (
  user_id uuid NOT NULL REFERENCES public.reader_profiles(user_id) ON DELETE CASCADE,
  generation bigint NOT NULL CHECK(generation >= 1),
  intent_id uuid NOT NULL,
  semantic_hash text NOT NULL,
  space_id text NOT NULL,
  embedding vector(1536) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(user_id,generation,intent_id,semantic_hash,space_id)
);
CREATE TABLE IF NOT EXISTS public.reader_embedding_jobs (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.reader_profiles(user_id) ON DELETE CASCADE,
  generation bigint NOT NULL CHECK(generation >= 1),
  intent_id uuid NOT NULL,
  semantic_hash text NOT NULL,
  space_id text NOT NULL,
  recipe_id text NOT NULL REFERENCES public.understanding_recipes(id),
  state text NOT NULL DEFAULT 'pending' CHECK(state IN
    ('pending','running','retry_wait','ready','superseded','failed')),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
  lease_token uuid,
  lease_until timestamptz,
  retry_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  failure_code text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(user_id,generation,intent_id,semantic_hash,space_id),
  CHECK((state='running')=(lease_token IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS reader_embedding_jobs_due ON public.reader_embedding_jobs(retry_at,id)
  WHERE state IN ('pending','retry_wait','running');
-- Conservative token reservations survive ambiguous provider outcomes. The global
-- aggregate contains no reader identifier and survives account deletion.
CREATE TABLE IF NOT EXISTS public.reader_embedding_global_spend (
  day date PRIMARY KEY,
  reserved_tokens bigint NOT NULL DEFAULT 0 CHECK(reserved_tokens >= 0)
);
CREATE TABLE IF NOT EXISTS public.reader_embedding_user_spend (
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  day date NOT NULL,
  reserved_tokens bigint NOT NULL DEFAULT 0 CHECK(reserved_tokens >= 0),
  PRIMARY KEY(user_id,day)
);
