"""Tests de metricas y evaluacion."""

import numpy as np

from src import evaluacion


def test_metricas_prediccion_perfecta():
    y = np.array([0.0, 0.3, 0.6, 0.9])
    m = evaluacion.metricas(y, y)
    assert m["mae"] == 0.0
    assert m["rmse"] == 0.0
    assert abs(m["r2"] - 1.0) < 1e-9


def test_vuelta_de_caida():
    y = np.array([0.1, 0.2, 0.55, 0.7])
    assert evaluacion.vuelta_de_caida(y, 0.5) == 2
    assert evaluacion.vuelta_de_caida(np.array([0.1, 0.2]), 0.5) is None
    assert evaluacion.error_vuelta_caida(y, np.array([0.1, 0.2, 0.3, 0.8]), 0.5) == 1


def test_cobertura_bandas():
    media = np.zeros(10)
    var = np.full(10, 1e-6)
    assert evaluacion.cobertura_bandas(np.zeros(10), media, var) == 1.0
    assert evaluacion.cobertura_bandas(np.full(10, 100.0), media, var) == 0.0


def test_baselines():
    y_train = np.array([0.1, 0.2, 0.3])
    y_test = np.array([0.35, 0.4])
    res = evaluacion.baselines(y_train, y_test)
    assert set(res) == {"baseline_media", "baseline_ultimo"}
    assert res["baseline_media"]["mae"] >= 0


def test_robustez_snr_empeora_con_ruido(cfg):
    from src import modelo

    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 4))
    y = X @ np.array([1.0, -2.0, 0.5, 3.0])
    laps = np.repeat(np.arange(1, 11), 20)
    m = modelo.entrenar_ridge(X, y, laps, cfg)
    filas = evaluacion.prueba_robustez_snr(m, X, y, [40.0, 10.0, 0.0], rng=rng)
    mae_limpio = filas[0]["mae"]
    mae_ruidoso = filas[-1]["mae"]
    assert mae_ruidoso > mae_limpio


def test_verificacion_fisica_cuenta_signos():
    import pandas as pd

    imp = pd.DataFrame(
        {
            "feature": ["slip_mean_fl", "temp_mean_rl", "grados_segundo_rr", "speed_mean"],
            "coeficiente": [0.1, 0.2, -0.3, -0.05],
        }
    )
    d = {r["grupo"]: r for r in evaluacion.verificacion_fisica(imp)}
    assert d["slip"]["n"] == 1 and d["slip"]["aciertos"] == 1
    assert d["temp"]["aciertos"] == 1
    assert d["grados_segundo"]["aciertos"] == 0
    assert "speed" not in d
    # suma por grupo y bandera de coincidencia
    assert abs(d["slip"]["suma"] - 0.1) < 1e-9 and d["slip"]["coincide"] is True
    assert abs(d["grados_segundo"]["suma"] + 0.3) < 1e-9 and d["grados_segundo"]["coincide"] is False


def test_sensibilidad_kalman(cfg):
    y_train = np.linspace(0.0, 0.6, 20)
    y_test = np.linspace(0.6, 0.9, 8)
    filas = evaluacion.sensibilidad_kalman(y_train, y_test, cfg, valores_r=[1e-4, 1e-2])
    assert len(filas) == 2
    assert {f["r"] for f in filas} == {1e-4, 1e-2}
    for f in filas:
        assert np.isfinite(f["mae"])
        assert 0.0 <= f["cobertura"] <= 1.0
