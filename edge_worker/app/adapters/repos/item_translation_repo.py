import os
from typing import Any, Dict, Optional

import psycopg
from psycopg.types.json import Jsonb


APP_SCHEMA = os.getenv("EDGE_DB_SCHEMA", "edge_ingest")


def db_dsn() -> str:
    host = os.getenv("EDGE_DB_HOST", "postgres")
    port = os.getenv("EDGE_DB_PORT", "5432")
    name = os.getenv("EDGE_DB_NAME", "edge")
    user = os.getenv("EDGE_DB_USER", "edge")
    password = os.getenv("EDGE_DB_PASSWORD", "")
    return f"host={host} port={port} dbname={name} user={user} password={password}"


class ItemTranslationRepo:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or db_dsn()

    def insert_translation(self, data: Dict[str, Any]) -> int:
        query = f"""
        INSERT INTO {APP_SCHEMA}.item_translations
        (
          raw_item_id,
          target_lang,
          translated_title,
          translated_summary,
          translated_content,
          engine_provider,
          model,
          prompt_version,
          source_text_hash,
          status,
          error_message,
          meta,
          updated_at
        )
        VALUES
        (
          %(raw_item_id)s,
          %(target_lang)s,
          %(translated_title)s,
          %(translated_summary)s,
          %(translated_content)s,
          %(engine_provider)s,
          %(model)s,
          %(prompt_version)s,
          %(source_text_hash)s,
          %(status)s,
          %(error_message)s,
          %(meta)s,
          NOW()
        )
        RETURNING id;
        """

        params = {**data, "meta": Jsonb(data.get("meta", {}))}

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return int(row[0])

    def mark_failed(
        self,
        *,
        raw_item_id: int,
        target_lang: str,
        engine_provider: str,
        model: str,
        prompt_version: str,
        source_text_hash: str,
        error_message: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        return self.insert_translation(
            {
                "raw_item_id": raw_item_id,
                "target_lang": target_lang,
                "translated_title": None,
                "translated_summary": None,
                "translated_content": None,
                "engine_provider": engine_provider,
                "model": model,
                "prompt_version": prompt_version,
                "source_text_hash": source_text_hash,
                "status": "FAILED",
                "error_message": error_message[:2000],
                "meta": meta or {},
            }
        )
