"""Serve the built War Room SPA from the API container (same origin: no CORS, no second app)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Static files that fall back to index.html so client-side routes survive a refresh.

    API paths never fall back: an unknown /api/... stays a 404.
    """

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not path.startswith("api"):
            return await super().get_response("index.html", scope)
        return response


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    if not (dist / "index.html").is_file():
        return False
    app.mount("/", SPAStaticFiles(directory=dist, html=True), name="frontend")
    return True
