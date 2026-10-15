"""Lectura, actualizacion y exportacion de la configuracion."""

from __future__ import annotations

import yaml
from fastapi import APIRouter, Body, Depends
from fastapi.responses import PlainTextResponse

from backend.dependencias import cache_actual
from backend.servicios.cache_memoria import CacheMemoria

router = APIRouter(prefix="/api/config", tags=["configuracion"])


@router.get("")
def leer(cache: CacheMemoria = Depends(cache_actual)) -> dict:
    return {"config": cache.config()}


@router.post("")
def actualizar(
    overrides: dict = Body(..., description="Overrides anidados sobre config.yaml"),
    cache: CacheMemoria = Depends(cache_actual),
) -> dict:
    """Actualiza parametros (los usaran las proximas sesiones cargadas)."""
    return {"config": cache.actualizar_overrides(overrides)}


@router.delete("")
def reiniciar(cache: CacheMemoria = Depends(cache_actual)) -> dict:
    """Restablece la configuración a los valores de fábrica (§3.4)."""
    return {"config": cache.reiniciar_overrides()}


@router.get("/exportar", response_class=PlainTextResponse)
def exportar(cache: CacheMemoria = Depends(cache_actual)) -> str:
    """Devuelve la configuracion activa como YAML interoperable con `main.py` (D10)."""
    return yaml.safe_dump(cache.config(), allow_unicode=True, sort_keys=False)
