"""Aplicacion FastAPI: REST + WebSocket + montaje de estaticos.

Se crea con :func:`crear_app` para poder inyectar otra carpeta `data/raw` o
overrides en los tests. El modulo expone `app` listo para uvicorn.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from telemetria.api.respuestas import RespuestaJSON
from telemetria.api.routers import configuracion, modelos, sesiones, telemetria, vivo
from telemetria.api.servicios.cache_memoria import RAIZ, CacheMemoria
from telemetria.api.servicios.vivo import VivoSesion
from telemetria.api.ws import stream_telemetria, stream_vivo

VERSION = "2.0.0"


def crear_app(
    dir_raw: str | Path | None = None,
    overrides: dict | None = None,
    dir_vivo: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Telemetry Analytics API",
        version=VERSION,
        default_response_class=RespuestaJSON,  # orjson: serializa numpy, NaN->null
    )
    app.state.cache = CacheMemoria(dir_raw=dir_raw, overrides=overrides)
    app.state.vivo = VivoSesion(app.state.cache, dir_vivo=dir_vivo)

    # CORS solo hace falta en desarrollo (Vite en otro puerto); en la app de
    # escritorio el frontend se sirve desde el mismo origen.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["salud"])
    def salud() -> dict:
        return {"estado": "ok", "version": VERSION}

    app.include_router(sesiones.router)
    app.include_router(telemetria.router)
    app.include_router(modelos.router)
    app.include_router(configuracion.router)
    app.include_router(vivo.router)
    app.include_router(stream_telemetria.router)
    app.include_router(stream_vivo.router)

    dist = RAIZ / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = crear_app()
