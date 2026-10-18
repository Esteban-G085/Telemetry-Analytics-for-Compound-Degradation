"""Inferencia y re-entrenamiento de modelos (Ridge y Kalman)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from telemetria.api.dependencias import cache_actual
from telemetria.api.servicios import analisis
from telemetria.api.servicios.cache_memoria import CacheMemoria

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


class SensorCaido(BaseModel):
    canal: str
    rueda: str | None = None


class EntradaSensores(BaseModel):
    caidos: list[SensorCaido] = []


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


@router.post("/sensores")
async def sensores(entrada: EntradaSensores, cache: CacheMemoria = Depends(cache_actual)) -> dict:
    """MAE de Ridge al desconectar canales (Vista 5, simulación de fallo)."""
    sesion = _sesion(cache)
    caidos = [{"canal": s.canal, "rueda": s.rueda} for s in entrada.caidos]
    try:
        return await run_in_threadpool(analisis.sensores, sesion, caidos)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/features")
async def features(cache: CacheMemoria = Depends(cache_actual)) -> dict:
    """Lista de features numericas del modelo (para los selectores de §3.2)."""
    sesion = _sesion(cache)
    return {"features": analisis.lista_features(sesion)}


@router.get("/dispersion")
async def dispersion(
    x: str,
    y: str = "degradacion",
    cache: CacheMemoria = Depends(cache_actual),
) -> dict:
    """Dispersion por vuelta de dos features (o de una vs. la degradacion)."""
    sesion = _sesion(cache)
    try:
        return await run_in_threadpool(analisis.dispersion, sesion, x, y)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/correlacion")
async def correlacion(
    features: str | None = None,
    cache: CacheMemoria = Depends(cache_actual),
) -> dict:
    """Matriz de correlacion entre features y la degradacion."""
    sesion = _sesion(cache)
    lista = [f for f in (features or "").split(",") if f] or None
    try:
        return await run_in_threadpool(analisis.correlacion, sesion, lista)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
