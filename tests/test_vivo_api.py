"""Tests de los endpoints en vivo (Etapa 3)."""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def cliente_vivo(datos_demo, tmp_path_factory):
    """App con `data/raw` de demo y una carpeta `data/vivo` temporal."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from telemetria.api.app import crear_app

    dir_vivo = tmp_path_factory.mktemp("vivo")
    app = crear_app(dir_raw=datos_demo, dir_vivo=dir_vivo)
    with TestClient(app) as c:
        yield c, dir_vivo


def _esperar_muestras(c, minimo=1, timeout=5.0):
    limite = time.time() + timeout
    estado = c.get("/api/vivo/estado").json()
    while estado.get("n", 0) < minimo and time.time() < limite:
        time.sleep(0.05)
        estado = c.get("/api/vivo/estado").json()
    return estado


def test_estado_inicial_inactivo(cliente_vivo):
    c, _ = cliente_vivo
    estado = c.get("/api/vivo/estado").json()
    assert estado["activo"] is False
    assert estado["n"] == 0


def test_iniciar_seco_y_ventana(cliente_vivo):
    c, _ = cliente_vivo
    r = c.post(
        "/api/vivo/iniciar",
        json={"fuente": "seco", "archivo": "demo.csv", "ritmo_hz": 0},
    )
    assert r.status_code == 200, r.text
    estado = _esperar_muestras(c)
    assert estado["n"] > 0
    assert estado["fuente"] == "seco"

    v = c.get(
        "/api/vivo/ventana", params={"canales": "speed_kmh,wheel_slip_fl", "n": 100}
    ).json()
    assert v["n"] > 0
    assert set(v["series"]) == {"speed_kmh", "wheel_slip_fl"}
    assert len(v["t"]) == v["n"]


def test_detener_cierra_el_csv(cliente_vivo):
    c, dir_vivo = cliente_vivo
    c.post("/api/vivo/iniciar", json={"fuente": "seco", "archivo": "demo.csv", "ritmo_hz": 0})
    _esperar_muestras(c)
    estado = c.post("/api/vivo/detener").json()
    assert estado["activo"] is False

    sesiones = c.get("/api/vivo/sesiones").json()["sesiones"]
    nombres = {s["nombre"] for s in sesiones}
    assert any(n.startswith("demo_") for n in nombres)
    # el CSV registrado se abre y trae al menos cabecera + filas
    registrado = next(n for n in nombres if n.startswith("demo_"))
    assert (dir_vivo / registrado).exists()


def test_fuente_invalida(cliente_vivo):
    c, _ = cliente_vivo
    r = c.post("/api/vivo/iniciar", json={"fuente": "nope"})
    assert r.status_code == 422


def test_archivo_inexistente(cliente_vivo):
    c, _ = cliente_vivo
    r = c.post("/api/vivo/iniciar", json={"fuente": "seco", "archivo": "no_existe.csv"})
    assert r.status_code == 404


def test_layout_reporta_sin_ac(cliente_vivo):
    c, _ = cliente_vivo
    j = c.get("/api/vivo/layout").json()
    assert "disponible" in j
    assert "layout_ok" in j


def test_ws_vivo_emite_tramas(cliente_vivo):
    c, _ = cliente_vivo
    c.post("/api/vivo/iniciar", json={"fuente": "seco", "archivo": "demo.csv", "ritmo_hz": 0})
    _esperar_muestras(c)
    with c.websocket_connect("/api/vivo/stream") as ws:
        datos = ws.receive_json()
        assert datos["tipo"] == "vivo"
        assert "ventana" in datos
        assert "degradacion" in datos
