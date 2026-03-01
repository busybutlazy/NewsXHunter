from datetime import date
from typing import Any, Dict, Optional

import psycopg
from psycopg.types.json import Jsonb

from app.adapters.repos.db import APP_SCHEMA, db_dsn


class UserQueryRepo:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or db_dsn()

    def get_or_create_user(
        self,
        *,
        line_user_id: str,
        display_name: Optional[str] = None,
        preferred_lang: str = "zh-TW",
    ) -> Dict[str, Any]:
        query = f"""
        INSERT INTO {APP_SCHEMA}.users (line_user_id, display_name, preferred_lang, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (line_user_id) DO UPDATE
          SET display_name = COALESCE(EXCLUDED.display_name, {APP_SCHEMA}.users.display_name),
              preferred_lang = COALESCE(EXCLUDED.preferred_lang, {APP_SCHEMA}.users.preferred_lang),
              updated_at = NOW()
        RETURNING id, line_user_id, timezone, COALESCE(daily_question_limit, 5) AS daily_question_limit;
        """
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (line_user_id, display_name, preferred_lang))
                row = cur.fetchone()
                return {
                    "user_id": int(row[0]),
                    "line_user_id": row[1],
                    "timezone": row[2] or "UTC",
                    "daily_question_limit": int(row[3]),
                }

    def consume_daily_quota(self, *, user_id: int, usage_date: date, limit_count: int) -> Dict[str, Any]:
        upsert_sql = f"""
        INSERT INTO {APP_SCHEMA}.user_daily_question_usage
          (user_id, usage_date, used_count, limit_count, updated_at)
        VALUES
          (%s, %s, 1, %s, NOW())
        ON CONFLICT (user_id, usage_date) DO UPDATE
          SET used_count = {APP_SCHEMA}.user_daily_question_usage.used_count + 1,
              updated_at = NOW()
        WHERE {APP_SCHEMA}.user_daily_question_usage.used_count < {APP_SCHEMA}.user_daily_question_usage.limit_count
        RETURNING used_count, limit_count;
        """

        lookup_sql = f"""
        SELECT used_count, limit_count
        FROM {APP_SCHEMA}.user_daily_question_usage
        WHERE user_id = %s AND usage_date = %s;
        """

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(upsert_sql, (user_id, usage_date, limit_count))
                row = cur.fetchone()
                if row:
                    used_count, db_limit = int(row[0]), int(row[1])
                    return {
                        "allowed": True,
                        "used_count": used_count,
                        "limit_count": db_limit,
                        "remaining": max(db_limit - used_count, 0),
                    }

                cur.execute(lookup_sql, (user_id, usage_date))
                denied_row = cur.fetchone()
                if denied_row:
                    used_count, db_limit = int(denied_row[0]), int(denied_row[1])
                    return {
                        "allowed": False,
                        "used_count": used_count,
                        "limit_count": db_limit,
                        "remaining": max(db_limit - used_count, 0),
                    }

        return {
            "allowed": False,
            "used_count": 0,
            "limit_count": int(limit_count),
            "remaining": int(limit_count),
        }

    def get_rag_space(self, space_key: str) -> Optional[Dict[str, Any]]:
        query = f"""
        SELECT id, space_key, backend, mode, is_graph_enabled, graph_namespace, config
        FROM {APP_SCHEMA}.rag_spaces
        WHERE space_key = %s;
        """
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (space_key,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "space_id": int(row[0]),
                    "space_key": row[1],
                    "backend": row[2],
                    "mode": row[3],
                    "is_graph_enabled": bool(row[4]),
                    "graph_namespace": row[5],
                    "config": row[6] or {},
                }

    def insert_query(self, data: Dict[str, Any]) -> int:
        query = f"""
        INSERT INTO {APP_SCHEMA}.user_queries
        (
          user_id,
          question_text,
          answer_text,
          status,
          rejected_reason,
          rag_provider,
          rag_space_key,
          rag_mode,
          rag_refs,
          graph_plan,
          answered_at
        )
        VALUES
        (
          %(user_id)s,
          %(question_text)s,
          %(answer_text)s,
          %(status)s,
          %(rejected_reason)s,
          %(rag_provider)s,
          %(rag_space_key)s,
          %(rag_mode)s,
          %(rag_refs)s,
          %(graph_plan)s,
          %(answered_at)s
        )
        RETURNING id;
        """
        params = {
            "user_id": data["user_id"],
            "question_text": data["question_text"],
            "answer_text": data.get("answer_text"),
            "status": data.get("status", "ANSWERED"),
            "rejected_reason": data.get("rejected_reason"),
            "rag_provider": data.get("rag_provider", "arango"),
            "rag_space_key": data.get("rag_space_key", "default"),
            "rag_mode": data.get("rag_mode", "vector"),
            "rag_refs": Jsonb(data.get("rag_refs", [])),
            "graph_plan": Jsonb(data.get("graph_plan", {})),
            "answered_at": data.get("answered_at"),
        }
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return int(row[0])
