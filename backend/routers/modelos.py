"""Inferencia y re-entrenamiento de modelos (Ridge y Kalman)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.dependencias import cache_actual
from backend.servicios import analisis
from backend.servicios.cache_memoria import CacheMemoria

router = APIRouter(prefix="/api/modelos", tags=["modelos"])


class EntradaKalman(BaseModel):
    q_nivel: float | None = None
    q_pendiente: float | None = None
    r: float | None = None
    monotono: bool | None = None


class EntradaRidge(BaseModel):
    alpha: float | None = None
    excluir: list[str] = []


class EntradaRobustez(BaseModel):
    snr_db: list[float] | None = None


def _sesion(cache: CacheMemoria):
    try:
        return cache.activa_o_error()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _kalman_cfg(sesion, entrada: EntradaKalman) -> dict:
    kc = sesion.cfg["modelo"]["kalman"]
    return {
        "q_nivel": float(entrada.q_nivel if entrada.q_nivel is not None else kc["q_nivel"]),
        "q_pendiente": float(
            entrada.q_pendiente if entrada.q_pendiente is not None else kc["q_pendiente"]
        ),
        "r": float(entrada.r if entrada.r is not None else kc["r"]),
        "monotono": bool(entrada.monotono if entrada.monotono is not None else kc.get("monotono", True)),
    }


@router.post("/kalman/estimar")
async def kalman(entrada: EntradaKalman, cache: CacheMemoria = Depends(cache_actual)) -> dict:
    sesion = _sesion(cache)
    params = _kalman_cfg(sesion, entrada)
    try:
        return await run_in_threadpool(analisis.kalman_por_vuelta, sesion, **params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ridge/ajustar")
async def ridge(entrada: EntradaRidge, cache: CacheMemoria = Depends(cache_actual)) -> dict:
    sesion = _sesion(cache)
    try:
        return await run_in_threadpool(
            analisis.ridge_por_vuelta,
            sesion,
            alpha=entrada.alpha,
            excluir=tuple(entrada.excluir),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/robustez")
async def robustez(entrada: EntradaRobustez, cache: CacheMemoria = Depends(cache_actual)) -> dict:
    """MAE de Ridge contra ruido inyectado en el input (Vista 5, §3.5)."""
    sesion = _sesion(cache)
    try:
        filas = await run_in_threadpool(analisis.robustez_snr, sesion, entrada.snr_db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "snr_db": [f["snr_db"] for f in filas],
        "mae": [f["mae"] for f in filas],
        "filas": filas,
    }
