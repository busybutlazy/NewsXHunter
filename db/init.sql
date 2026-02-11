CREATE SCHEMA IF NOT EXISTS edge_ingest;

CREATE TABLE IF NOT EXISTS edge_ingest.sources (
  id          SERIAL PRIMARY KEY,
  source_key  TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  feed_url    TEXT NOT NULL UNIQUE,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS edge_ingest.raw_items (
  id           BIGSERIAL PRIMARY KEY,

  item_id      TEXT NOT NULL UNIQUE,
  source_id    INT  NOT NULL REFERENCES edge_ingest.sources(id),
  source_key   TEXT NOT NULL,

  url          TEXT NOT NULL,
  title        TEXT NOT NULL,
  summary      TEXT,
  creator      TEXT,
  published_at TIMESTAMPTZ,
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  lang         TEXT NOT NULL DEFAULT 'en',

  dedup_key    TEXT NOT NULL UNIQUE,

  -- 對應 Python 端：rights 已統一為 str，因此在 DB 端設為 TEXT NOT NULL 並給空字串預設值
  rights       TEXT NOT NULL DEFAULT '',
  -- 對應 Python 端：raw 為 dict，實際以 Jsonb(...) 寫入 JSONB 欄位
  raw          JSONB NOT NULL DEFAULT '{}'::jsonb,

  status       TEXT NOT NULL DEFAULT 'RAW'
);

CREATE TABLE IF NOT EXISTS edge_ingest.item_translations (
  id                BIGSERIAL PRIMARY KEY,
  raw_item_id       BIGINT NOT NULL
    REFERENCES edge_ingest.raw_items(id) ON DELETE CASCADE,
  target_lang       TEXT NOT NULL,
  translated_title   TEXT,
  translated_summary TEXT,
  translated_content TEXT,
  engine_provider    TEXT,
  model              TEXT NOT NULL DEFAULT '',
  prompt_version     TEXT NOT NULL DEFAULT '',
  source_text_hash   TEXT NOT NULL DEFAULT '',
  status             TEXT NOT NULL DEFAULT 'QUEUED',
  error_message      TEXT,
  meta               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_item_translations_status
    CHECK (status IN ('QUEUED','PROCESSING','DONE','FAILED')),
  CONSTRAINT chk_item_translations_hash
    CHECK (
      source_text_hash = ''
      OR source_text_hash ~ '^[0-9a-f]{64}$'
    )
);

-- 0) 確保 schema 存在
CREATE SCHEMA IF NOT EXISTS edge_ingest;

-- 1) 建議用 ENUM 來限制狀態值（成功/錯誤）- 放在 edge_ingest schema 下
DO $$
BEGIN
  IF to_regtype('edge_ingest.n8n_run_status') IS NULL THEN
    CREATE TYPE edge_ingest.n8n_run_status AS ENUM ('success', 'error');
  END IF;
END$$;

-- 2) 任務執行紀錄表 - 放在 edge_ingest schema 下
CREATE TABLE IF NOT EXISTS edge_ingest.n8n_workflow_run_log (
  id              BIGSERIAL PRIMARY KEY,

  -- n8n 的 workflow / execution 識別資訊
  workflow_id     TEXT NULL,
  workflow_name   TEXT NULL,
  execution_id    TEXT NOT NULL,               -- 建議用 $execution.id 寫入
  trigger         TEXT NULL,                   -- cron/webhook/manual...（可選）

  -- 成功/錯誤狀態（你要的快速 query 欄位）
  status          edge_ingest.n8n_run_status NOT NULL,

  -- 時間資訊
  started_at      TIMESTAMPTZ NULL,
  ended_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  duration_ms     INTEGER NULL CHECK (duration_ms IS NULL OR duration_ms >= 0),

  -- 資料量（可用於統計）
  items_in        INTEGER NULL CHECK (items_in IS NULL OR items_in >= 0),
  items_out       INTEGER NULL CHECK (items_out IS NULL OR items_out >= 0),

  -- 錯誤資訊（成功時通常為 NULL）
  error_code      TEXT NULL,
  error_message   TEXT NULL,
  error_stack     TEXT NULL,

  -- 彈性擴充欄位
  meta            JSONB NOT NULL DEFAULT '{}'::jsonb,

  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT uq_edge_ingest_n8n_runlog_execution UNIQUE (execution_id),

  CONSTRAINT ck_edge_ingest_n8n_runlog_error_fields
    CHECK (
      (status = 'success' AND error_message IS NULL)
      OR (status = 'error')
    )
);

-- 3) 索引（建在同一 schema 的 table 上）
CREATE INDEX IF NOT EXISTS idx_edge_ingest_n8n_runlog_status_endedat
  ON edge_ingest.n8n_workflow_run_log (status, ended_at DESC);

CREATE INDEX IF NOT EXISTS idx_edge_ingest_n8n_runlog_workflow_endedat
  ON edge_ingest.n8n_workflow_run_log (workflow_id, ended_at DESC);

CREATE INDEX IF NOT EXISTS idx_edge_ingest_n8n_runlog_createdat
  ON edge_ingest.n8n_workflow_run_log (created_at DESC);

-- 若你會查 meta 內部欄位再開（可選）
-- CREATE INDEX IF NOT EXISTS idx_edge_ingest_n8n_runlog_meta_gin
--   ON edge_ingest.n8n_workflow_run_log USING GIN (meta);




CREATE INDEX IF NOT EXISTS idx_raw_items_published_at ON edge_ingest.raw_items (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_items_source_id ON edge_ingest.raw_items (source_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_status ON edge_ingest.raw_items (status);
