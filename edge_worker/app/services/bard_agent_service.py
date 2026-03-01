import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict
from urllib import error, request

from app.adapters.repos.agent_run_repo import AgentRunRepo
from app.adapters.repos.line_delivery_repo import LineDeliveryRepo
from app.config import get_llm_config_by_tenant
from app.services.llm_gateway import LLMGateway, TenantConfig


class BardAgentService:
    def __init__(
        self,
        *,
        line_repo: LineDeliveryRepo,
        run_repo: AgentRunRepo,
        tenant_id: str = "default",
        prompt_version: str = "bard-v1",
        gateway: LLMGateway | None = None,
    ):
        self.line_repo = line_repo
        self.run_repo = run_repo
        self.tenant_id = tenant_id
        self.prompt_version = prompt_version
        self.gateway = gateway or LLMGateway()
        self.tenant_cfg = TenantConfig(**get_llm_config_by_tenant(tenant_id))
        self.gateway.register_tenant(self.tenant_cfg)

    def create_push_and_deliver(
        self,
        *,
        line_user_id: str,
        raw_item_id: int,
        display_name: str | None = None,
        send: bool = True,
    ) -> Dict[str, Any]:
        user_id = self.line_repo.upsert_user(
            line_user_id=line_user_id,
            display_name=display_name,
        )
        source = self.line_repo.fetch_push_source(raw_item_id=raw_item_id)
        if not source:
            raise ValueError(f"raw_item_id={raw_item_id} not found")

        started = time.perf_counter()
        title = source["translated_title"] or source["source_title"]
        summary = source["translated_summary"] or source["source_summary"]
        content_url = source["source_url"]

        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        llm_status = "DONE"
        llm_error = None

        try:
            generated, usage = self._generate_push_message(
                title=title,
                summary=summary,
                url=content_url,
            )
            final_title = generated["title"]
            final_body = generated["message_body"]
        except Exception as exc:
            llm_status = "FAILED"
            llm_error = str(exc)
            final_title = title[:120]
            final_body = f"{summary}\n\n{content_url}".strip()

        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_run_id = self.run_repo.insert_run(
            {
                "agent": "Bard",
                "user_id": user_id,
                "raw_item_id": raw_item_id,
                "query_id": None,
                "provider": self.tenant_cfg.provider,
                "model": self.tenant_cfg.model,
                "prompt_version": self.prompt_version,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "total_tokens": usage["total_tokens"],
                "latency_ms": latency_ms,
                "status": llm_status,
                "error_message": llm_error,
                "meta": {"fallback_used": llm_status != "DONE"},
            }
        )

        delivery_status = "PENDING"
        line_request_id = None
        delivery_error = None
        sent_at = None
        payload = {"messages": [{"type": "text", "text": final_body}]}

        if send:
            delivery = self._push_to_line(line_user_id=line_user_id, message=final_body)
            delivery_status = "SENT" if delivery["ok"] else "FAILED"
            line_request_id = delivery.get("line_request_id")
            delivery_error = delivery.get("error")
            sent_at = datetime.now(timezone.utc).isoformat() if delivery["ok"] else None

        push_message_id = self.line_repo.insert_push_message(
            {
                "user_id": user_id,
                "raw_item_id": raw_item_id,
                "translation_id": source.get("translation_id"),
                "agent_run_id": agent_run_id,
                "target_line_user_id": line_user_id,
                "title": final_title,
                "message_body": final_body,
                "payload": payload,
                "status": delivery_status,
                "line_request_id": line_request_id,
                "error_message": delivery_error,
                "sent_at": sent_at,
            }
        )

        return {
            "user_id": user_id,
            "agent_run_id": agent_run_id,
            "push_message_id": push_message_id,
            "delivery_status": delivery_status,
            "line_request_id": line_request_id,
            "message_preview": final_body,
        }

    def _generate_push_message(self, *, title: str, summary: str, url: str) -> tuple[Dict[str, str], Dict[str, int]]:
        prompt = (
            "你是 LINE 官方帳號新聞推播編輯 Bard。"
            "請以繁體中文輸出 JSON，key 僅有 title, message_body。"
            "message_body 最多 220 字，保留重點，不誇大，不加入不存在資訊。"
        )
        out_msg = self.gateway.invoke(
            self.tenant_id,
            [
                ("system", prompt),
                ("human", f"title:\n{title}\n\nsummary:\n{summary}\n\nurl:\n{url}"),
            ],
            return_message=True,
        )
        content = getattr(out_msg, "content", "") or ""
        parsed = self._safe_parse_json(content)

        message_title = str(parsed.get("title") or title).strip()[:120]
        message_body = str(parsed.get("message_body") or f"{summary}\n\n{url}").strip()
        usage = self._extract_token_usage(out_msg)
        return {"title": message_title, "message_body": message_body}, usage

    def _push_to_line(self, *, line_user_id: str, message: str) -> Dict[str, Any]:
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        if not token:
            return {"ok": False, "error": "LINE_CHANNEL_ACCESS_TOKEN is missing"}

        endpoint = "https://api.line.me/v2/bot/message/push"
        payload = {
            "to": line_user_id,
            "messages": [{"type": "text", "text": message[:5000]}],
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            method="POST",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=20) as resp:
                return {
                    "ok": 200 <= resp.status < 300,
                    "status_code": resp.status,
                    "line_request_id": resp.headers.get("x-line-request-id"),
                }
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            return {"ok": False, "error": f"http_{exc.code}:{body}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _safe_parse_json(self, text: str) -> Dict[str, Any]:
        payload = (text or "").strip()
        if payload.startswith("```"):
            payload = payload.strip("`")
            if payload.startswith("json"):
                payload = payload[4:].strip()
        try:
            value = json.loads(payload)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _extract_token_usage(self, message: Any) -> Dict[str, int]:
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        usage_meta = getattr(message, "usage_metadata", None)
        if isinstance(usage_meta, dict):
            usage["input_tokens"] = int(usage_meta.get("input_tokens", 0) or 0)
            usage["output_tokens"] = int(usage_meta.get("output_tokens", 0) or 0)
            usage["total_tokens"] = int(usage_meta.get("total_tokens", 0) or 0)
            return usage

        resp_meta = getattr(message, "response_metadata", None)
        if isinstance(resp_meta, dict):
            token_usage = resp_meta.get("token_usage") or {}
            usage["input_tokens"] = int(token_usage.get("prompt_tokens", 0) or 0)
            usage["output_tokens"] = int(token_usage.get("completion_tokens", 0) or 0)
            usage["total_tokens"] = int(token_usage.get("total_tokens", 0) or 0)
        return usage
