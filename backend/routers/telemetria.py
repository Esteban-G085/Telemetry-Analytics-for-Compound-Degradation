"""Telemetría procesada por vuelta / stint, crudo vs. limpio, y espectro de Welch."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencias import cache_actual
from backend.servicios import adaptador_pipeline as adaptador
from backend.servicios import analisis
from backend.servicios.cache_memoria import CacheMemoria
from backend.servicios.serializacion import indices_minmax, lista_numerica
from src.config import canales_fisicos

router = APIRouter(prefix="/api/telemetria", tags=["telemetria"])

CANALES_DEFECTO = (
    "wheel_slip_fl",
    "temp_core_c_fl",
    "wheel_load_n_fl",
    "pressure_psi_fl",
    "speed_kmh",
)


def _sesion(cache: CacheMemoria):
    try:
        return cache.activa_o_error()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _parsear_canales(canales: str | None, columnas) -> list[str]:
    if not canales:
        return [c for c in CANALES_DEFECTO if c in columnas]
    cols = [c.strip() for c in canales.split(",") if c.strip()]
    desconocidas = [c for c in cols if c not in columnas]
    if desconocidas:
        raise HTTPException(status_code=400, detail=f"Canales desconocidos: {desconocidas}")
    return cols


@router.get("/canales")
def canales(cache: CacheMemoria = Depends(cache_actual)) -> dict:
    sesion = _sesion(cache)
    return {"canales": adaptador.columnas_disponibles(sesion), "fisicas": canales_fisicos()}


@router.get("/vuelta/{lap}")
def vuelta(
    lap: int,
    canales: str | None = None,
    crudo: bool = Query(False, description="Incluye la señal remuestreada cruda"),
    max_puntos: int = Query(20000, ge=50, description="Reducción min/max si se supera"),
    cache: CacheMemoria = Depends(cache_actual),
) -> dict:
    """Arrays planos JSON de una vuelta (D4: por vuelta va en JSON)."""
    sesion = _sesion(cache)
    if lap not in sesion.laps:
        raise HTTPException(status_code=404, detail=f"Vuelta {lap} no existe en la sesión")
    return _payload(sesion, lap, canales, crudo, max_puntos)


@router.get("/stint")
def stint(
    canales: str | None = None,
    crudo: bool = Query(False, description="Incluye la señal remuestreada cruda"),
    max_puntos: int = Query(20000, ge=50, description="Reducción min/max si se supera"),
    cache: CacheMemoria = Depends(cache_actual),
) -> dict:
    """Stint completo con min-max bucket downsampling (§3.1, Vista 1)."""
    sesion = _sesion(cache)
    return _payload(sesion, None, canales, crudo, max_puntos)


def _payload(sesion, lap: int | None, canales: str | None, crudo: bool, max_puntos: int) -> dict:
    """Construye el JSON de telemetría para una vuelta o para el stint entero."""
    df = sesion.limpio
    mascara_lap = (
        df["lap"].to_numpy() == lap if lap is not None else np.ones(len(df), dtype=bool)
    )
    if lap is not None and not mascara_lap.any():
        raise HTTPException(status_code=404, detail=f"Vuelta {lap} no existe en la sesión")

    cols = _parsear_canales(canales, df.columns)
    sub = df.loc[mascara_lap]
    t = sub["timestamp_s"].to_numpy(dtype=float)
    series = {c: sub[c].to_numpy(dtype=float) for c in cols}
    valido = sub["valido"].to_numpy(dtype=bool) if "valido" in sub.columns else np.ones(len(sub), bool)

    crudo_series = None
    if crudo and sesion.crudo is not None and len(sesion.crudo) == len(df):
        csub = sesion.crudo.loc[mascara_lap]
        crudo_series = {c: csub[c].to_numpy(dtype=float) for c in cols}

    # --- reducción min/max (misma selección para todas las series) ---
    idx = indices_minmax(series[cols[0]], max_puntos) if cols else None
    pos = {int(o): i for i, o in enumerate(idx)} if idx is not None else None

    def _recorte(arr):
        return arr[idx] if idx is not None else arr

    t_out = _recorte(t)
    series_out = {c: lista_numerica(_recorte(series[c])) for c in cols}
    crudo_out = (
        {c: lista_numerica(_recorte(crudo_series[c])) for c in cols} if crudo_series else None
    )
    valido_out = _recorte(valido).astype(bool).tolist()

    # --- outliers (índices dentro del array devuelto) ---
    outliers: dict[str, list[int]] = {}
    for c in cols:
        m = sesion.mascara_outliers.get(c)
        if m is None or len(m) != len(df):
            continue
        idx_lap = np.flatnonzero(m[mascara_lap])
        if idx_lap.size == 0:
            continue
        if pos is not None:
            idx_lap = [pos[int(i)] for i in idx_lap if int(i) in pos]
        outliers[c] = [int(i) for i in idx_lap]

    # --- KPIs de calidad ---
    kpis = {
        "n_vuelta": int(mascara_lap.sum()),
        "n_invalidos": int((~valido).sum()),
        "outliers_total": int(sum(len(v) for v in outliers.values())),
        "atenuacion_db": {
            c: _atenuacion(series[c], crudo_series[c] if crudo_series else None) for c in cols
        },
    }

    return {
        "sesion": sesion.id,
        "lap": lap,
        "fs": sesion.fs,
        "n_total": int(mascara_lap.sum()),
        "n": int(len(t_out)),
        "downsample": idx is not None,
        "t": lista_numerica(t_out, 3),
        "series": series_out,
        "crudo": crudo_out,
        "valido": valido_out,
        "outliers": outliers,
        "kpis": kpis,
    }


def _atenuacion(limpio: np.ndarray, crudo: np.ndarray | None) -> float | None:
    """Atenuación de varianza del ruido en dB: 10*log10(var_cruda/var_limpia)."""
    if crudo is None:
        return None
    a = crudo[np.isfinite(crudo)]
    b = limpio[np.isfinite(limpio)]
    if a.size < 2 or b.size < 2:
        return None
    var_a, var_b = float(np.var(a)), float(np.var(b))
    if var_b <= 0:
        return None
    return round(10.0 * np.log10(max(var_a, 1e-20) / var_b), 2)


@router.get("/espectro")
def espectro(
    canal: str,
    lap: int | None = None,
    nperseg: int | None = Query(None, ge=16, le=2048),
    cache: CacheMemoria = Depends(cache_actual),
) -> dict:
    sesion = _sesion(cache)
    try:
        return analisis.espectro(sesion, canal, lap=lap, nperseg=nperseg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
