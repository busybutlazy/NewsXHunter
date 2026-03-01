from typing import Any, Dict, Optional

import psycopg
from psycopg.types.json import Jsonb

from app.adapters.repos.db import APP_SCHEMA, db_dsn


class AgentRunRepo:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or db_dsn()

    def insert_run(self, data: Dict[str, Any]) -> int:
        query = f"""
        INSERT INTO {APP_SCHEMA}.agent_runs
        (
          agent,
          user_id,
          raw_item_id,
          query_id,
          provider,
          model,
          prompt_version,
          input_tokens,
          output_tokens,
          total_tokens,
          latency_ms,
          status,
          error_message,
          meta
        )
        VALUES
        (
          %(agent)s,
          %(user_id)s,
          %(raw_item_id)s,
          %(query_id)s,
          %(provider)s,
          %(model)s,
          %(prompt_version)s,
          %(input_tokens)s,
          %(output_tokens)s,
          %(total_tokens)s,
          %(latency_ms)s,
          %(status)s,
          %(error_message)s,
          %(meta)s
        )
        RETURNING id;
        """

        params = {
            "agent": data["agent"],
            "user_id": data.get("user_id"),
            "raw_item_id": data.get("raw_item_id"),
            "query_id": data.get("query_id"),
            "provider": data.get("provider", ""),
            "model": data.get("model", ""),
            "prompt_version": data.get("prompt_version", ""),
            "input_tokens": int(data.get("input_tokens", 0) or 0),
            "output_tokens": int(data.get("output_tokens", 0) or 0),
            "total_tokens": int(data.get("total_tokens", 0) or 0),
            "latency_ms": data.get("latency_ms"),
            "status": data.get("status", "DONE"),
            "error_message": data.get("error_message"),
            "meta": Jsonb(data.get("meta", {})),
        }

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return int(row[0])

    def insert_failed(
        self,
        *,
        agent: str,
        error_message: str,
        provider: str = "",
        model: str = "",
        prompt_version: str = "",
        user_id: Optional[int] = None,
        raw_item_id: Optional[int] = None,
        query_id: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        return self.insert_run(
            {
                "agent": agent,
                "user_id": user_id,
                "raw_item_id": raw_item_id,
                "query_id": query_id,
                "provider": provider,
                "model": model,
                "prompt_version": prompt_version,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "latency_ms": None,
                "status": "FAILED",
                "error_message": error_message[:2000],
                "meta": meta or {},
            }
        )
