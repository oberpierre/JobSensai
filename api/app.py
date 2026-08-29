"""create_app(): the health route, the jobs and boards routers, and the SPA mount."""

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers.boards import router as boards_router
from api.routers.jobs import router as jobs_router


def _spa_fallback_handler(web_dist_dir: str):
    """Any unmatched non-/api path is a client-side route, so it gets index.html
    rather than a 404. An unmatched /api path stays a genuine JSON 404."""

    async def handler(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
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
