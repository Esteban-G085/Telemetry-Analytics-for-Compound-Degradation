"""Latencia y tramas contra un servidor uvicorn real (§8 y §12 del plan).

El `TestClient` de FastAPI corre en proceso y de forma síncrona: no mide red de
verdad. Aquí se levanta `uvicorn` sobre un puerto libre y se habla con él usando
un cliente `websockets` real, tal como lo hará la app de escritorio (§6.1).

Objetivos (plan §12): REST con caché caliente <20 ms; Kalman por WS <20-50 ms;
re-fit de Ridge por WS <100 ms.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time

import numpy as np
import pytest

from tests.conftest import OVERRIDES


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _medir(datos_demo) -> dict:
    import httpx
    import uvicorn
    import websockets

    from telemetria.api.app import crear_app
    from tests.ayudas import decodificar_float32

    puerto = _puerto_libre()
    app = crear_app(dir_raw=datos_demo, overrides=OVERRIDES)
    servidor = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning")
    )
    tarea = asyncio.create_task(servidor.serve())
    base = f"http://127.0.0.1:{puerto}"
    med: dict = {}

    try:
        async with httpx.AsyncClient(timeout=120) as cl:
            for _ in range(400):
                if servidor.started:
                    break
                await asyncio.sleep(0.05)
            assert servidor.started, "uvicorn no arrancó"

            assert (await cl.get(f"{base}/health")).status_code == 200
            r = await cl.post(f"{base}/api/sesiones/cargar", json={"nombre": "demo.csv"})
            assert r.status_code == 200, r.text

            # REST con caché caliente (una llamada previa + mediana de 20)
            await cl.get(f"{base}/api/telemetria/vuelta/1")
            latencias = []
            for _ in range(20):
                t0 = time.perf_counter()
                assert (await cl.get(f"{base}/api/telemetria/vuelta/1")).status_code == 200
                latencias.append((time.perf_counter() - t0) * 1000.0)
            med["rest_ms"] = float(np.median(latencias))

        async with websockets.connect(f"ws://127.0.0.1:{puerto}/ws/telemetria") as ws:
            t0 = time.perf_counter()
            await ws.send('{"tipo": "ping"}')
            assert json.loads(await ws.recv())["tipo"] == "pong"
            med["ping_ms"] = (time.perf_counter() - t0) * 1000.0

            latencias = []
            for _ in range(10):
                t0 = time.perf_counter()
                await ws.send(
                    '{"tipo": "ajuste_kalman", "q_nivel": 1e-4, "q_pendiente": 1e-5, "r": 1e-3}'
                )
                j = json.loads(await ws.recv())
                latencias.append((time.perf_counter() - t0) * 1000.0)
            assert j["tipo"] == "kalman" and len(j["pred"]) > 0
            med["kalman_ms"] = float(np.median(latencias))

            latencias = []
            for _ in range(5):
                t0 = time.perf_counter()
                await ws.send('{"tipo": "ajuste_ridge", "alpha": 1.0}')
                j = json.loads(await ws.recv())
                latencias.append((time.perf_counter() - t0) * 1000.0)
            assert j["tipo"] == "ridge" and j["alpha"] == 1.0
            med["ridge_ms"] = float(np.median(latencias))

            # trama binaria: cabecera JSON + Float32 (D4)
            await ws.send(
                '{"tipo": "trama", "lap": 1, "canales": ["wheel_slip_fl", "speed_kmh"], '
                '"inicio": 0, "fin": 500}'
            )
            cabecera = json.loads(await ws.recv())
            datos = await ws.recv()
            esperado = cabecera["n_muestras"] * len(cabecera["canales"]) * 4
            assert len(datos) == esperado
            matriz = decodificar_float32(datos, n_canales=len(cabecera["canales"]))
            assert matriz.shape == (len(cabecera["canales"]), cabecera["n_muestras"])
            med["trama_bytes"] = len(datos)
            med["trama_forma"] = list(matriz.shape)
    finally:
        servidor.should_exit = True
        await tarea

    return med


def test_latencia_contra_uvicorn_real(datos_demo, capsys):
    pytest.importorskip("websockets")
    med = asyncio.run(_medir(datos_demo))

    with capsys.disabled():
        print(
            "\n[carga/latencia] "
            f"REST={med['rest_ms']:.1f} ms | "
            f"ping={med['ping_ms']:.1f} ms | "
            f"Kalman={med['kalman_ms']:.1f} ms | "
            f"Ridge={med['ridge_ms']:.1f} ms | "
            f"trama={med['trama_bytes']} B {med['trama_forma']}"
        )

    # §12: REST <20 ms con caché caliente y Kalman <20 ms (margen en CI)
    assert med["rest_ms"] < 20.0
    assert med["kalman_ms"] < 50.0
    # §12: el re-fit de Ridge completa el ciclo en <100 ms
    assert med["ridge_ms"] < 100.0
