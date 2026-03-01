from typing import Any, Dict

import psycopg
from psycopg.types.json import Jsonb

from app.adapters.repos.db import APP_SCHEMA, db_dsn


class RawItemRepo:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or db_dsn()

    def validate_source(self, conn: psycopg.Connection, source_id: int, source_key: str) -> bool:
        query = f"SELECT 1 FROM {APP_SCHEMA}.sources WHERE id=%s AND source_key=%s AND enabled=TRUE"
        with conn.cursor() as cur:
            cur.execute(query, (source_id, source_key))
            return cur.fetchone() is not None

    def upsert_raw_item(self, conn: psycopg.Connection, data: Dict[str, Any]) -> Dict[str, Any]:
        query = f"""
        INSERT INTO {APP_SCHEMA}.raw_items
        (item_id, source_id, source_key, url, title, summary, published_at, fetched_at, lang, dedup_key, rights, raw, status)
        VALUES
        (%(item_id)s, %(source_id)s, %(source_key)s, %(url)s, %(title)s, %(summary)s, %(published_at)s, %(fetched_at)s,
         %(lang)s, %(dedup_key)s, %(rights)s, %(raw)s, %(status)s)
        ON CONFLICT (dedup_key) DO UPDATE
          SET fetched_at = EXCLUDED.fetched_at
        RETURNING id, (xmax = 0) AS inserted;
        """
        db_params = {**data, "raw": Jsonb(data["raw"])}

        with conn.cursor() as cur:
            cur.execute(query, db_params)
            row = cur.fetchone()
            if not row:
                return {"raw_item_id": None, "inserted": False}
            return {"raw_item_id": int(row[0]), "inserted": bool(row[1])}

    def ingest_raw_item(self, source_id: int, source_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with psycopg.connect(self.dsn) as conn:
            if not self.validate_source(conn, source_id, source_key):
                return {"source_valid": False, "inserted": False, "raw_item_id": None}
            upsert_result = self.upsert_raw_item(conn, data)
            return {
                "source_valid": True,
                "inserted": upsert_result["inserted"],
                "raw_item_id": upsert_result["raw_item_id"],
            }
