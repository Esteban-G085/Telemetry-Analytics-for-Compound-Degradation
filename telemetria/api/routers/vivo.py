"""Endpoints de captura/analisis en vivo (Etapa 3).

  - ``POST /api/vivo/iniciar``  arranca la fuente (AC o CSV en modo seco)
  - ``POST /api/vivo/detener``  para la captura y cierra el CSV
  - ``GET  /api/vivo/estado``   degradacion actual, prediccion, features, espectro
  - ``GET  /api/vivo/ventana``  ultimas N muestras (osciloscopio)
  - ``GET  /api/vivo/sesiones`` CSV disponibles para el modo seco
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from telemetria.api.dependencias import vivo_actual
from telemetria.api.servicios.vivo import FUENTES, VivoSesion

router = APIRouter(prefix="/api/vivo", tags=["vivo"])


class EntradaIniciar(BaseModel):
    fuente: str = "ac"
    archivo: str | None = None
    ritmo_hz: float | None = None
    bucle: bool = False


@router.post("/iniciar")
async def iniciar(
    entrada: EntradaIniciar, vivo: VivoSesion = Depends(vivo_actual)
) -> dict:
    if entrada.fuente not in FUENTES:
        raise HTTPException(status_code=422, detail=f"fuente debe ser una de {FUENTES}")
    try:
        return await run_in_threadpool(
            vivo.iniciar,
            entrada.fuente,
            entrada.archivo,
            entrada.ritmo_hz,
            entrada.bucle,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/detener")
async def detener(vivo: VivoSesion = Depends(vivo_actual)) -> dict:
    return await run_in_threadpool(vivo.detener)


@router.get("/estado")
def estado(vivo: VivoSesion = Depends(vivo_actual)) -> dict:
    return vivo.estado()


@router.get("/ventana")
def ventana(
    n: int | None = Query(None, ge=1, le=12000),
    canales: str | None = None,
    vivo: VivoSesion = Depends(vivo_actual),
) -> dict:
    cols = [c.strip() for c in canales.split(",") if c.strip()] if canales else None
    return vivo.ventana(n=n, canales=cols)


@router.get("/sesiones")
def sesiones(vivo: VivoSesion = Depends(vivo_actual)) -> dict:
    return {"sesiones": vivo.listar()}


@router.get("/layout")
def layout() -> dict:
    """Comprueba si AC esta publicando datos y si el layout es plausible."""
    from telemetria.adquisicion.ac_info import verificar_layout

    info = verificar_layout()
    return {
        "disponible": info.disponible,
        "packet_id": info.packet_id,
        "layout_ok": info.ok,
        "checks": info.checks,
        "error": info.error,
    }
