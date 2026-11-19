from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.clients.keitaro import KeitaroAPIError, KeitaroClient
from app.config import settings
from app.routers import api, pages
from app.services.references import ReferenceCache

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = KeitaroClient()
    app.state.keitaro_client = client
    app.state.references = ReferenceCache(client, settings.offer_cache_ttl)
    try:
        yield
    finally:
        await client.aclose()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(pages.router)
app.include_router(api.router)


@app.exception_handler(KeitaroAPIError)
async def keitaro_error_handler(request: Request, exc: KeitaroAPIError) -> JSONResponse:
    status = exc.status_code if 400 <= exc.status_code <= 599 else 502
    return JSONResponse(status_code=status, content=exc.as_dict())
