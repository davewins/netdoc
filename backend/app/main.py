import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401 - registers tables with Base metadata
from .database import Base, engine
from .migrations import run_additive_migrations
from .routers import connectors, credentials, inventory, links, topology
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

run_additive_migrations(engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="netdoc")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory.router)
app.include_router(credentials.router)
app.include_router(connectors.router)
app.include_router(links.router)
app.include_router(topology.router)


@app.on_event("startup")
def on_startup():
    app.state.scheduler = start_scheduler()


@app.get("/api/health")
def health():
    return {"status": "ok"}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "static"
if FRONTEND_DIST.exists():
    app.mount(
        "/app-assets", StaticFiles(directory=str(FRONTEND_DIST / "app-assets")), name="frontend-assets"
    )

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # Anything that isn't an API route or a built asset is a
        # client-side (React Router) path - always serve index.html and
        # let the SPA's router take over, otherwise a direct link to or
        # refresh on e.g. /inventory 404s.
        if full_path.startswith("api/"):
            raise HTTPException(404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
