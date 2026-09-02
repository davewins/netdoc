import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, mcp_server, models  # noqa: F401 - models registers tables with Base metadata
from .database import Base, engine
from .migrations import run_additive_migrations
from .routers import connectors, credentials, inventory, links, reports, topology
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

run_additive_migrations(engine)
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = start_scheduler()
    # The MCP session manager's context has to be entered by whatever ASGI
    # app actually owns the top-level lifespan - mounting mcp_server's own
    # streamable_http_app() below does NOT get its internal lifespan run for
    # free, since Starlette doesn't propagate lifespan events into a
    # sub-app mounted with .mount(). This is the one thing every FastMCP
    # "embed in an existing app" example wires up by hand.
    logging.getLogger(__name__).info(
        "MCP server mounted at /mcp - bearer token at %s (or set NETDOC_MCP_TOKEN)", config.MCP_TOKEN_PATH
    )
    async with mcp_server.mcp.session_manager.run():
        yield


app = FastAPI(title="netdoc", lifespan=lifespan)

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
app.include_router(reports.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# The rest of the API has no authentication at all (see CLAUDE.md) - fine
# for a homelab tool whose UI is only ever hit from a trusted LAN, but /mcp
# is meant to be reachable more broadly (any MCP client, any machine on the
# network), and it exposes a couple of mutating actions (poll-now, confirm/
# reject link). A single shared bearer token, generated on first run and
# persisted the same way as the credential-encryption master key, is the
# minimum needed so that endpoint isn't wide open to anyone who can reach
# this host's port.
#
# This is a plain ASGI wrapper rather than a FastAPI/Starlette
# @app.middleware("http") - that flavor runs through BaseHTTPMiddleware,
# which buffers/reshapes responses in ways known to conflict with streaming
# responses, and the MCP Streamable HTTP transport's responses can be a
# held-open SSE stream. A bare ASGI callable passes scope/receive/send
# straight through untouched once the auth check passes, so it can't
# interfere with that streaming.
class _MCPAuthGate:
    def __init__(self, inner_app, token: str):
        self._inner_app = inner_app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization", b"").decode("latin-1") != self._expected:
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self._inner_app(scope, receive, send)


app.mount("/mcp", _MCPAuthGate(mcp_server.mcp.streamable_http_app(), mcp_server.MCP_TOKEN))


@app.api_route("/mcp", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def _mcp_trailing_slash_redirect():
    # Starlette's Mount above only matches "/mcp/..." (its path regex
    # requires the slash) - a bare "/mcp" would otherwise fall through to
    # the SPA catch-all further down and 405 on anything but GET, which is
    # a nasty surprise since "/mcp" (no trailing slash) is the more natural
    # way to type the URL into an MCP client config. 307 preserves the
    # method and body across the redirect, unlike 301/302.
    return RedirectResponse(url="/mcp/", status_code=307)


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
