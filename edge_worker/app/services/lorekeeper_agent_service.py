import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from app.adapters.repos.agent_run_repo import AgentRunRepo
from app.adapters.repos.user_query_repo import UserQueryRepo
from app.config import get_llm_config_by_tenant
from app.services.llm_gateway import LLMGateway, TenantConfig


class LorekeeperAgentService:
    def __init__(
        self,
        *,
        query_repo: UserQueryRepo,
        run_repo: AgentRunRepo,
        tenant_id: str = "default",
        prompt_version: str = "lorekeeper-v1",
        gateway: LLMGateway | None = None,
    ):
        self.query_repo = query_repo
        self.run_repo = run_repo
        self.tenant_id = tenant_id
        self.prompt_version = prompt_version
        self.gateway = gateway or LLMGateway()
        self.tenant_cfg = TenantConfig(**get_llm_config_by_tenant(tenant_id))
        self.gateway.register_tenant(self.tenant_cfg)

    def ask(
        self,
        *,
        line_user_id: str,
        question: str,
        display_name: str | None = None,
        rag_space_key: str = "default",
    ) -> Dict[str, Any]:
        user = self.query_repo.get_or_create_user(
            line_user_id=line_user_id,
            display_name=display_name,
        )
        user_id = user["user_id"]
        limit = int(user["daily_question_limit"])
        user_tz = user.get("timezone", "UTC")
        try:
            today = datetime.now(ZoneInfo(user_tz)).date()
        except Exception:
            today = datetime.now(timezone.utc).date()
        quota = self.query_repo.consume_daily_quota(
            user_id=user_id,
            usage_date=today,
            limit_count=limit,
        )

        rag_space = self.query_repo.get_rag_space(rag_space_key) or {
            "space_key": "default",
            "backend": "arango",
            "mode": "vector",
            "is_graph_enabled": True,
            "graph_namespace": "default_graph",
            "config": {},
        }

        graph_plan = {
            "graph_rag_reserved": bool(rag_space.get("is_graph_enabled", True)),
            "namespace": rag_space.get("graph_namespace", "default_graph"),
            "state": "reserved_not_implemented",
        }

        if not quota["allowed"]:
            query_id = self.query_repo.insert_query(
                {
                    "user_id": user_id,
                    "question_text": question,
                    "answer_text": None,
                    "status": "REJECTED",
                    "rejected_reason": "DAILY_LIMIT_REACHED",
                    "rag_provider": rag_space.get("backend", "arango"),
                    "rag_space_key": rag_space.get("space_key", "default"),
                    "rag_mode": rag_space.get("mode", "vector"),
                    "rag_refs": [],
                    "graph_plan": graph_plan,
                    "answered_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return {
                "user_id": user_id,
                "query_id": query_id,
                "status": "REJECTED",
                "answer": None,
                "rejected_reason": "你今日提問次數已達上限（5次）。",
                "usage": quota,
            }

        rag_refs = self._retrieve_context(question=question, rag_space=rag_space)
        started = time.perf_counter()
        try:
            answer, usage = self._generate_answer(question=question, rag_refs=rag_refs)
            query_id = self.query_repo.insert_query(
                {
                    "user_id": user_id,
                    "question_text": question,
                    "answer_text": answer,
                    "status": "ANSWERED",
                    "rejected_reason": None,
                    "rag_provider": rag_space.get("backend", "arango"),
                    "rag_space_key": rag_space.get("space_key", "default"),
                    "rag_mode": rag_space.get("mode", "vector"),
                    "rag_refs": rag_refs,
                    "graph_plan": graph_plan,
                    "answered_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            self.run_repo.insert_run(
                {
                    "agent": "Lorekeeper",
                    "user_id": user_id,
                    "query_id": query_id,
                    "provider": self.tenant_cfg.provider,
                    "model": self.tenant_cfg.model,
                    "prompt_version": self.prompt_version,
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "total_tokens": usage["total_tokens"],
                    "latency_ms": latency_ms,
                    "status": "DONE",
                    "error_message": None,
                    "meta": {"rag_refs_count": len(rag_refs)},
                }
            )
            return {
                "user_id": user_id,
                "query_id": query_id,
                "status": "ANSWERED",
                "answer": answer,
                "rejected_reason": None,
                "usage": quota,
            }
        except Exception as exc:
            query_id = self.query_repo.insert_query(
                {
                    "user_id": user_id,
                    "question_text": question,
                    "answer_text": None,
                    "status": "FAILED",
                    "rejected_reason": str(exc)[:500],
                    "rag_provider": rag_space.get("backend", "arango"),
                    "rag_space_key": rag_space.get("space_key", "default"),
                    "rag_mode": rag_space.get("mode", "vector"),
                    "rag_refs": rag_refs,
                    "graph_plan": graph_plan,
                    "answered_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self.run_repo.insert_failed(
                agent="Lorekeeper",
                error_message=str(exc),
                provider=self.tenant_cfg.provider,
                model=self.tenant_cfg.model,
                prompt_version=self.prompt_version,
                user_id=user_id,
                query_id=query_id,
                meta={"rag_refs_count": len(rag_refs)},
            )
            return {
                "user_id": user_id,
                "query_id": query_id,
                "status": "FAILED",
                "answer": None,
                "rejected_reason": "系統忙碌中，請稍後再試。",
                "usage": quota,
            }

    def _retrieve_context(self, *, question: str, rag_space: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Placeholder for Arango vector retrieval.
        return [
            {
                "source": "arango",
                "space_key": rag_space.get("space_key", "default"),
                "note": "Vector RAG retrieval not implemented yet.",
                "question": question[:160],
            }
        ]

    def _generate_answer(self, *, question: str, rag_refs: List[Dict[str, Any]]) -> tuple[str, Dict[str, int]]:
        prompt = (
            "你是 Lorekeeper。請用繁體中文回答，內容要精準、可讀。"
            "若檢索內容不足，明確說明限制，不可捏造。"
        )
        out_msg = self.gateway.invoke(
            self.tenant_id,
            [
                ("system", prompt),
                ("human", f"question:\n{question}\n\nrag_refs:\n{rag_refs}"),
            ],
            return_message=True,
        )
        answer = str(getattr(out_msg, "content", "") or "").strip()
        if not answer:
            answer = "目前找不到足夠資料回答，請提供更具體的問題。"
        usage = self._extract_token_usage(out_msg)
        return answer, usage

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
