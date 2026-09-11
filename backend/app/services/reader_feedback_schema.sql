CREATE TABLE IF NOT EXISTS public.reader_delivery_receipts (
 user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
 feed_request_id uuid NOT NULL,
 article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
 generation bigint NOT NULL, revision bigint NOT NULL,
 article_revision text, intent_ids jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,feed_request_id,article_id)
);
CREATE INDEX IF NOT EXISTS reader_receipts_expiry ON public.reader_delivery_receipts(created_at);
-- Additive migration: old receipts/signals deliberately retain no semantic proof.
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS learning_revision bigint;
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS ranking_recipe text;
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS final_position integer;
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS evidence_stamp jsonb;
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS intent_semantic_hashes jsonb NOT NULL DEFAULT '{}'::jsonb;
CREATE TABLE IF NOT EXISTS public.reader_proposals (
 user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
 operation_id uuid NOT NULL, request_hash text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,operation_id)
);
CREATE TABLE IF NOT EXISTS public.reader_feedback_events (
 user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
 event_id uuid NOT NULL, generation bigint NOT NULL,
 request_hash text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,event_id)
);
CREATE TABLE IF NOT EXISTS public.reader_learned_signals (
 user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
 intent_id uuid NOT NULL, generation bigint NOT NULL,
 weight double precision NOT NULL CHECK(weight BETWEEN -1 AND 0.8),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,intent_id)
);
ALTER TABLE public.reader_learned_signals ADD COLUMN IF NOT EXISTS semantic_hash text;
-- S10 B2: versions the reward formula that produced this weight, independent
-- of the intent's own semantic_hash. Lets a future reward-recipe change be
-- told apart from a change in what the reader actually did when reading
-- historical reader_learned_signals rows.
ALTER TABLE public.reader_learned_signals ADD COLUMN IF NOT EXISTS reward_recipe_hash text;
ALTER TABLE public.reading_events ADD COLUMN IF NOT EXISTS client_event_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS reading_event_client_id ON public.reading_events(user_id,client_event_id)
 WHERE client_event_id IS NOT NULL;
