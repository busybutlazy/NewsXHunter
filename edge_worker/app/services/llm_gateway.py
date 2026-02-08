from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union, Literal

from app.config import get_llm_config_by_tenant


try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import BaseMessage, convert_to_messages
except Exception as e:  # pragma: no cover
    raise ImportError(
        "LangChain core is required. Install: pip install -U langchain-core"
    ) from e


ProviderName = Literal["openai", "ollama", "custom"]

MessageLike = Union[
    BaseMessage,
    str,
    Tuple[str, str],          # ("system"|"human"|"ai", "content")
    Dict[str, Any],           # OpenAI-style {"role": "...", "content": "..."}
]

ChatResult = Union[str, BaseMessage]


@dataclass(frozen=True)
class TenantConfig:
    """
    Tenant-level configuration.
    - provider: "openai" | "ollama" | "custom"
    - model: model name (e.g. "gpt-4o-mini", "llama3.1", "deepseek-r1:8b")
    - api_key/base_url: used by providers that need them
    - default_params: default kwargs to model init or bind (temperature, max_tokens, etc.)
    """
    tenant_id: str
    provider: ProviderName = "openai"
    model: str = "gpt-4o-mini"

    # Credentials / endpoints (optional)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    organization: Optional[str] = None  # for OpenAI-compatible org header (optional)

    # Default inference params
    default_params: Dict[str, Any] = field(default_factory=lambda: {"temperature": 0.2})

    # Free-form tags/metadata for tracing
    tags: List[str] = field(default_factory=list)


