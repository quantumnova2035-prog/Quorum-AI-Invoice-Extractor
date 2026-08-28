-- Run this once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query).

create extension if not exists "pgcrypto";

create table if not exists documents (
    id                  uuid primary key default gen_random_uuid(),
    created_at          timestamptz not null default now(),
    filename            text not null,
    source              text,                 -- text_pdf | ocr_image
    provider            text,                 -- which LLM answered
    overall_confidence  numeric,
    auto_accept_rate    numeric,
    fields              jsonb not null default '[]'::jsonb,
    line_items          jsonb not null default '[]'::jsonb,
    warnings            jsonb not null default '[]'::jsonb,
    raw_text_preview    text,
    -- Phase breakdown + per-LLM-call latency. See schemas.Timing.
    timing              jsonb not null default '{}'::jsonb,
    -- Token counts + per-pass cost. See schemas.Cost.
    cost                jsonb not null default '{}'::jsonb,
    -- Denormalised out of `timing` / `cost` purely so the History list can sort
    -- and aggregate on them without unpacking the JSON for every row.
    -- cost_usd is NULL (not 0) when a provider did not report a price: unknown
    -- and free must stay distinguishable, or a paid model can hide as a zero.
    total_ms            numeric,
    cost_usd            numeric
);

-- Migration for databases created before timing was added. Safe to re-run.
alter table documents add column if not exists timing   jsonb not null default '{}'::jsonb;
alter table documents add column if not exists total_ms numeric;
alter table documents add column if not exists cost     jsonb not null default '{}'::jsonb;
alter table documents add column if not exists cost_usd numeric;

create table if not exists corrections (
    id                  uuid primary key default gen_random_uuid(),
    created_at          timestamptz not null default now(),
    document_id         uuid references documents(id) on delete cascade,
    field_name          text not null,
    original_value      text,
    corrected_value     text,
    original_confidence numeric
);

create index if not exists documents_created_at_idx   on documents (created_at desc);
create index if not exists corrections_field_idx      on corrections (field_name);
create index if not exists corrections_document_idx   on corrections (document_id);

-- RLS is on by default in Supabase. The backend uses the service role key, which
-- bypasses RLS, so no policies are needed for this app. Enabling RLS with no
-- policies is the safe default: nothing is reachable from the browser with the
-- anon key.
alter table documents   enable row level security;
alter table corrections enable row level security;
