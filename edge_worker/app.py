import os
from hashlib import sha256
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

APP_SCHEMA = os.getenv("EDGE_DB_SCHEMA", "edge_ingest")

def db_dsn() -> str:
    host = os.getenv("EDGE_DB_HOST", "postgres")
    port = os.getenv("EDGE_DB_PORT", "5432")
    name = os.getenv("EDGE_DB_NAME", "edge")
    user = os.getenv("EDGE_DB_USER", "edge")
    password = os.getenv("EDGE_DB_PASSWORD", "")
    return f"host={host} port={port} dbname={name} user={user} password={password}"

app = FastAPI(title="edge-worker", version="1.0.0")

class SourceCtx(BaseModel):
    source_id: int
    source_key: str

class RssItem(BaseModel):
    link: Optional[str] = None
    url: Optional[str] = None
    guid: Optional[str] = None
    title: Optional[str] = None
    contentSnippet: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    isoDate: Optional[str] = None
    pubDate: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

class IngestReq(BaseModel):
    source: SourceCtx
    item: RssItem

class RawItemOut(BaseModel):
    item_id: str
    source_id: int
    source_key: str
    url: str
    title: str
    summary: str
    published_at: Optional[str]
    fetched_at: str
    lang: str
    dedup_key: str
    rights: Dict[str, Any]
    raw: Dict[str, Any]
    inserted: bool

@app.get("/healthz")
def healthz():
    return {"ok": True}

def _canonicalize(source: SourceCtx, item: RssItem) -> Tuple[Dict[str, Any], str]:
    url = item.link or item.url or ""
    title = item.title or ""
    summary = item.contentSnippet or item.content or item.summary or ""
    published = item.isoDate or item.pubDate  # may be None

    dedup_input = f"{source.source_key}||{item.guid or ''}||{url}||{title}||{published or ''}"
    dedup_key = sha256(dedup_input.encode("utf-8")).hexdigest()
    item_id = f"{source.source_key}:sha256:{dedup_key}"

    now = datetime.now(timezone.utc).isoformat()

    raw = item.raw or {}
    rights = {"store_fulltext": False, "mode": "rss_summary_link_only"}

    data = dict(
        item_id=item_id,
        source_id=source.source_id,
        source_key=source.source_key,
        url=url,
        title=title,
        summary=summary,
        published_at=published,
        fetched_at=now,
        lang="en",
        dedup_key=dedup_key,
        rights=rights,
        raw=raw,
        status="RAW",
    )
    return data, now

def _validate_source(conn: psycopg.Connection, source: SourceCtx) -> None:
    q = f"SELECT 1 FROM {APP_SCHEMA}.sources WHERE id=%s AND source_key=%s AND enabled=TRUE"
    with conn.cursor() as cur:
        cur.execute(q, (source.source_id, source.source_key))
        if cur.fetchone() is None:
            raise HTTPException(status_code=400, detail="Invalid or disabled source")

@app.post("/v1/ingest/rawitem", response_model=RawItemOut)
def ingest_rawitem(req: IngestReq):
    data, _ = _canonicalize(req.source, req.item)
    db_data = dict(data)
    db_data["rights"] = Jsonb(db_data["rights"])
    db_data["raw"] = Jsonb(db_data["raw"])
    with psycopg.connect(db_dsn()) as conn:
        _validate_source(conn, req.source)

        q = f"""
        INSERT INTO {APP_SCHEMA}.raw_items
        (item_id, source_id, source_key, url, title, summary, published_at, fetched_at, lang, dedup_key, rights, raw, status)
        VALUES
        (%(item_id)s, %(source_id)s, %(source_key)s, %(url)s, %(title)s, %(summary)s, %(published_at)s, %(fetched_at)s,
         %(lang)s, %(dedup_key)s, %(rights)s, %(raw)s, %(status)s)
        ON CONFLICT (dedup_key) DO UPDATE
          SET fetched_at = EXCLUDED.fetched_at
        RETURNING (xmax = 0) AS inserted;
        """
        with conn.cursor() as cur:
            cur.execute(q, db_data)
            row = cur.fetchone()
            inserted = bool(row[0]) if row else False

    return RawItemOut(**{k: data[k] for k in RawItemOut.model_fields.keys() if k in data}, inserted=inserted)
