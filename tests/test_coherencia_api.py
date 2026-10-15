"""Tests de coherencia numérica: la API devuelve lo que produce la Etapa 1.

Criterio de la sección 8 del plan Etapa 2: los resultados de Ridge y Kalman
calculados por la API deben ser idénticos a los de `main.py`, con el slider de
alpha en su valor por defecto (elegido por CV) y los Q/R de `config.yaml`.

La réplica del pipeline en `_pipeline_referencia` sigue paso a paso la
orquestación de `main.py::correr`; si alguna se modifica, este test avisa.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import etiquetas, evaluacion, features, limpieza, modelo
from src.config import cargar_config
from tests.conftest import OVERRIDES

RAIZ = Path(__file__).resolve().parents[1]


def _pipeline_referencia(ruta_csv: Path, ruta_verdad: Path | None, cfg: dict) -> dict:
    """Répica de `main.py::correr` sobre un CSV ya escrito en disco."""
    df_raw = pd.read_csv(ruta_csv)
    df_limpio, _registro, _estado = limpieza.preprocesar(df_raw, cfg)
    feats = features.features_por_ventanas(df_limpio, cfg)

    verdad = pd.read_csv(ruta_verdad) if ruta_verdad and ruta_verdad.exists() else None
    proxy = etiquetas.proxy_degradacion(df_limpio, cfg, fs=cfg["fs"])
    if verdad is not None:
        y_vuelta_df = etiquetas.verdad_por_vuelta(verdad)
        y_ventana = modelo.etiquetas_por_ventana(feats, verdad, cfg)
    else:
        y_vuelta_df = proxy[["lap", "degradacion_proxy"]].rename(
            columns={"degradacion_proxy": "degradacion"}
        )
        mapa = dict(zip(proxy["lap"], proxy["degradacion_proxy"]))
        y_ventana = feats["lap"].map(mapa).to_numpy(dtype=float)

    # split temporal (nunca al azar), igual que main.py
    laps_w = feats["lap"].to_numpy()
    train_laps, test_laps = modelo.split_temporal(np.unique(laps_w), cfg["modelo"]["prop_test"])
    m_tr = np.isin(laps_w, train_laps)
    verdad_lap = dict(zip(y_vuelta_df["lap"], y_vuelta_df["degradacion"]))
    y_test = np.array([verdad_lap[l] for l in test_laps], dtype=float)
    y_train_lap = np.array([verdad_lap[l] for l in train_laps], dtype=float)

    # Ridge a nivel ventana, agregado por vuelta
    Xw, _cols = modelo.matriz_features(feats)
    ridge = modelo.entrenar_ridge(Xw[m_tr], y_ventana[m_tr], laps_w[m_tr], cfg)
    pred_ridge = (
        pd.DataFrame({"lap": laps_w, "pred": modelo.predecir_ridge(ridge, Xw)})
        .groupby("lap")["pred"]
        .mean()
        .reindex(test_laps)
        .to_numpy(dtype=float)
    )

    # Kalman a nivel vuelta
    kc = cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(
        kc["q_nivel"], kc["q_pendiente"], kc["r"], monotono=kc.get("monotono", True)
    )
    res_kal = kal.filtrar(y_train_lap)
    medias, var = kal.predecir(res_kal, len(test_laps))

    return {
        "alpha": float(ridge["alpha"]),
        "pred_ridge": pred_ridge,
        "met_ridge": evaluacion.metricas(y_test, pred_ridge),
        "medias": medias,
        "var": var,
        "met_kalman": evaluacion.metricas(y_test, medias),
        "cobertura": evaluacion.cobertura_bandas(y_test, medias, var, cfg["evaluacion"]["z"]),
    }


def test_api_reproduce_el_pipeline_de_etapa_1(cliente, datos_demo):
    """Ridge y Kalman de la API == los de main.py (alpha por CV, Q/R de config)."""
    cfg = cargar_config(overrides=OVERRIDES)
    ref = _pipeline_referencia(
        datos_demo / "demo.csv", datos_demo / "demo_verdad.csv", cfg
    )

    ridge = cliente.post("/api/modelos/ridge/ajustar", json={}).json()
    assert ridge["alpha"] == pytest.approx(ref["alpha"], rel=1e-12)
    assert ridge["metricas"]["mae"] == pytest.approx(ref["met_ridge"]["mae"], abs=1e-12)
    assert ridge["metricas"]["rmse"] == pytest.approx(ref["met_ridge"]["rmse"], abs=1e-12)
    assert ridge["metricas"]["r2"] == pytest.approx(ref["met_ridge"]["r2"], abs=1e-12)
    np.testing.assert_allclose(np.array(ridge["pred_test"]), ref["pred_ridge"], atol=1e-12)

    kalman = cliente.post("/api/modelos/kalman/estimar", json={}).json()
    np.testing.assert_allclose(np.array(kalman["pred"]), ref["medias"], atol=1e-12)
    np.testing.assert_allclose(np.array(kalman["var"]), ref["var"], atol=1e-15)
    assert kalman["metricas"]["mae"] == pytest.approx(ref["met_kalman"]["mae"], abs=1e-12)
    assert kalman["cobertura"] == pytest.approx(ref["cobertura"], abs=1e-12)


def test_ws_y_rest_dan_lo_mismo(cliente):
    """Los dos transportes (REST y WebSocket) comparten el mismo servicio."""
    with cliente.websocket_connect("/ws/telemetria") as ws:
        ws.send_json({"tipo": "ajuste_kalman"})
        j_ws = ws.receive_json()
    j_rest = cliente.post("/api/modelos/kalman/estimar", json={}).json()

    np.testing.assert_allclose(np.array(j_ws["pred"]), np.array(j_rest["pred"]), atol=1e-12)
    np.testing.assert_allclose(np.array(j_ws["banda_sup"]), np.array(j_rest["banda_sup"]), atol=1e-12)
    assert j_ws["metricas"] == j_rest["metricas"]


def test_coherencia_del_espectro(cliente):
    """El PSD del backend es un Welch con los parámetros de config.yaml."""
    from scipy.signal import welch

    sesion = cliente.app.state.cache.activa_o_error()
    canal = "wheel_slip_fl"
    j = cliente.get("/api/telemetria/espectro", params={"canal": canal}).json()

    x = sesion.limpio[canal].to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    n = int(min(sesion.cfg["features"]["welch_nperseg"], len(x)))
    freqs, psd = welch(x, fs=sesion.fs, nperseg=n, noverlap=n // 2)

    np.testing.assert_allclose(np.array(j["freqs"]), freqs, atol=1e-9)
    np.testing.assert_allclose(
        np.array(j["psd_limpio_db"]), 10 * np.log10(np.maximum(psd, 1e-20)), atol=1e-6
    )
    assert j["nperseg"] == sesion.cfg["features"]["welch_nperseg"]


# --------------------------------------------------------------------------
# Referencia documentada (data/raw/sim_42.csv, semilla 42, 40 vueltas)
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cliente_sim42():
    """App real contra data/raw/sim_42.csv (la sesión de referencia del README)."""
    pytest.importorskip("fastapi")
    if not (RAIZ / "data" / "raw" / "sim_42.csv").exists():
        pytest.skip("data/raw/sim_42.csv no está presente")

    from fastapi.testclient import TestClient

    from backend.app import crear_app

    app = crear_app()  # config.yaml real, sin overrides
    with TestClient(app) as c:
        r = c.post("/api/sesiones/cargar", json={"nombre": "sim_42.csv"})
        assert r.status_code == 200, r.text
        yield c


def test_referencia_documentada_sim_42(cliente_sim42):
    """La API reproduce los MAE documentados en el README de la Etapa 1."""
    ridge = cliente_sim42.post("/api/modelos/ridge/ajustar", json={}).json()
    assert ridge["metricas"]["mae"] == pytest.approx(0.0023, abs=5e-5)

    kalman = cliente_sim42.post("/api/modelos/kalman/estimar", json={}).json()
    assert kalman["metricas"]["mae"] == pytest.approx(0.0197, abs=5e-4)
    assert kalman["cobertura"] == pytest.approx(1.00, abs=1e-6)


def test_stint_completo_recortado(cliente_sim42):
    """El stint entero (211k muestras) viaja recortado a max_puntos (§3.1)."""
    import time

    t0 = time.perf_counter()
    j = cliente_sim42.get(
        "/api/telemetria/stint", params={"max_puntos": 5000}
    ).json()
    transcurrido = time.perf_counter() - t0

    assert j["lap"] is None
    assert j["downsample"] is True
    assert j["n"] <= 5000
    assert len(j["t"]) == len(j["series"]["speed_kmh"])
    assert j["n_total"] > 200_000  # el stint real se reduce ~42x
    assert transcurrido < 2.0  # sin bloquear el event loop de forma notable
