"""Tests del WebSocket de telemetria (Etapa 2)."""

from __future__ import annotations

import numpy as np

from tests.ayudas import decodificar_float32


def test_ws_ping(cliente):
    with cliente.websocket_connect("/ws/telemetria") as ws:
        ws.send_json({"tipo": "ping"})
        assert ws.receive_json() == {"tipo": "pong"}


def test_ws_tipo_desconocido(cliente):
    with cliente.websocket_connect("/ws/telemetria") as ws:
        ws.send_json({"tipo": "magia"})
        assert ws.receive_json()["tipo"] == "error"


def test_ws_ajuste_kalman(cliente):
    with cliente.websocket_connect("/ws/telemetria") as ws:
        ws.send_json({"tipo": "ajuste_kalman", "q_nivel": 1e-4, "q_pendiente": 1e-5, "r": 1e-3})
        j = ws.receive_json()
        assert j["tipo"] == "kalman"
        assert len(j["pred"]) == len(j["laps_test"])
        assert len(j["banda_inf"]) == len(j["pred"])


def test_ws_ajuste_ridge(cliente):
    with cliente.websocket_connect("/ws/telemetria") as ws:
        ws.send_json({"tipo": "ajuste_ridge", "alpha": 0.1})
        j = ws.receive_json()
        assert j["tipo"] == "ridge"
        assert j["alpha"] == 0.1


def test_ws_trama_binaria(cliente):
    with cliente.websocket_connect("/ws/telemetria") as ws:
        ws.send_json(
            {
                "tipo": "trama",
                "lap": 1,
                "canales": ["wheel_slip_fl", "speed_kmh"],
                "inicio": 0,
                "fin": 200,
            }
        )
        cabecera = ws.receive_json()
        assert cabecera["tipo"] == "trama"
        assert cabecera["canales"] == ["timestamp_s", "wheel_slip_fl", "speed_kmh"]
        assert cabecera["n_muestras"] == 200

        datos = ws.receive_bytes()
        matriz = decodificar_float32(datos, n_canales=len(cabecera["canales"]))
        assert matriz.shape == (3, 200)
        assert np.isfinite(matriz).all()
        # el tiempo arranca en 0 y avanza 1/fs (float32: tolerancia)
        assert abs(float(matriz[0, 1] - matriz[0, 0]) - 0.01) < 1e-4


def test_ws_sin_sesion_activa(datos_demo):
    """Sin sesion cargada el WS responde un error controlado, no un crash."""
    from fastapi.testclient import TestClient

    from telemetria.api.app import crear_app

    app = crear_app(dir_raw=datos_demo)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/telemetria") as ws:
            ws.send_json({"tipo": "ping"})
            assert ws.receive_json()["tipo"] == "pong"
            ws.send_json({"tipo": "ajuste_kalman"})
            assert ws.receive_json()["tipo"] == "error"
