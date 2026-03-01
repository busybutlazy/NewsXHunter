import hashlib
import json
from typing import Any, Dict

from app.adapters.repos.line_delivery_repo import LineDeliveryRepo
from app.adapters.repos.user_query_repo import UserQueryRepo
from app.adapters.repos.agent_run_repo import AgentRunRepo
from app.services.line_messaging_service import LineMessagingService
from app.services.lorekeeper_agent_service import LorekeeperAgentService


class LineWebhookService:
    def __init__(
        self,
        *,
        line_repo: LineDeliveryRepo,
        lorekeeper_service: LorekeeperAgentService,
        line_messaging: LineMessagingService | None = None,
    ):
        self.line_repo = line_repo
        self.lorekeeper_service = lorekeeper_service
        self.line_messaging = line_messaging or LineMessagingService()

    def handle_body(self, body: Dict[str, Any]) -> Dict[str, Any]:
        events = body.get("events") or []
        processed = 0
        dedup_skipped = 0

        for event in events:
            event_id = self._event_id(event)
            source = event.get("source") or {}
            line_user_id = source.get("userId")
            event_type = str(event.get("type") or "unknown")
            inserted = self.line_repo.register_webhook_event(
                line_event_id=event_id,
                event_type=event_type,
                line_user_id=line_user_id,
                payload=event if isinstance(event, dict) else {},
            )
            if not inserted:
                dedup_skipped += 1
                continue
            processed += 1

            if event_type == "follow":
                self._on_follow(event, line_user_id)
                continue

            if event_type == "unfollow":
                self._on_unfollow(line_user_id)
                continue

            if event_type == "message":
                self._on_message(event, line_user_id)
                continue

        return {
            "ok": True,
            "processed": processed,
            "dedup_skipped": dedup_skipped,
            "total_events": len(events),
        }

    def _on_follow(self, event: Dict[str, Any], line_user_id: str | None) -> None:
        if not line_user_id:
            return
        self.line_repo.upsert_user(line_user_id=line_user_id, is_active=True)
        reply_token = event.get("replyToken")
        if isinstance(reply_token, str) and reply_token:
            self.line_messaging.reply_text(
                reply_token=reply_token,
                message="歡迎加入，之後我會推播重點新聞，也可以直接提問。",
            )

    def _on_unfollow(self, line_user_id: str | None) -> None:
        if not line_user_id:
            return
        self.line_repo.set_user_active(line_user_id=line_user_id, is_active=False)

    def _on_message(self, event: Dict[str, Any], line_user_id: str | None) -> None:
        if not line_user_id:
            return
        message = event.get("message") or {}
        if message.get("type") != "text":
            return
        text = str(message.get("text") or "").strip()
        if not text:
            return

        result = self.lorekeeper_service.ask(
            line_user_id=line_user_id,
            question=text,
            rag_space_key="default",
        )
        reply_text = result.get("answer") or result.get("rejected_reason") or "目前無法回答，請稍後再試。"
        reply_token = event.get("replyToken")
        if isinstance(reply_token, str) and reply_token:
            self.line_messaging.reply_text(reply_token=reply_token, message=reply_text)

    def _event_id(self, event: Dict[str, Any]) -> str:
        event_id = event.get("webhookEventId")
        if isinstance(event_id, str) and event_id:
            return event_id
        fallback_raw = json.dumps(event, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(fallback_raw.encode("utf-8")).hexdigest()


def build_line_webhook_service() -> LineWebhookService:
    return LineWebhookService(
        line_repo=LineDeliveryRepo(),
        lorekeeper_service=LorekeeperAgentService(
            query_repo=UserQueryRepo(),
            run_repo=AgentRunRepo(),
        ),
    )
