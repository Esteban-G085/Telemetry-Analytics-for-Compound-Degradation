"""WebSocket de captura en vivo (``/api/vivo/stream``).

A diferencia de ``/ws/telemetria`` (que reacciona a comandos sobre una sesion
grabada), este canal **empuja** tramas periodicas (~10 Hz, D8) con el estado del
motor en vivo y la ventana reciente para el osciloscopio. El cliente puede
ajustar los canales y el tamano de ventana enviando JSON de control.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from telemetria.api.respuestas import dumps

router = APIRouter()

CANALES_DEFECTO = (
    "speed_kmh",
    "throttle",
    "brake",
    "wheel_slip_fl",
    "temp_core_c_fl",
    "wheel_load_n_fl",
    "pressure_psi_fl",
)


def _config_canal(datos: dict, actual: dict) -> dict:
    if "canales" in datos and datos["canales"]:
        actual["canales"] = [str(c) for c in datos["canales"]]
    if "n" in datos and datos["n"]:
        actual["n"] = max(1, min(12000, int(datos["n"])))
    return actual


@router.websocket("/api/vivo/stream")
async def ws_vivo(websocket: WebSocket) -> None:
    await websocket.accept()
    app = websocket.app
    vivo = app.state.vivo

    try:
        fps = float(app.state.cache.config().get("vivo", {}).get("fps_ws", 10.0))
    except Exception:  # noqa: BLE001
        fps = 10.0
    periodo = 1.0 / max(1.0, fps)

    ajustes = {"canales": list(CANALES_DEFECTO), "n": None}

    try:
        while True:
            try:
                texto = await asyncio.wait_for(websocket.receive_text(), timeout=periodo)
            except asyncio.TimeoutError:
                texto = None
            except WebSocketDisconnect:
                break

            if texto:
                try:
                    datos = json.loads(texto)
                except json.JSONDecodeError:
                    datos = None
                if datos is not None:
                    if datos.get("tipo") == "ping":
                        await websocket.send_text(dumps({"tipo": "pong"}).decode())
                        continue
                    ajustes = _config_canal(datos, ajustes)

            estado = vivo.estado()
            ventana = vivo.ventana(n=ajustes["n"], canales=ajustes["canales"])
            await websocket.send_text(
                dumps({"tipo": "vivo", **estado, "ventana": ventana}).decode()
            )
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        # el socket se cerro mientras enviabamos
        pass
