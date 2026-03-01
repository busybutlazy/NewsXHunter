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

-- =========================================
-- Conversational Agents / LINE / QA / RAG
-- =========================================

DO $$
BEGIN
  IF to_regtype('edge_ingest.agent_name') IS NULL THEN
    CREATE TYPE edge_ingest.agent_name AS ENUM ('Bard', 'Lorekeeper');
  END IF;
END$$;

DO $$
BEGIN
  IF to_regtype('edge_ingest.delivery_status') IS NULL THEN
    CREATE TYPE edge_ingest.delivery_status AS ENUM ('PENDING', 'SENT', 'FAILED');
  END IF;
END$$;

DO $$
BEGIN
  IF to_regtype('edge_ingest.query_status') IS NULL THEN
    CREATE TYPE edge_ingest.query_status AS ENUM ('ANSWERED', 'REJECTED', 'FAILED');
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS edge_ingest.users (
  id                BIGSERIAL PRIMARY KEY,
  line_user_id      TEXT NOT NULL UNIQUE,
  display_name      TEXT,
  preferred_lang    TEXT NOT NULL DEFAULT 'zh-TW',
  timezone          TEXT NOT NULL DEFAULT 'Asia/Taipei',
  is_active         BOOLEAN NOT NULL DEFAULT TRUE,
  daily_question_limit INTEGER NOT NULL DEFAULT 5 CHECK (daily_question_limit > 0),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS edge_ingest.agent_runs (
  id                BIGSERIAL PRIMARY KEY,
  agent             edge_ingest.agent_name NOT NULL,
  user_id           BIGINT REFERENCES edge_ingest.users(id) ON DELETE SET NULL,
  raw_item_id       BIGINT REFERENCES edge_ingest.raw_items(id) ON DELETE SET NULL,
  query_id          BIGINT,
  provider          TEXT NOT NULL DEFAULT '',
  model             TEXT NOT NULL DEFAULT '',
  prompt_version    TEXT NOT NULL DEFAULT '',
  input_tokens      INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens     INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  total_tokens      INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
  latency_ms        INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
  status            TEXT NOT NULL DEFAULT 'DONE',
  error_message     TEXT,
  meta              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS edge_ingest.line_push_messages (
  id                BIGSERIAL PRIMARY KEY,
  user_id           BIGINT NOT NULL REFERENCES edge_ingest.users(id) ON DELETE CASCADE,
  raw_item_id       BIGINT REFERENCES edge_ingest.raw_items(id) ON DELETE SET NULL,
  translation_id    BIGINT REFERENCES edge_ingest.item_translations(id) ON DELETE SET NULL,
  agent_run_id      BIGINT REFERENCES edge_ingest.agent_runs(id) ON DELETE SET NULL,
  target_line_user_id TEXT NOT NULL,
  title             TEXT NOT NULL,
  message_body      TEXT NOT NULL,
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  status            edge_ingest.delivery_status NOT NULL DEFAULT 'PENDING',
  line_request_id   TEXT,
  error_message     TEXT,
  sent_at           TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS edge_ingest.user_daily_question_usage (
  id                BIGSERIAL PRIMARY KEY,
  user_id           BIGINT NOT NULL REFERENCES edge_ingest.users(id) ON DELETE CASCADE,
  usage_date        DATE NOT NULL,
  used_count        INTEGER NOT NULL DEFAULT 0 CHECK (used_count >= 0),
  limit_count       INTEGER NOT NULL DEFAULT 5 CHECK (limit_count > 0),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_user_daily_usage UNIQUE (user_id, usage_date)
);

CREATE TABLE IF NOT EXISTS edge_ingest.user_queries (
  id                BIGSERIAL PRIMARY KEY,
  user_id           BIGINT NOT NULL REFERENCES edge_ingest.users(id) ON DELETE CASCADE,
  question_text     TEXT NOT NULL,
  answer_text       TEXT,
  status            edge_ingest.query_status NOT NULL DEFAULT 'ANSWERED',
  rejected_reason   TEXT,
  rag_provider      TEXT NOT NULL DEFAULT 'arango',
  rag_space_key     TEXT NOT NULL DEFAULT 'default',
  rag_mode          TEXT NOT NULL DEFAULT 'vector',
  rag_refs          JSONB NOT NULL DEFAULT '[]'::jsonb,
  graph_plan        JSONB NOT NULL DEFAULT '{}'::jsonb,
  asked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  answered_at       TIMESTAMPTZ
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_agent_runs_query'
  ) THEN
    ALTER TABLE edge_ingest.agent_runs
      ADD CONSTRAINT fk_agent_runs_query
      FOREIGN KEY (query_id) REFERENCES edge_ingest.user_queries(id) ON DELETE SET NULL;
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS edge_ingest.rag_spaces (
  id                BIGSERIAL PRIMARY KEY,
  space_key         TEXT NOT NULL UNIQUE,
  display_name      TEXT NOT NULL,
  backend           TEXT NOT NULL DEFAULT 'arango',
  mode              TEXT NOT NULL DEFAULT 'vector',
  is_graph_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
  graph_namespace   TEXT NOT NULL DEFAULT 'default_graph',
  description       TEXT,
  config            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS edge_ingest.rag_graph_nodes (
  id                BIGSERIAL PRIMARY KEY,
  space_id          BIGINT NOT NULL REFERENCES edge_ingest.rag_spaces(id) ON DELETE CASCADE,
  external_node_id  TEXT NOT NULL,
  node_type         TEXT NOT NULL DEFAULT 'entity',
  properties        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_rag_graph_node UNIQUE (space_id, external_node_id)
);

CREATE TABLE IF NOT EXISTS edge_ingest.rag_graph_edges (
  id                BIGSERIAL PRIMARY KEY,
  space_id          BIGINT NOT NULL REFERENCES edge_ingest.rag_spaces(id) ON DELETE CASCADE,
  from_external_node_id TEXT NOT NULL,
  to_external_node_id   TEXT NOT NULL,
  relation_type     TEXT NOT NULL DEFAULT 'related_to',
  properties        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO edge_ingest.rag_spaces (
  space_key,
  display_name,
  backend,
  mode,
  is_graph_enabled,
  graph_namespace,
  description
)
VALUES (
  'default',
  'Default Lorekeeper Space',
  'arango',
  'vector',
  TRUE,
  'default_graph',
  'Reserved space for vector RAG and future graph RAG.'
)
ON CONFLICT (space_key) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_created_at
  ON edge_ingest.agent_runs (agent, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created_at
  ON edge_ingest.agent_runs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_line_push_messages_status_created_at
  ON edge_ingest.line_push_messages (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_line_push_messages_user_created_at
  ON edge_ingest.line_push_messages (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_queries_user_asked_at
  ON edge_ingest.user_queries (user_id, asked_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_daily_usage_user_date
  ON edge_ingest.user_daily_question_usage (user_id, usage_date DESC);

CREATE TABLE IF NOT EXISTS edge_ingest.line_webhook_events (
  id                BIGSERIAL PRIMARY KEY,
  line_event_id     TEXT NOT NULL UNIQUE,
  event_type        TEXT NOT NULL,
  line_user_id      TEXT,
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_line_webhook_events_created_at
  ON edge_ingest.line_webhook_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_line_webhook_events_user_created_at
  ON edge_ingest.line_webhook_events (line_user_id, created_at DESC);
