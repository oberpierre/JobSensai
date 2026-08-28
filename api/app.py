"""create_app(): the health route and the SPA mount."""

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException


def _spa_fallback_handler(web_dist_dir: str):
    """Any unmatched non-/api path is a client-side route, so it gets index.html
    rather than a 404; an unmatched /api path stays a genuine JSON 404."""

    async def handler(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        index_path = os.path.join(web_dist_dir, "index.html")
        return FileResponse(index_path)

    return handler


def create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    web_dist_dir = os.environ.get("WEB_DIST_DIR")
    if web_dist_dir and os.path.isfile(os.path.join(web_dist_dir, "index.html")):
        app.mount("/", StaticFiles(directory=web_dist_dir, html=True), name="spa")
        app.add_exception_handler(404, _spa_fallback_handler(web_dist_dir))

    return app
