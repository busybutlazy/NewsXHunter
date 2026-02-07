import os
import json
from hashlib import sha256
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from psycopg.types.json import Jsonb

APP_SCHEMA = os.getenv("EDGE_DB_SCHEMA", "edge_ingest")

def db_dsn() -> str:
    host = os.getenv("EDGE_DB_HOST", "postgres")
    port = os.getenv("EDGE_DB_PORT", "5432")
    name = os.getenv("EDGE_DB_NAME", "edge")
    user = os.getenv("EDGE_DB_USER", "edge")
    password = os.getenv("EDGE_DB_PASSWORD", "")
    return f"host={host} port={port} dbname={name} user={user} password={password}"

router = APIRouter()

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
    isoDate: Optional[str] = None
    pubDate: Optional[str] = None
    creator: Optional[str] = None
    # rights 可能是 string / array / object，先用 Any 接，再在寫入 DB 前統一轉成 str
    rights: Optional[Any] = None
    # raw 可能是 dict 或 JSON 字串，統一在 validator 中處理成 dict
    raw: Optional[Any] = None
    
    @field_validator('raw', mode='before')
    @classmethod
    def normalize_raw(cls, v: Any) -> Optional[Dict[str, Any]]:
        """將 raw 欄位統一轉換成 dict"""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        # 其他型別嘗試轉成 dict
        try:
            if hasattr(v, '__iter__') and not isinstance(v, (str, bytes)):
                return dict(v) if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            pass
        return {}

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
    rights: str
    raw: Dict[str, Any]
    inserted: bool


def _normalize_rights(value: Any) -> str:
    """
    將各種型別的 rights 統一轉成可存入 TEXT 欄位的字串。
    - None -> 空字串
    - str -> 原樣
    - 其他 (list/dict/...) -> 先嘗試 json.dumps，失敗再用 str()
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)

@router.get("/healthz")
def healthz():
    return {"ok": True}

def _canonicalize(source: SourceCtx, item: RssItem) -> Tuple[Dict[str, Any], str]:
    url = item.link or item.url or ""
    title = item.title or ""
    summary = item.contentSnippet or item.content or item.summary or ""
    published = item.isoDate or item.pubDate  # may be None
    # deduplication 去重用 利用source + guid等內容組裝 再sha256變成唯一碼 
    dedup_input = f"{source.source_key}||{item.guid or ''}||{url}||{title}||{published or ''}"
    dedup_key = sha256(dedup_input.encode("utf-8")).hexdigest()
    item_id = f"{source.source_key}:sha256:{dedup_key}"

    now = datetime.now(timezone.utc).isoformat()

    # raw 直接保留 JSON 結構，後面用 Jsonb 包裝給 DB
    raw: Dict[str, Any] = dict(item.raw or {})

    # 若外部有傳 rights，就優先用外部的；否則使用預設設定
    default_rights = {"store_fulltext": False, "mode": "rss_summary_link_only"}
    rights_source = item.rights if item.rights is not None else default_rights
    rights_str = _normalize_rights(rights_source)

    data: Dict[str, Any] = dict(
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
        rights=rights_str,
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

@router.post("/ingest/rawitem", response_model=RawItemOut)
def ingest_rawitem(req: IngestReq):
    data, _ = _canonicalize(req.source, req.item)
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
            # raw 使用 Jsonb 包裝，確保可以正確寫入 JSONB 欄位
            db_params = {**data, "raw": Jsonb(data["raw"])}
            cur.execute(q, db_params)
            row = cur.fetchone()
            inserted = bool(row[0]) if row else False

    return RawItemOut(**{k: data[k] for k in RawItemOut.model_fields.keys() if k in data}, inserted=inserted)
