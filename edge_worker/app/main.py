from fastapi import FastAPI

from app.api import rss_update_router

app = FastAPI(title="edge-worker", version="1.0.0")

@app.get("/healthz")
def healthz():
    return {"ok": True}

app.include_router(rss_update_router, prefix='/v1/rss')