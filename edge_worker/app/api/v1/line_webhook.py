import json

from fastapi import APIRouter, Header, HTTPException, Request

from app.services.line_messaging_service import LineMessagingService
from app.services.line_webhook_service import build_line_webhook_service


router = APIRouter()


@router.post("/webhook")
async def line_webhook(
    request: Request,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
):
    body_bytes = await request.body()
    line_service = LineMessagingService()
    if not line_service.verify_signature(body_bytes, x_line_signature):
        raise HTTPException(status_code=401, detail="Invalid LINE signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    result = build_line_webhook_service().handle_body(payload if isinstance(payload, dict) else {})
    return result
