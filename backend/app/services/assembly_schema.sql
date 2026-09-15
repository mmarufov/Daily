-- S8-only additive state. Installation never approves or enables assembly.
CREATE TABLE IF NOT EXISTS public.assembly_control (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  epoch bigint NOT NULL DEFAULT 1 CHECK(epoch > 0),
  recipe jsonb NOT NULL DEFAULT '{}'::jsonb,
  recipe_hash text NOT NULL DEFAULT '',
  approved boolean NOT NULL DEFAULT false,
  serving boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO public.assembly_control(singleton) VALUES(true) ON CONFLICT DO NOTHING;

ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS assembly_recipe text;
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS coverage_key text;
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS novelty_key text;
ALTER TABLE public.reader_delivery_receipts ADD COLUMN IF NOT EXISTS assembly_content_hash text;
CREATE INDEX IF NOT EXISTS reader_receipts_novelty
  ON public.reader_delivery_receipts(user_id,generation,novelty_key,created_at)
  WHERE novelty_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.reader_edition_state (
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  generation bigint NOT NULL,
  revision bigint NOT NULL DEFAULT 0 CHECK(revision >= 0),
  PRIMARY KEY(user_id,generation)
);
-- One acknowledged content snapshot, not one delivery or one impression. The
-- receipt FK keeps attribution removable with reset/retention/account deletion.
CREATE TABLE IF NOT EXISTS public.reader_edition_reads (
  user_id uuid NOT NULL,
  generation bigint NOT NULL,
  novelty_key text NOT NULL,
  feed_request_id uuid NOT NULL,
  article_id uuid NOT NULL,
  client_event_id uuid NOT NULL,
  acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(user_id,generation,novelty_key),
  FOREIGN KEY(user_id,feed_request_id,article_id)
    REFERENCES public.reader_delivery_receipts(user_id,feed_request_id,article_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS reader_edition_reads_expiry
  ON public.reader_edition_reads(user_id,generation,acknowledged_at);

CREATE OR REPLACE FUNCTION public.assembly_reader_reset() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  IF NEW.generation IS DISTINCT FROM OLD.generation THEN
    DELETE FROM public.reader_edition_reads WHERE user_id=NEW.user_id;
    DELETE FROM public.reader_edition_state WHERE user_id=NEW.user_id;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS assembly_reader_reset ON public.reader_profiles;
CREATE TRIGGER assembly_reader_reset AFTER UPDATE OF generation ON public.reader_profiles
FOR EACH ROW EXECUTE FUNCTION public.assembly_reader_reset();
