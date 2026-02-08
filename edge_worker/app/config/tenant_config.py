import os
from typing import Literal

ProviderName = Literal["openai", "ollama", "custom"]


def get_llm_config_by_tenant(tenat_id:str):
    _tenant_map = {
        "default": {
            "tenant_id": "default",
            "model": "gpt-4o-mini",
            "provider": "openai",
            "api_key": os.getenv("OPENAI_API_KEY")
        }
    }
    result = _tenant_map[tenat_id]
    return result
