import hashlib
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.adapters.repos.item_translation_repo import ItemTranslationRepo
from app.config import get_llm_config_by_tenant
from app.services.llm_gateway import LLMGateway, TenantConfig


class TranslationOut(BaseModel):
    translated_title: str
    translated_summary: str
    translated_content: Optional[str] = None


class ItemTranslationService:
    def __init__(
        self,
        repo: ItemTranslationRepo,
        *,
        tenant_id: str = "default",
        target_lang: str = "zh-TW",
        prompt_version: str = "v1",
        gateway: LLMGateway | None = None,
    ):
        self.repo = repo
        self.tenant_id = tenant_id
        self.target_lang = target_lang
        self.prompt_version = prompt_version

        self.gateway = gateway or LLMGateway()
        self.tenant_cfg = TenantConfig(**get_llm_config_by_tenant(tenant_id))
        self.gateway.register_tenant(self.tenant_cfg)

    def translate_and_store(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not payload.get("inserted"):
            return payload

        raw_item_id = payload.get("raw_item_id")
        if raw_item_id is None:
            return payload

        source_title = payload.get("title", "")
        source_summary = payload.get("summary", "")
        source_content = self._extract_source_content(payload)
        source_hash = self._build_source_text_hash(source_title, source_summary, source_content)

        try:
            translated = self._translate(
                title=source_title,
                summary=source_summary,
                content=source_content,
            )

            translation_id = self.repo.insert_translation(
                {
                    "raw_item_id": raw_item_id,
                    "target_lang": self.target_lang,
                    "translated_title": translated.translated_title,
                    "translated_summary": translated.translated_summary,
                    "translated_content": translated.translated_content,
                    "engine_provider": self.tenant_cfg.provider,
                    "model": self.tenant_cfg.model,
                    "prompt_version": self.prompt_version,
                    "source_text_hash": source_hash,
                    "status": "DONE",
                    "error_message": None,
                    "meta": {
                        "source_lang": payload.get("lang", "en"),
                        "source_key": payload.get("source_key", ""),
                    },
                }
            )

            payload["translation"] = {
                "id": translation_id,
                "status": "DONE",
                "target_lang": self.target_lang,
            }
            return payload
        except Exception as exc:
            fail_id = self.repo.mark_failed(
                raw_item_id=int(raw_item_id),
                target_lang=self.target_lang,
                engine_provider=self.tenant_cfg.provider,
                model=self.tenant_cfg.model,
                prompt_version=self.prompt_version,
                source_text_hash=source_hash,
                error_message=str(exc),
                meta={"source_key": payload.get("source_key", "")},
            )
            payload["translation"] = {
                "id": fail_id,
                "status": "FAILED",
                "target_lang": self.target_lang,
                "error": str(exc),
            }
            return payload

    def _translate(self, *, title: str, summary: str, content: str) -> TranslationOut:
        prompt = (
            "You are a precise news translator. Translate input to Traditional Chinese (zh-TW). "
            "Keep facts, names, numbers unchanged when needed. "
            "Return only translated text ㄆfields."
        )

        runnable = self.gateway.with_structured_output(self.tenant_id, TranslationOut)
        result = runnable.invoke(
            [
                ("system", prompt),
                (
                    "human",
                    f"title:\n{title}\n\nsummary:\n{summary}\n\ncontent:\n{content}",
                ),
            ]
        )

        if isinstance(result, TranslationOut):
            return result
        if isinstance(result, dict):
            return TranslationOut(**result)
        return TranslationOut.model_validate(result)

    def _extract_source_content(self, payload: Dict[str, Any]) -> str:
        raw = payload.get("raw") or {}
        if isinstance(raw, dict):
            value = raw.get("content") or raw.get("content:encoded") or raw.get("description") or ""
            if isinstance(value, str):
                return value
        return ""

    def _build_source_text_hash(self, title: str, summary: str, content: str) -> str:
        composed = f"{title}\n{summary}\n{content}"
        return hashlib.sha256(composed.encode("utf-8")).hexdigest()
