import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict

from fastapi import HTTPException

from app.adapters.repos.raw_item_repo import RawItemRepo
from app.api.v1.schemas.rss_update import IngestReq


class RssIngestService:
    def __init__(self, repo: RawItemRepo):
        self.repo = repo

    def ingest_raw_item(self, req: IngestReq) -> Dict[str, Any]:
        data = self._canonicalize(req)
        write_result = self.repo.ingest_raw_item(
            source_id=req.source.source_id,
            source_key=req.source.source_key,
            data=data,
        )
        if not write_result["source_valid"]:
            raise HTTPException(status_code=400, detail="Invalid or disabled source")
        return {
            **data,
            "inserted": write_result["inserted"],
            "raw_item_id": write_result["raw_item_id"],
        }

    def _canonicalize(self, req: IngestReq) -> Dict[str, Any]:
        source = req.source
        item = req.item

        url = item.link or item.url or ""
        title = item.title or ""
        summary = item.summary or item.contentSnippet or item.content or ""
        published = item.isoDate or item.pubDate

        dedup_input = f"{source.source_key}||{item.guid or ''}||{url}||{title}||{published or ''}"
        dedup_key = sha256(dedup_input.encode("utf-8")).hexdigest()
        item_id = f"{source.source_key}:sha256:{dedup_key}"
        now = datetime.now(timezone.utc).isoformat()

        raw = dict(item.raw or {})

        default_rights = {"store_fulltext": False, "mode": "rss_summary_link_only"}
        rights_source = item.rights if item.rights is not None else default_rights
        rights = self._normalize_rights(rights_source)

        return {
            "item_id": item_id,
            "source_id": source.source_id,
            "source_key": source.source_key,
            "url": url,
            "title": title,
            "summary": summary,
            "published_at": published,
            "fetched_at": now,
            "lang": "en",
            "dedup_key": dedup_key,
            "rights": rights,
            "raw": raw,
            "status": "RAW",
        }

    def _normalize_rights(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)
