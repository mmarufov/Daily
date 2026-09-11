-- S7-owned state. Installation never enables serving or provider work.
CREATE TABLE IF NOT EXISTS public.ranking_control (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  epoch bigint NOT NULL DEFAULT 1 CHECK(epoch > 0),
  recipe jsonb NOT NULL DEFAULT '{}'::jsonb,
  recipe_hash text NOT NULL DEFAULT '',
  approved boolean NOT NULL DEFAULT false,
  serving boolean NOT NULL DEFAULT false,
  provider boolean NOT NULL DEFAULT false,
  daily_usd numeric(20,8) NOT NULL DEFAULT 0 CHECK(daily_usd >= 0),
  account_daily_usd numeric(20,8) NOT NULL DEFAULT 0 CHECK(account_daily_usd >= 0),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO public.ranking_control(singleton) VALUES(true) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ranking_builds (
  user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  build_id uuid NOT NULL UNIQUE,
  token uuid NOT NULL,
  epoch bigint NOT NULL,
  recipe_hash text NOT NULL,
  identity jsonb NOT NULL,
  identity_hash text NOT NULL,
  expires_at timestamptz NOT NULL,
  published boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS public.ranking_results (
  user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  build_id uuid NOT NULL,
  epoch bigint NOT NULL,
  recipe_hash text NOT NULL,
  identity jsonb NOT NULL,
  identity_hash text NOT NULL,
  envelope jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- S9 publication order survives result expiry, reader reset and maintenance.
-- The counter is advanced only inside the successful publication transaction.
CREATE TABLE IF NOT EXISTS public.ranking_publication_counters (
  user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  sequence bigint NOT NULL CHECK(sequence BETWEEN 1 AND 9007199254740991)
);
ALTER TABLE public.ranking_results ADD COLUMN IF NOT EXISTS publication_sequence bigint
  CHECK(publication_sequence BETWEEN 1 AND 9007199254740991);
-- Global totals survive account deletion. Account-specific counters are removed
-- by the delete trigger; the opaque reservation rows have a cascading user FK.
CREATE TABLE IF NOT EXISTS public.ranking_budget (
  day date NOT NULL,
  account text NOT NULL,
  committed_usd numeric(20,8) NOT NULL CHECK(committed_usd >= 0),
  PRIMARY KEY(day,account)
);
CREATE TABLE IF NOT EXISTS public.ranking_reservations (
  reservation_id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  build_id uuid NOT NULL,
  attempt smallint NOT NULL CHECK(attempt BETWEEN 1 AND 6),
  day date NOT NULL,
  reserved_usd numeric(20,8) NOT NULL CHECK(reserved_usd > 0),
  actual_usd numeric(20,8) CHECK(actual_usd >= 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(build_id,attempt)
);
CREATE INDEX IF NOT EXISTS ranking_reservations_created ON public.ranking_reservations(created_at);
CREATE OR REPLACE FUNCTION public.ranking_account_deleted() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  DELETE FROM public.ranking_budget WHERE account=OLD.id::text;
  RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS ranking_account_deleted ON public.users;
CREATE TRIGGER ranking_account_deleted AFTER DELETE ON public.users
FOR EACH ROW EXECUTE FUNCTION public.ranking_account_deleted();
