from typing import Any, Dict, Optional

import psycopg
from psycopg.types.json import Jsonb

from app.adapters.repos.db import APP_SCHEMA, db_dsn


class LineDeliveryRepo:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or db_dsn()

    def upsert_user(
        self,
        *,
        line_user_id: str,
        display_name: Optional[str] = None,
        preferred_lang: str = "zh-TW",
    ) -> int:
        query = f"""
        INSERT INTO {APP_SCHEMA}.users (line_user_id, display_name, preferred_lang, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (line_user_id) DO UPDATE
          SET display_name = COALESCE(EXCLUDED.display_name, {APP_SCHEMA}.users.display_name),
              preferred_lang = COALESCE(EXCLUDED.preferred_lang, {APP_SCHEMA}.users.preferred_lang),
              updated_at = NOW()
        RETURNING id;
        """

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (line_user_id, display_name, preferred_lang))
                row = cur.fetchone()
                return int(row[0])

    def fetch_push_source(self, raw_item_id: int) -> Optional[Dict[str, Any]]:
        query = f"""
        SELECT
          r.id AS raw_item_id,
          r.title AS source_title,
          r.summary AS source_summary,
          r.url AS source_url,
          t.id AS translation_id,
          t.translated_title,
          t.translated_summary
        FROM {APP_SCHEMA}.raw_items r
        LEFT JOIN LATERAL (
          SELECT id, translated_title, translated_summary
          FROM {APP_SCHEMA}.item_translations
          WHERE raw_item_id = r.id
            AND status = 'DONE'
          ORDER BY id DESC
          LIMIT 1
        ) t ON TRUE
        WHERE r.id = %s;
        """
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (raw_item_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "raw_item_id": int(row[0]),
                    "source_title": row[1] or "",
                    "source_summary": row[2] or "",
                    "source_url": row[3] or "",
                    "translation_id": int(row[4]) if row[4] is not None else None,
                    "translated_title": row[5] or "",
                    "translated_summary": row[6] or "",
                }

    def insert_push_message(self, data: Dict[str, Any]) -> int:
        query = f"""
        INSERT INTO {APP_SCHEMA}.line_push_messages
        (
          user_id,
          raw_item_id,
          translation_id,
          agent_run_id,
          target_line_user_id,
          title,
          message_body,
          payload,
          status,
          line_request_id,
          error_message,
          sent_at
        )
        VALUES
        (
          %(user_id)s,
          %(raw_item_id)s,
          %(translation_id)s,
          %(agent_run_id)s,
          %(target_line_user_id)s,
          %(title)s,
          %(message_body)s,
          %(payload)s,
          %(status)s,
          %(line_request_id)s,
          %(error_message)s,
          %(sent_at)s
        )
        RETURNING id;
        """
        params = {
            "user_id": data["user_id"],
            "raw_item_id": data.get("raw_item_id"),
            "translation_id": data.get("translation_id"),
            "agent_run_id": data.get("agent_run_id"),
            "target_line_user_id": data["target_line_user_id"],
            "title": data["title"],
            "message_body": data["message_body"],
            "payload": Jsonb(data.get("payload", {})),
            "status": data.get("status", "PENDING"),
            "line_request_id": data.get("line_request_id"),
            "error_message": data.get("error_message"),
            "sent_at": data.get("sent_at"),
        }
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return int(row[0])
