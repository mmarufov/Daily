-- S5 additive reader authority. Install after core user/preferences tables.
CREATE TABLE IF NOT EXISTS public.reader_profiles (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    schema_version integer NOT NULL DEFAULT 3 CHECK(schema_version = 3),
    revision bigint NOT NULL DEFAULT 1 CHECK(revision > 0),
    learning_revision bigint NOT NULL DEFAULT 1 CHECK(learning_revision > 0),
    generation bigint NOT NULL DEFAULT 1 CHECK(generation > 0),
    profile jsonb NOT NULL,
    projections jsonb NOT NULL,
    migration_status text NOT NULL CHECK(migration_status IN ('ready','needs_review')),
    migration_evidence jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.reader_operations (
    user_id uuid NOT NULL REFERENCES public.reader_profiles(user_id) ON DELETE CASCADE,
    operation_id uuid NOT NULL,
    request_hash text NOT NULL,
    kind text NOT NULL CHECK(kind IN ('patch','reset_learning')),
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, operation_id)
);
CREATE TABLE IF NOT EXISTS public.reader_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.reader_profiles(user_id) ON DELETE CASCADE,
    generation bigint NOT NULL,
    revision bigint NOT NULL,
    kind text NOT NULL CHECK(kind IN ('embeddings','source_reconcile')),
    payload jsonb NOT NULL DEFAULT '{}',
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','completed','failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(user_id,generation,revision,kind)
);
CREATE INDEX IF NOT EXISTS reader_jobs_pending ON public.reader_jobs(kind,created_at) WHERE state='pending';
