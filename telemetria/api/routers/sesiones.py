"""Listado, carga y validacion de sesiones (`data/raw/`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from telemetria.api.dependencias import cache_actual
from telemetria.api.servicios import adaptador_pipeline as adaptador
from telemetria.api.servicios.cache_memoria import CacheMemoria

router = APIRouter(prefix="/api/sesiones", tags=["sesiones"])


class EntradaCargar(BaseModel):
    nombre: str


def resumen(sesion: adaptador.Sesion) -> dict:
    """Metadatos de una sesion ya procesada."""
    return {
        "id": sesion.id,
        "nombre": sesion.nombre,
        "ruta": sesion.ruta,
        "fs": sesion.fs,
        "n_muestras": int(len(sesion.limpio)),
        "n_ventanas": int(len(sesion.feats)),
        "laps": sesion.laps,
        "vueltas": sesion.vueltas_meta(),
        "tiene_verdad": sesion.verdad is not None,
        "registro": sesion.registro,
        "canales": adaptador.columnas_disponibles(sesion),
    }


@router.get("")
def listar(cache: CacheMemoria = Depends(cache_actual)) -> dict:
    return {"sesiones": cache.listar(), "activa": cache.activa}


@router.get("/activa")
def activa(cache: CacheMemoria = Depends(cache_actual)) -> dict:
    if cache.activa is None:
        raise HTTPException(status_code=404, detail="No hay sesion activa")
    return resumen(cache.activa_o_error())


@router.post("/cargar")
async def cargar(entrada: EntradaCargar, cache: CacheMemoria = Depends(cache_actual)) -> dict:
    """Carga un CSV existente en `data/raw/` por nombre."""
    try:
        sesion = await run_in_threadpool(cache.cargar_archivo, entrada.nombre)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:  # esquema invalido
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return resumen(sesion)


@router.post("/subir")
async def subir(
    archivo: UploadFile = File(...), cache: CacheMemoria = Depends(cache_actual)
) -> dict:
    """Carga un CSV subido desde el navegador (drag & drop, D11)."""
    datos = await archivo.read()
    if not datos:
        raise HTTPException(status_code=422, detail="Archivo vacio")
    try:
        sesion = await run_in_threadpool(
            cache.cargar_contenido, datos, archivo.filename or "subida.csv"
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"CSV invalido: {exc}") from exc
    return resumen(sesion)
