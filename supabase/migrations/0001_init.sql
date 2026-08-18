-- Durable persistence for the scheduled-data edge system.
--
-- Design: indexed columns for querying, plus a full JSONB payload for the
-- object itself. Reads select only the payload and cast, so schema evolution
-- costs nothing.
--
-- Calibration is the reason this table matters. Measuring whether the system's
-- probabilities beat the market requires months of resolved outcomes, which the
-- in-memory store cannot hold across a restart.

create table if not exists app_settings (
  id         text primary key,
  payload    jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists candidates (
  id               text primary key,
  fingerprint      text not null,
  market_id        text not null,
  status           text not null,
  fair_probability double precision,
  market_price     double precision,
  decision_at      bigint not null,
  payload          jsonb not null,
  updated_at       timestamptz not null default now()
);

create unique index if not exists candidates_fingerprint_idx on candidates (fingerprint);
create index if not exists candidates_decision_at_idx on candidates (decision_at desc);
create index if not exists candidates_status_idx on candidates (status);
create index if not exists candidates_market_idx on candidates (market_id);

create table if not exists scans (
  id          text primary key,
  started_at  bigint not null,
  finished_at bigint not null,
  payload     jsonb not null
);

create index if not exists scans_started_at_idx on scans (started_at desc);

-- Ground truth: what each market actually resolved to. Candidates can be
-- regenerated from a scan; this table cannot, which makes it the one dataset
-- whose durability actually matters for calibration.
create table if not exists resolutions (
  market_id    text primary key,
  resolved_yes boolean not null,
  resolved_at  bigint not null
);
