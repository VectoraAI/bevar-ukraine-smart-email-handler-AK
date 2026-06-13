from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.api.routes import router
from src.config.logging import setup_logging
from src.config.settings import get_settings
from src.storage.database import get_database

setup_logging()

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    db = get_database()
    db.initialize()
    yield


app = FastAPI(
    title="Bevar Ukraine Email Archive",
    description="Multi-agent email archive analysis system",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

STATIC_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    db = get_database()
    stats = db.get_archive_stats()
    manifest = db.get_manifest()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "manifest": manifest,
        },
    )
