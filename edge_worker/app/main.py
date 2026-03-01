import os

from dotenv import load_dotenv
from fastapi import FastAPI
from app.api import agents_router, line_webhook_router, rss_update_router


load_dotenv()

app = FastAPI(title="edge-worker", version="1.0.0")

@app.get("/healthz")
def healthz():
    return {"ok": True}


# @app.get("/test")
# def test():
#     from app.services.llm_gateway import LLMGateway, TenantConfig
#     from app.config import get_llm_config_by_tenant 

#     gw = LLMGateway()

#     gw.register_tenant(TenantConfig(**get_llm_config_by_tenant('default')))
#     response = gw.invoke("default", [("system", "你是翻譯器，請將使用者提出的句子翻譯成『繁體中文』"), ("human", "Translate: Pneumonoultramicroscopicsilicovolcanoconiosis")]) 
#     return {
#         "response": response
#     }

app.include_router(rss_update_router, prefix='/v1/rss')
app.include_router(agents_router, prefix='/v1/agents')
app.include_router(line_webhook_router, prefix='/v1/line')
