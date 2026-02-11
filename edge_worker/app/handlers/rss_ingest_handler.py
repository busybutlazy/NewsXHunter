from typing import Any, Callable, Dict

from app.api.v1.schemas.rss_update import IngestReq
from app.services.rss_ingest_service import RssIngestService


class RssIngestHandler:
    def __init__(self, ingest_service: RssIngestService, pipeline: list[Callable[[Dict[str, Any]], Dict[str, Any]]] | None = None):
        self.ingest_service = ingest_service
        self.pipeline = pipeline or []

    def handle_raw_item(self, req: IngestReq) -> Dict[str, Any]:
        payload = self.ingest_service.ingest_raw_item(req)
        for stage in self.pipeline:
            payload = stage(payload)
        return payload
