import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401 - registers tables with Base metadata
from .database import Base, engine
from .routers import connectors, credentials, inventory
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

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


@app.on_event("startup")
def on_startup():
    app.state.scheduler = start_scheduler()


@app.get("/api/health")
def health():
    return {"status": "ok"}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "static"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
