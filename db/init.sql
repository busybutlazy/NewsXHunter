CREATE SCHEMA IF NOT EXISTS edge_ingest;

-- RSS 來源清單
CREATE TABLE IF NOT EXISTS edge_ingest.sources (
  id          SERIAL PRIMARY KEY,
  source_key  TEXT NOT NULL UNIQUE,         -- e.g. sciencedaily, arxiv, bbc
  name        TEXT NOT NULL,
  feed_url    TEXT NOT NULL UNIQUE,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 收集到的原始項目（canonical RawItem）
CREATE TABLE IF NOT EXISTS edge_ingest.raw_items (
  id           BIGSERIAL PRIMARY KEY,

  item_id      TEXT NOT NULL UNIQUE,         -- source_key:sha256:<dedup_key>
  source_id    INT  NOT NULL REFERENCES edge_ingest.sources(id),
  source_key   TEXT NOT NULL,

  url          TEXT NOT NULL,
  title        TEXT NOT NULL,
  summary      TEXT,
  published_at TIMESTAMPTZ,
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  lang         TEXT NOT NULL DEFAULT 'en',

  dedup_key    TEXT NOT NULL UNIQUE,         -- sha256 hex

  rights       JSONB NOT NULL DEFAULT '{"store_fulltext": false, "mode": "rss_summary_link_only"}'::jsonb,
  raw          JSONB NOT NULL DEFAULT '{}'::jsonb,

  status       TEXT NOT NULL DEFAULT 'RAW'   -- 先保留，M2 用得上
);

CREATE INDEX IF NOT EXISTS idx_raw_items_published_at ON edge_ingest.raw_items (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_items_source_id ON edge_ingest.raw_items (source_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_status ON edge_ingest.raw_items (status);
