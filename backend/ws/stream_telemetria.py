"""WebSocket de telemetria (`/ws/telemetria`).

Protocolo (D3/D4):
  - Tramas JSON de control: ``ping``, ``ajuste_kalman``, ``ajuste_ridge``,
    ``trama`` (una trama binaria).
  - Tramas binarias (Float32 little-endian) con cabecera JSON previa.

El replay no vive aqui: sobre una sesion grabada el frontend ya tiene las
muestras y reproduce avanzando un cursor. El streaming a 100 Hz se anadira en
la Etapa 3, cuando el dato nazca en el servidor.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.respuestas import dumps
from backend.servicios import analisis
from backend.servicios.serializacion import empaquetar_float32

router = APIRouter()

CANALES_DEFECTO = ("wheel_slip_fl", "temp_core_c_fl", "wheel_load_n_fl", "speed_kmh")
TIPOS = ("ajuste_kalman", "ajuste_ridge", "trama")


@router.websocket("/ws/telemetria")
async def ws_telemetria(websocket: WebSocket) -> None:
    cache = websocket.app.state.cache
    await websocket.accept()
    while True:
        try:
            mensaje = await websocket.receive()
        except WebSocketDisconnect:
            break
        if mensaje.get("type") == "websocket.disconnect":
            break
        texto = mensaje.get("text")
        if texto is None:
            continue
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError:
            await websocket.send_json({"tipo": "error", "mensaje": "JSON invalido"})
            continue
        try:
            await _procesar(websocket, cache, datos)
        except Exception as exc:  # noqa: BLE001 - se informa al cliente
            await websocket.send_json({"tipo": "error", "mensaje": str(exc)})


async def _procesar(websocket: WebSocket, cache, datos: dict) -> None:
    tipo = datos.get("tipo")
    if tipo == "ping":
        await websocket.send_json({"tipo": "pong"})
        return
    if tipo not in TIPOS:
        await websocket.send_json({"tipo": "error", "mensaje": f"tipo desconocido: {tipo}"})
        return

    sesion = cache.activa_o_error()

    if tipo == "ajuste_kalman":
        kc = sesion.cfg["modelo"]["kalman"]
        params = {
            "q_nivel": float(datos.get("q_nivel", kc["q_nivel"])),
            "q_pendiente": float(datos.get("q_pendiente", kc["q_pendiente"])),
            "r": float(datos.get("r", kc["r"])),
            "monotono": bool(datos.get("monotono", kc.get("monotono", True))),
        }
        res = await asyncio.to_thread(analisis.kalman_por_vuelta, sesion, **params)
        await websocket.send_text(dumps({"tipo": "kalman", **res}).decode())
    elif tipo == "ajuste_ridge":
        res = await asyncio.to_thread(
            analisis.ridge_por_vuelta,
            sesion,
            alpha=datos.get("alpha"),
            excluir=tuple(datos.get("excluir") or ()),
        )
        await websocket.send_text(dumps({"tipo": "ridge", **res}).decode())
    elif tipo == "trama":
        await _enviar_trama(websocket, sesion, datos)


def _canales(sesion, datos: dict) -> list[str]:
    canales = datos.get("canales") or [
        c for c in CANALES_DEFECTO if c in sesion.limpio.columns
    ]
    desconocidas = [c for c in canales if c not in sesion.limpio.columns]
    if desconocidas:
        raise ValueError(f"Canales desconocidos: {desconocidas}")
    return list(canales)


async def _enviar_trama(websocket: WebSocket, sesion, datos: dict) -> None:
    canales = _canales(sesion, datos)
    lap = datos.get("lap")
    df = sesion.limpio
    sub = df if lap is None else df[df["lap"] == lap]
    if sub.empty:
        raise ValueError(f"Vuelta {lap} no existe")
    inicio = int(datos.get("inicio", 0))
    fin = datos.get("fin")
    sub = sub.iloc[inicio:fin] if fin is not None else sub.iloc[inicio:]

    t = sub["timestamp_s"].to_numpy(dtype=float)
    await websocket.send_json(
        {
            "tipo": "trama",
            "canales": ["timestamp_s"] + canales,
            "n_muestras": int(len(t)),
            "lap": lap,
            "inicio": inicio,
            "dtype": "float32",
        }
    )
    filas = [t] + [sub[c].to_numpy(dtype=float) for c in canales]
    await websocket.send_bytes(empaquetar_float32(filas))
