"""Tests de segmentacion y extraccion de features."""

import numpy as np

from telemetria.pipeline import features
from tests.ayudas import df_esquema


def test_rms_y_energia_de_una_senoidal(cfg):
    fs = float(cfg["fs"])
    n = 200
    A = 3.0
    df = df_esquema(n, fs=fs)
    t = df["timestamp_s"].to_numpy()
    df["wheel_slip_rl"] = A * np.sin(2 * np.pi * 5 * t)

    f = features.features_ventana(df, cfg)
    assert abs(f["slip_rms_rl"] - A / np.sqrt(2)) < 0.05
    assert abs(f["slip_energia_rl"] - (A**2 / 2) * (n / fs)) < 0.05 * (A**2 / 2) * (n / fs)


def test_pico_espectral_en_la_banda_correcta(cfg):
    fs = float(cfg["fs"])
    n = 200
    df = df_esquema(n, fs=fs)
    t = df["timestamp_s"].to_numpy()
    df["wheel_slip_rl"] = np.sin(2 * np.pi * 3 * t)
    f = features.features_ventana(df, cfg)
    assert f["psd_baja_rl"] > 10 * f["psd_alta_rl"]


def test_grados_segundo_nulo_bajo_el_umbral(cfg):
    umbral = float(cfg["features"]["temp_umbral_c"])
    df = df_esquema(200)
    df["temp_core_c_rl"] = umbral - 5.0
    f = features.features_ventana(df, cfg)
    assert f["grados_segundo_rl"] == 0.0

    df["temp_core_c_rl"] = umbral + 10.0
    f2 = features.features_ventana(df, cfg)
    assert abs(f2["grados_segundo_rl"] - 10.0 * 2.0) < 1e-6


def test_trabajo_de_friccion_positivo(cfg):
    df = df_esquema(200)
    df["wheel_slip_rl"] = 0.2
    f = features.features_ventana(df, cfg)
    assert f["trabajo_friccion_rl"] > 0


def test_ventanas_no_cruzan_vueltas(cfg):
    fs = float(cfg["fs"])
    df = df_esquema(400, fs=fs)
    df["lap"] = np.where(df.index < 200, 1, 2)
    df["valido"] = True
    feats = features.features_por_ventanas(df, cfg)
    assert not feats.empty
    assert set(feats["lap"].unique()) <= {1, 2}
    # agregar por vuelta produce 2 filas
    agg = features.agregar_por_vuelta(feats)
    assert len(agg) == 2
    assert "n_ventanas" in agg.columns
