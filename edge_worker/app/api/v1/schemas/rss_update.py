import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, field_validator


class SourceCtx(BaseModel):
    source_id: int
    source_key: str


class RssItem(BaseModel):
    link: Optional[str] = None
    url: Optional[str] = None
    guid: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    contentSnippet: Optional[str] = None
    content: Optional[str] = None
    isoDate: Optional[str] = None
    pubDate: Optional[str] = None
    creator: Optional[str] = None
    rights: Optional[Any] = None
    raw: Optional[Any] = None

    @field_validator("raw", mode="before")
    @classmethod
    def normalize_raw(cls, value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        try:
            if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
                return dict(value) if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}
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
