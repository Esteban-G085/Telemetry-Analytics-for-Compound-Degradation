"""Test de integracion: pipeline completo con datos simulados."""

import numpy as np

from telemetria.adquisicion import generador
from telemetria.pipeline import etiquetas, evaluacion, features, limpieza, modelo


def test_pipeline_de_punta_a_punta(cfg):
    df_raw, verdad = generador.generar_dataframe(cfg, semilla=7)

    df_limpio, registro, estado = limpieza.preprocesar(df_raw, cfg)
    assert np.isfinite(df_limpio.loc[df_limpio["valido"], "wheel_slip_rl"].to_numpy()).all()

    feats = features.features_por_ventanas(df_limpio, cfg)
    assert not feats.empty
    feats_vuelta = features.agregar_por_vuelta(feats)

    y_vuelta = etiquetas.verdad_por_vuelta(verdad)
    promedio = modelo.preparar_vuelta(feats_vuelta, y_vuelta)
    assert len(promedio) >= 4

    laps = promedio["lap"].to_numpy()
    tr, te = modelo.split_temporal(laps, 0.34)
    m_tr = np.isin(laps, tr)
    m_te = np.isin(laps, te)

    X, _ = modelo.matriz_features(promedio)
    y = promedio["degradacion"].to_numpy()

    ridge = modelo.entrenar_ridge(X[m_tr], y[m_tr], laps[m_tr], cfg)
    pred = modelo.predecir_ridge(ridge, X[m_te])
    met = evaluacion.metricas(y[m_te], pred)
    assert np.isfinite(met["mae"])
    assert met["mae"] < 0.5

    kal_cfg = cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(kal_cfg["q_nivel"], kal_cfg["q_pendiente"], kal_cfg["r"])
    res = kal.filtrar(y[m_tr])
    medias, var = kal.predecir(res, int(m_te.sum()))
    assert len(medias) == int(m_te.sum())
    assert np.all(np.isfinite(medias))


def test_proxy_vs_verdad_es_razonable(cfg):
    df_raw, verdad = generador.generar_dataframe(cfg, semilla=11)
    df_limpio, _, _ = limpieza.preprocesar(df_raw, cfg)
    proxy = etiquetas.proxy_degradacion(df_limpio, cfg, fs=float(cfg["fs"]))
    yv = etiquetas.verdad_por_vuelta(verdad)
    res = etiquetas.comparar_proxy(proxy, yv)
    # el proxy es una aproximacion: exigimos solo que correlacione
    assert res["corr"] > 0.5
    assert res["mae"] < 0.5
