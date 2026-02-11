from fastapi import APIRouter

from app.adapters.repos.item_translation_repo import ItemTranslationRepo
from app.adapters.repos.raw_item_repo import RawItemRepo
from app.api.v1.schemas.rss_update import IngestReq, RawItemOut
from app.handlers.rss_ingest_handler import RssIngestHandler
from app.services.item_translation_service import ItemTranslationService
from app.services.rss_ingest_service import RssIngestService


router = APIRouter()


def build_handler() -> RssIngestHandler:
    repo = RawItemRepo()
    ingest_service = RssIngestService(repo=repo)
    translation_repo = ItemTranslationRepo()
    translation_service = ItemTranslationService(repo=translation_repo)
    return RssIngestHandler(
        ingest_service=ingest_service,
        pipeline=[translation_service.translate_and_store],
    )


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.post("/ingest/rawitem", response_model=RawItemOut)
def ingest_rawitem(req: IngestReq):
    handler = build_handler()
    result = handler.handle_raw_item(req)
    return RawItemOut(**result)
