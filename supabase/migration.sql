create table if not exists execution_log (
    id bigint generated always as identity primary key,
    prompt text not null,
    response text,
    steps jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

-- This table holds a teenager's questionnaire answers, free-text health notes,
-- and full LLM prompts (including retrieved medical context). Without RLS,
-- PostgREST exposes all of it to anyone holding the anon/public API key, which
-- typically ships client-side. Restrict every operation to the service role.
alter table execution_log enable row level security;

-- Dropped first so this migration stays re-runnable, like the create table above.
drop policy if exists "service role only" on execution_log;

create policy "service role only" on execution_log
    for all
    using (auth.role() = 'service_role');

-- Because of the policy above, SUPABASE_KEY must be the service-role key and
-- must stay server-side only — the anon/public key cannot insert here.
