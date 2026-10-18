"""Tests de Ridge y del filtro de Kalman."""

import numpy as np

from telemetria.pipeline import modelo


def test_split_temporal_sin_fuga(cfg):
    laps = np.arange(1, 11)
    tr, te = modelo.split_temporal(laps, 0.3)
    assert set(tr).isdisjoint(set(te))
    assert tr.max() < te.min()


def test_ridge_no_usa_datos_de_test(cfg):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(60, 4))
    y = X @ np.array([1.0, -2.0, 0.5, 3.0]) + rng.normal(scale=0.1, size=60)
    laps = np.repeat(np.arange(1, 7), 10)

    m = modelo.entrenar_ridge(X[:40], y[:40], laps[:40], cfg)
    # el escalador se ajusta solo con train
    assert np.allclose(m["escalador"].mean_, X[:40].mean(axis=0))
    assert not np.allclose(m["escalador"].mean_, X.mean(axis=0))


def test_ridge_reproducible(cfg):
    rng = np.random.default_rng(2)
    X = rng.normal(size=(50, 3))
    y = rng.normal(size=50)
    laps = np.repeat(np.arange(1, 6), 10)
    a = modelo.entrenar_ridge(X, y, laps, cfg)
    b = modelo.entrenar_ridge(X, y, laps, cfg)
    assert a["alpha"] == b["alpha"]
    assert np.allclose(a["ridge"].coef_, b["ridge"].coef_)


def test_kalman_converge_sin_ruido(cfg):
    k = cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(k["q_nivel"], k["q_pendiente"], k["r"])
    obs = 0.05 * np.arange(20)
    res = kal.filtrar(obs)
    err = np.abs(res["nivel"] - obs)
    # hay un transitorio inicial y un retardo pequeno esperable (R > 0),
    # pero el error se mantiene acotado y termina muy cerca de la senal
    assert err.max() < 0.06
    assert err[-1] < 0.01
    assert abs(res["pendiente"][-1] - 0.05) < 5e-3


def test_kalman_monotono(cfg):
    k = cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(k["q_nivel"], k["q_pendiente"], k["r"], monotono=True)
    obs = np.array([0.0, 0.2, 0.4, 0.3, 0.5, 0.45, 0.6])
    res = kal.filtrar(obs)
    assert np.all(np.diff(res["nivel"]) >= -1e-12)


def test_kalman_cobertura_de_bandas(cfg):
    from telemetria.pipeline.evaluacion import cobertura_bandas

    k = cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(k["q_nivel"], k["q_pendiente"], k["r"])
    rng = np.random.default_rng(3)
    obs = 0.5 + 0.02 * np.arange(30) + rng.normal(0.0, 0.01, 30)
    res = kal.filtrar(obs)
    cob = cobertura_bandas(obs, res["nivel"], res["var_nivel"], z=1.96)
    assert 0.6 <= cob <= 1.0


def test_kalman_predice_hacia_adelante(cfg):
    k = cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(k["q_nivel"], k["q_pendiente"], k["r"])
    obs = np.linspace(0.0, 0.6, 15)
    res = kal.filtrar(obs)
    medias, var = kal.predecir(res, pasos=5)
    assert len(medias) == 5
    assert np.all(np.diff(medias) >= -1e-9)
    assert np.all(var >= 0)
    assert var[0] <= var[-1]  # la incertidumbre crece


def test_kalman_varianza_incluye_ruido_de_proceso():
    """Sin ruido de proceso la banda es casi solo P; con Q crece."""
    obs = np.linspace(0.0, 0.6, 20)
    kal_sin = modelo.KalmanDegradacion(0.0, 0.0, 1e-3)
    kal_con = modelo.KalmanDegradacion(1e-3, 1e-5, 1e-3)
    _, v_sin = kal_sin.predecir(kal_sin.filtrar(obs), pasos=8)
    _, v_con = kal_con.predecir(kal_con.filtrar(obs), pasos=8)
    assert np.all(v_con > v_sin)
    assert np.all(np.diff(v_con) >= 0)


def test_matriz_features_excluye_etiqueta(cfg):
    import pandas as pd

    tab = pd.DataFrame({"lap": [1, 2], "degradacion": [0.1, 0.2], "slip_mean_fl": [1.0, 2.0], "temp_mean_fl": [3.0, 4.0]})
    X, cols = modelo.matriz_features(tab)
    assert "degradacion" not in cols
    Xa, cola = modelo.matriz_features(tab, excluir=("slip", "temp"))
    assert cola == []


def test_ridge_no_explota_con_feature_constante_en_train(cfg):
    """Una feature sin varianza en train no debe amplificarse en test."""
    rng = np.random.default_rng(0)
    n = 240
    X = rng.normal(size=(n, 6))
    X[:, 2] = 7.0  # constante en TODO el dataset
    y = 0.4 * X[:, 0] + 0.1 * X[:, 1] + 0.3
    laps = np.repeat(np.arange(1, 13), 20)
    m = modelo.entrenar_ridge(X[:180], y[:180], laps[:180], cfg)
    assert m["utiles"][2] is np.False_ or m["utiles"][2] == False  # noqa: E712

    X_test = X[180:].copy()
    X_test[:, 2] = 1e6  # valor imposible en test
    pred = modelo.predecir_ridge(m, X_test)
    assert np.all(np.isfinite(pred))
    assert np.max(np.abs(pred)) < 10.0


def test_ridge_acota_la_estandarizacion(cfg):
    """El recorte (ridge_clip) limita el efecto de valores extremos."""
    rng = np.random.default_rng(1)
    n = 240
    X = rng.normal(size=(n, 5))
    y = X[:, 0] * 0.5 + 0.2
    laps = np.repeat(np.arange(1, 13), 20)
    m = modelo.entrenar_ridge(X[:180], y[:180], laps[:180], cfg)
    extremo = X[180:].copy()
    extremo[:, 0] = 1e5
    pred = modelo.predecir_ridge(m, extremo)
    assert np.all(np.isfinite(pred))
    assert np.max(np.abs(pred)) < 50.0