class LLMGateway:
    """
    Multi-tenant LLM gateway built on LangChain chat model abstraction.

    Key goals:
    - Tenant isolation: each tenant resolves its own provider/model/api_key/base_url
    - Future-proof: swap OpenAI -> local LLM (e.g., Ollama) without changing callers
    - Safe config precedence: explicit per-call overrides > tenant config > env defaults
    """

    def __init__(
        self,
        *,
        tenants: Optional[Dict[str, TenantConfig]] = None,
        # Default OpenAI key (optional). Can still override per tenant or per call.
        openai_api_key: Optional[str] = None,
        # Environment variable base name for OpenAI keys
        openai_env_var: str = "OPENAI_API_KEY",
        # Custom provider factory for provider="custom"
        custom_factory: Optional[Callable[[TenantConfig], BaseChatModel]] = None,
        # Cache model instances per (tenant_id, provider, model, base_url, api_key_hash-ish)
        enable_model_cache: bool = True,
    ) -> None:
        self._tenants: Dict[str, TenantConfig] = dict(tenants or {})
        self._openai_api_key_default = openai_api_key
        self._openai_env_var = openai_env_var
        self._custom_factory = custom_factory
        self._enable_model_cache = enable_model_cache

        self._lock = threading.RLock()
        self._model_cache: Dict[str, BaseChatModel] = {}

    # ----------------------------
    # Tenant management
    # ----------------------------
    def register_tenant(self, cfg: TenantConfig) -> None:
        with self._lock:
            self._tenants[cfg.tenant_id] = cfg
            # Optional: clear cache for this tenant to avoid stale config
            keys_to_del = [k for k in self._model_cache.keys() if k.startswith(cfg.tenant_id + "::")]
            for k in keys_to_del:
                del self._model_cache[k]

    def get_tenant(self, tenant_id: str) -> TenantConfig:
        try:
            return self._tenants[tenant_id]
        except KeyError as e:
            raise KeyError(f"Unknown tenant_id: {tenant_id}") from e

    # ----------------------------
    # Public invoke APIs
    # ----------------------------
    def invoke(
        self,
        tenant_id: str,
        messages: Union[MessageLike, Iterable[MessageLike]],
        *,
        return_message: bool = False,
        **overrides: Any,
    ) -> ChatResult:
        """
        Synchronous invoke.
        - messages: a single MessageLike or an iterable of MessageLike
        - overrides: per-call params (temperature, max_tokens, model, base_url, api_key, etc.)
        """
        model = self._get_chat_model(tenant_id, **overrides)
        lc_messages = self._coerce_messages(messages)
        out_msg = model.invoke(lc_messages)
        return out_msg if return_message else getattr(out_msg, "content", str(out_msg))

    async def ainvoke(
        self,
        tenant_id: str,
        messages: Union[MessageLike, Iterable[MessageLike]],
        *,
        return_message: bool = False,
        **overrides: Any,
    ) -> ChatResult:
        model = self._get_chat_model(tenant_id, **overrides)
        lc_messages = self._coerce_messages(messages)
        out_msg = await model.ainvoke(lc_messages)
        return out_msg if return_message else getattr(out_msg, "content", str(out_msg))

    def stream(
        self,
        tenant_id: str,
        messages: Union[MessageLike, Iterable[MessageLike]],
        **overrides: Any,
    ):
        """
        Streaming generator yielding chunks (LangChain message chunks).
        Caller can do: for chunk in gateway.stream(...): print(chunk.content, end="")
        """
        model = self._get_chat_model(tenant_id, **overrides)
        lc_messages = self._coerce_messages(messages)
        yield from model.stream(lc_messages)

    def with_structured_output(
        self,
        tenant_id: str,
        schema: Any,
        *,
        method: str = "json_schema",
        include_raw: bool = False,
        **overrides: Any,
    ) -> BaseChatModel:
        """
        Returns a *new* model runnable that emits structured outputs.
        Useful for translation + push payload generation.

        schema can be:
        - Pydantic model
        - TypedDict
        - OpenAI function schema (dict)
        """
        model = self._get_chat_model(tenant_id, **overrides)
        if not hasattr(model, "with_structured_output"):
            raise NotImplementedError(f"Provider '{self.get_tenant(tenant_id).provider}' does not support structured output.")
        return model.with_structured_output(schema, method=method, include_raw=include_raw)

    # ----------------------------
    # Internal: model building
    # ----------------------------
    def _get_chat_model(self, tenant_id: str, **overrides: Any) -> BaseChatModel:
        cfg = self.get_tenant(tenant_id)

        provider: ProviderName = overrides.pop("provider", cfg.provider)
        model_name: str = overrides.pop("model", cfg.model)

        # Resolve endpoints/credentials with clear precedence.
        base_url = overrides.pop("base_url", cfg.base_url)
        api_key = overrides.pop("api_key", None) or cfg.api_key or self._resolve_openai_key(tenant_id)

        # Merge default params (tenant) + per-call overrides (temperature, max_tokens, etc.)
        params: Dict[str, Any] = {}
        params.update(cfg.default_params or {})
        params.update(overrides or {})

        cache_key = self._cache_key(
            tenant_id=tenant_id,
            provider=provider,
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            params=cfg.default_params,  # cache should not vary by per-call overrides
        )

        if self._enable_model_cache:
            with self._lock:
                if cache_key in self._model_cache:
                    # For per-call runtime tweaks, use bind() rather than rebuilding.
                    return self._model_cache[cache_key].bind(**params)

        built = self._build_provider_model(
            cfg=cfg,
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            params=params,
        )

        if self._enable_model_cache:
            with self._lock:
                # Store a "base" model without per-call params bound (we already passed params to init),
                # but still safe because callers may override via bind() later.
                self._model_cache[cache_key] = built

        return built

    def _build_provider_model(
        self,
        *,
        cfg: TenantConfig,
        provider: ProviderName,
        model_name: str,
        api_key: Optional[str],
        base_url: Optional[str],
        params: Dict[str, Any],
    ) -> BaseChatModel:
        # Attach tags (tenant/provider) for observability if caller uses LC tracing.
        tags = list(cfg.tags or []) + [f"tenant:{cfg.tenant_id}", f"provider:{provider}"]

        if provider == "openai":
            # langchain-openai
            try:
                from langchain_openai import ChatOpenAI
            except Exception as e:  # pragma: no cover
                raise ImportError("Missing dependency: pip install -U langchain-openai") from e

            if not api_key:
                raise ValueError(
                    f"OpenAI api_key not found for tenant '{cfg.tenant_id}'. "
                    f"Set env {self._openai_env_var} (or {self._openai_env_var}__{cfg.tenant_id.upper()}), "
                    "or pass openai_api_key to LLMGateway, or set TenantConfig.api_key."
                )

            # ChatOpenAI supports api_key/base_url/organization in init args.
            # Extra runtime parameters can also be passed and later overridden via bind().
            return ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                organization=cfg.organization,
                tags=tags,
                **params,
            )

        if provider == "ollama":
            # langchain-ollama (local)
            try:
                from langchain_ollama import ChatOllama
            except Exception as e:  # pragma: no cover
                raise ImportError("Missing dependency: pip install -U langchain-ollama") from e

            return ChatOllama(
                model=model_name,
                base_url=base_url,  # optional, defaults to Ollama client default
                tags=tags,
                **params,
            )

        if provider == "custom":
            if not self._custom_factory:
                raise ValueError("provider='custom' requires LLMGateway(custom_factory=...).")
            built = self._custom_factory(cfg)
            # allow per-call overrides via bind()
            return built.bind(**params)

        raise ValueError(f"Unsupported provider: {provider}")

    # ----------------------------
    # Internal: utilities
    # ----------------------------
    def _resolve_openai_key(self, tenant_id: str) -> Optional[str]:
        """
        Resolution order:
        1) LLMGateway(openai_api_key=...)
        2) env OPENAI_API_KEY__TENANT (uppercased)
        3) env OPENAI_API_KEY
        """
        if self._openai_api_key_default:
            return self._openai_api_key_default

        tenant_suffix = tenant_id.upper()
        per_tenant = os.getenv(f"{self._openai_env_var}__{tenant_suffix}")
        if per_tenant:
            return per_tenant

        return os.getenv(self._openai_env_var)

    def _coerce_messages(self, messages: Union[MessageLike, Iterable[MessageLike]]) -> List[BaseMessage]:
        if isinstance(messages, (str, dict)) or isinstance(messages, BaseMessage) or (
            isinstance(messages, tuple) and len(messages) == 2
        ):
            # Single message -> wrap
            msgs: Iterable[MessageLike] = [messages]  # type: ignore[list-item]
        else:
            msgs = messages  # type: ignore[assignment]

        try:
            return convert_to_messages(msgs)
        except Exception as e:
            raise ValueError(
                "Failed to coerce messages. Supported formats: "
                "str | BaseMessage | (role, content) | {'role':..., 'content':...} | list of these."
            ) from e

    def _cache_key(
        self,
        *,
        tenant_id: str,
        provider: ProviderName,
        model: str,
        base_url: Optional[str],
        api_key: Optional[str],
        params: Optional[Dict[str, Any]],
    ) -> str:
        # Do NOT store raw api_key in cache key; just whether it exists + a short stable marker.
        # If you truly need to separate multiple keys per tenant, pass different tenant_id or set enable_model_cache=False.
        key_marker = "1" if api_key else "0"
        base_url_marker = base_url or ""
        params_marker = str(sorted((params or {}).items()))
        return f"{tenant_id}::{provider}::{model}::{base_url_marker}::k{key_marker}::{params_marker}"
