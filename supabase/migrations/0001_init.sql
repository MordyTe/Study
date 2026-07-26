-- Bybit Pattern Scanner — initial schema
-- Run this in Supabase → SQL Editor after creating a project.
-- Analysis-only application: no order, position, or credential tables exist by design.

create table if not exists app_settings (
  id          text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);

create table if not exists opportunities (
  id              text primary key,
  fingerprint     text not null unique,
  instrument_id   text not null,
  category        text not null check (category in ('spot', 'linear')),
  symbol          text not null,
  timeframe       text not null,
  detector_name   text not null,
  direction       text not null check (direction in ('long', 'short')),
  status          text not null,
  score           numeric not null,
  reward_to_risk  numeric,
  detected_at     timestamptz not null,
  updated_at      timestamptz not null default now(),
  -- Full immutable evidence bundle (overlays, score components, verification record).
  payload         jsonb not null
);

create index if not exists opportunities_detected_at_idx on opportunities (detected_at desc);
create index if not exists opportunities_status_idx      on opportunities (status);
create index if not exists opportunities_symbol_idx      on opportunities (symbol);
create index if not exists opportunities_score_idx       on opportunities (score desc);
create index if not exists opportunities_category_idx    on opportunities (category);

create table if not exists scan_runs (
  id                    text primary key,
  started_at            timestamptz not null,
  finished_at           timestamptz not null,
  instruments_scanned   integer not null default 0,
  candidates_evaluated  integer not null default 0,
  confirmed             integer not null default 0,
  forming               integer not null default 0,
  alerts_sent           integer not null default 0,
  duration_ms           integer not null default 0,
  errors                jsonb not null default '[]'::jsonb
);

create index if not exists scan_runs_started_at_idx on scan_runs (started_at desc);

create table if not exists alert_deliveries (
  id               text primary key,
  opportunity_id   text not null,
  idempotency_key  text not null,
  channel          text not null default 'telegram',
  status           text not null check (status in ('sent', 'failed', 'skipped')),
  detail           text,
  created_at       timestamptz not null default now()
);

create unique index if not exists alert_deliveries_idem_idx on alert_deliveries (idempotency_key);
create index if not exists alert_deliveries_created_idx     on alert_deliveries (created_at desc);

create table if not exists data_quality_events (
  id           bigserial primary key,
  instrument_id text not null,
  timeframe    text not null,
  severity     text not null,
  message      text not null,
  created_at   timestamptz not null default now()
);

create index if not exists data_quality_created_idx on data_quality_events (created_at desc);

-- ── Row Level Security ────────────────────────────────────────────────────
-- The server writes with the service-role key (which bypasses RLS).
-- Anon clients get read-only access to analysis output only. No table here
-- contains credentials or personally identifying data.

alter table opportunities     enable row level security;
alter table scan_runs         enable row level security;
alter table alert_deliveries  enable row level security;
alter table app_settings      enable row level security;
alter table data_quality_events enable row level security;

drop policy if exists "public read opportunities" on opportunities;
create policy "public read opportunities" on opportunities for select using (true);

drop policy if exists "public read scans" on scan_runs;
create policy "public read scans" on scan_runs for select using (true);

drop policy if exists "public read settings" on app_settings;
create policy "public read settings" on app_settings for select using (true);

drop policy if exists "public read data quality" on data_quality_events;
create policy "public read data quality" on data_quality_events for select using (true);

-- alert_deliveries has no public select policy: delivery metadata stays server-side.
