"""create_app(): the health route, the jobs and boards routers, and the SPA mount."""

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers.boards import router as boards_router
from api.routers.jobs import router as jobs_router


def _spa_fallback_handler(web_dist_dir: str):
    """An unmatched path falls into one of four cases, in order. /api or under it
    stays a genuine JSON 404. Under /assets, Vite's hashed-filename build output, a
    miss is also a JSON 404, since it means a stale client asking for a file this
    build never shipped rather than a route to resolve. A route path missing its
    trailing slash redirects to the canonical form that carries one. Anything else
    is index.html, which the redirect target above always reaches directly."""

    async def handler(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if path == "/api" or path.startswith("/api/") or path.startswith("/assets/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if not path.endswith("/"):
            location = f"{path}/"
            if request.url.query:
                location = f"{location}?{request.url.query}"
            return RedirectResponse(location, status_code=307)
        index_path = os.path.join(web_dist_dir, "index.html")
        return FileResponse(index_path)

    return handler


def create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(jobs_router)
    app.include_router(boards_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Every router goes above this mount: the SPA catches "/" and anything a route
    # registered after it would shadow that route with index.html instead.
    web_dist_dir = os.environ.get("WEB_DIST_DIR")
    if web_dist_dir and os.path.isfile(os.path.join(web_dist_dir, "index.html")):
        app.mount("/", StaticFiles(directory=web_dist_dir, html=True), name="spa")
        app.add_exception_handler(404, _spa_fallback_handler(web_dist_dir))

    return app
