"""Tests de los endpoints REST del backend (Etapa 2)."""

from __future__ import annotations

import yaml

from telemetria.pipeline.config import cargar_config


def test_health(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok"


def test_listar_sesiones(cliente):
    j = cliente.get("/api/sesiones").json()
    assert j["activa"] == "demo"
    nombres = {s["nombre"] for s in j["sesiones"]}
    assert "demo.csv" in nombres
    assert any(s["tiene_verdad"] for s in j["sesiones"])


def test_sesion_activa_resumen(cliente):
    j = cliente.get("/api/sesiones/activa").json()
    assert j["id"] == "demo"
    assert j["fs"] == 100.0
    assert j["tiene_verdad"] is True
    assert len(j["laps"]) >= 4
    assert len(j["vueltas"]) == len(j["laps"])


def test_vuelta_arrays_alineados(cliente):
    j = cliente.get("/api/telemetria/vuelta/1").json()
    assert j["lap"] == 1
    n = len(j["t"])
    assert n > 0
    for canal, valores in j["series"].items():
        assert len(valores) == n, canal
    assert len(j["valido"]) == n
    assert j["downsample"] is False


def test_vuelta_downsample_minmax(cliente):
    j = cliente.get("/api/telemetria/vuelta/1", params={"max_puntos": 500}).json()
    assert j["downsample"] is True
    assert len(j["t"]) <= 500
    assert len(j["t"]) == len(j["series"]["wheel_slip_fl"])


def test_vuelta_crudo_vs_limpio(cliente):
    j = cliente.get(
        "/api/telemetria/vuelta/1",
        params={"canales": "wheel_slip_fl,speed_kmh", "crudo": True},
    ).json()
    assert set(j["crudo"]) == {"wheel_slip_fl", "speed_kmh"}
    assert len(j["crudo"]["wheel_slip_fl"]) == len(j["series"]["wheel_slip_fl"])
    assert "atenuacion_db" in j["kpis"]


def test_vuelta_inexistente_404(cliente):
    r = cliente.get("/api/telemetria/vuelta/9999")
    assert r.status_code == 404


def test_canal_desconocido_400(cliente):
    r = cliente.get("/api/telemetria/vuelta/1", params={"canales": "no_existe"})
    assert r.status_code == 400


def test_canales(cliente):
    j = cliente.get("/api/telemetria/canales").json()
    assert "wheel_slip_fl" in j["canales"]
    assert "speed_kmh" in j["fisicas"]


def test_espectro_welch(cliente):
    j = cliente.get("/api/telemetria/espectro", params={"canal": "wheel_slip_fl"}).json()
    assert len(j["freqs"]) == len(j["psd_limpio_db"])
    assert j["psd_crudo_db"] is not None
    assert len(j["psd_crudo_db"]) == len(j["freqs"])
    assert j["delta_f"] > 0
    assert j["freqs"][-1] <= j["fs"] / 2 + 1e-6


def test_kalman_estimar(cliente):
    r = cliente.post("/api/modelos/kalman/estimar", json={"q_nivel": 1e-4, "r": 1e-3})
    assert r.status_code == 200
    j = r.json()
    assert len(j["pred"]) == len(j["laps_test"])
    assert len(j["banda_inf"]) == len(j["pred"])
    assert all(b_i <= p <= b_s for b_i, p, b_s in zip(j["banda_inf"], j["pred"], j["banda_sup"]))


def test_kalman_monotono(cliente):
    j = cliente.post("/api/modelos/kalman/estimar", json={"monotono": True}).json()
    nivel = j["nivel"]
    assert all(b >= a - 1e-12 for a, b in zip(nivel, nivel[1:]))


def test_ridge_alpha_fijo(cliente):
    j = cliente.post("/api/modelos/ridge/ajustar", json={"alpha": 1.0}).json()
    assert j["alpha"] == 1.0
    assert len(j["pred_all"]) == len(j["laps_all"])
    assert "coeficiente" in j["importancias"][0]


def test_series_de_referencia(cliente):
    """Ridge y Kalman exponen verdad y proxy por vuelta para la Vista 3 (§3.3)."""
    for ruta in ("/api/modelos/ridge/ajustar", "/api/modelos/kalman/estimar"):
        j = cliente.post(ruta, json={}).json()
        assert len(j["verdad"]) == len(j["verdad_laps"]) > 0
        assert len(j["proxy"]) == len(j["proxy_laps"]) > 0
        assert all(0.0 <= v <= 1.0 for v in j["verdad"] if v == v)
        assert all(0.0 <= v <= 1.0 for v in j["proxy"] if v == v)


def test_ridge_ablacion(cliente):
    j = cliente.post(
        "/api/modelos/ridge/ajustar", json={"excluir": ["slip", "temp", "trabajo"]}
    ).json()
    assert all("slip" not in f["feature"] for f in j["importancias"])


def test_config_get_post_export(cliente, tmp_path):
    base = cliente.get("/api/config").json()["config"]
    assert "limpieza" in base and "modelo" in base

    r = cliente.post("/api/config", json={"limpieza": {"filtro": {"corte_hz": 15.0}}})
    assert r.status_code == 200
    assert r.json()["config"]["limpieza"]["filtro"]["corte_hz"] == 15.0

    texto = cliente.get("/api/config/exportar").text
    ruta = tmp_path / "config_custom.yaml"
    ruta.write_text(texto, encoding="utf-8")
    recargada = cargar_config(ruta)
    assert recargada["limpieza"]["filtro"]["corte_hz"] == 15.0
    assert yaml.safe_load(texto)["fs"] == 100.0


def test_subir_csv_invalido_422(cliente):
    r = cliente.post(
        "/api/sesiones/subir",
        files={"archivo": ("malo.csv", "a,b\n1,2\n")},
    )
    assert r.status_code == 422


def test_subir_csv_valido(cliente, datos_demo):
    datos = (datos_demo / "demo.csv").read_bytes()
    r = cliente.post(
        "/api/sesiones/subir",
        files={"archivo": ("otra.csv", datos)},
    )
    assert r.status_code == 200
    assert r.json()["id"] == "otra"

    # la sesion subida pasa a ser la activa
    assert cliente.get("/api/sesiones").json()["activa"] == "otra"

    # restaurar la demo para no romper el orden de los tests del modulo
    cliente.post("/api/sesiones/cargar", json={"nombre": "demo.csv"})


def test_cargar_archivo_inexistente_404(cliente):
    r = cliente.post("/api/sesiones/cargar", json={"nombre": "no_existe.csv"})
    assert r.status_code == 404


def test_stint_endpoint(cliente):
    j = cliente.get("/api/telemetria/stint", params={"max_puntos": 300}).json()
    assert j["lap"] is None
    assert j["downsample"] is True
    assert len(j["t"]) <= 300
    for canal, valores in j["series"].items():
        assert len(valores) == len(j["t"]), canal


def test_robustez_snr(cliente):
    r = cliente.post("/api/modelos/robustez", json={"snr_db": [40.0, 20.0, 0.0]})
    assert r.status_code == 200
    j = r.json()
    assert j["snr_db"] == [40.0, 20.0, 0.0]
    assert len(j["mae"]) == 3
    # mas ruido (SNR menor) no deberia mejorar el error de forma sistematica
    assert j["mae"][-1] >= j["mae"][0]


def test_config_reset(cliente):
    cliente.post("/api/config", json={"limpieza": {"filtro": {"corte_hz": 12.0}}})
    assert cliente.get("/api/config").json()["config"]["limpieza"]["filtro"]["corte_hz"] == 12.0

    r = cliente.delete("/api/config")
    assert r.status_code == 200
    assert r.json()["config"]["limpieza"]["filtro"]["corte_hz"] == 20.0

