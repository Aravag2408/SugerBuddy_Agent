create table if not exists execution_log (
    id bigint generated always as identity primary key,
    prompt text not null,
    response text,
    steps jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);
