"""Tests de remuestreo, validacion y limpieza."""

import numpy as np
import pandas as pd
import pytest

from src import limpieza
from tests.ayudas import df_esquema


def test_validar_esquema_rechaza_faltantes(cfg):
    df = df_esquema(50)
    with pytest.raises(ValueError):
        limpieza.validar_esquema(df.drop(columns=["wheel_slip_fl"]))
    assert limpieza.validar_esquema(df) is True


def test_resampleo_deja_dt_constante():
    fs_origen = 300.0
    n = 3000
    t = np.arange(n) / fs_origen
    df = pd.DataFrame({"timestamp_s": t, "x": np.sin(2 * np.pi * 10 * t)})
    r = limpieza.resamplear(df, 100.0, fs_origen=fs_origen)
    d = np.diff(r["timestamp_s"].to_numpy())
    assert np.allclose(d, 0.01, atol=1e-9)


def test_antialias_elimina_tono_sobre_nyquist():
    fs_origen = 300.0
    n = 6000
    t = np.arange(n) / fs_origen
    # 10 Hz (debe conservarse) + 80 Hz (debe eliminarse; alias a 20 Hz)
    x = np.sin(2 * np.pi * 10 * t) + np.sin(2 * np.pi * 80 * t)
    df = pd.DataFrame({"timestamp_s": t, "x": x})
    r = limpieza.resamplear(df, 100.0, fs_origen=fs_origen)

    y = r["x"].to_numpy()
    y = y - y.mean()
    freqs = np.fft.rfftfreq(len(y), d=1.0 / 100.0)
    amp = 2.0 * np.abs(np.fft.rfft(y)) / len(y)

    def amplitud_en(f0, ancho=2.0):
        m = np.abs(freqs - f0) < ancho
        return float(amp[m].max()) if m.any() else 0.0

    assert amplitud_en(10.0) > 0.8          # se conserva
    assert amplitud_en(20.0) < 0.15         # el alias fue atenuado


def test_filtro_reduce_varianza_del_ruido(cfg):
    fs = float(cfg["fs"])
    rng = np.random.default_rng(0)
    df = df_esquema(4000, fs=fs)
    df["wheel_slip_rl"] = rng.normal(0.0, 1.0, len(df))
    out, _ = limpieza.filtrar(df, cfg, fs)
    desv_in = df["wheel_slip_rl"].std()
    desv_out = out["wheel_slip_rl"].std()
    assert desv_out < 0.85 * desv_in


def test_filtro_conserva_banda(cfg):
    fs = float(cfg["fs"])
    n = 4000
    df = df_esquema(n, fs=fs)
    t = df["timestamp_s"].to_numpy()
    df["wheel_slip_rl"] = np.sin(2 * np.pi * 5 * t)
    out, _ = limpieza.filtrar(df, cfg, fs)
    y = out["wheel_slip_rl"].to_numpy()
    amplitud = np.max(np.abs(y[n // 2 :]))
    assert 0.85 <= amplitud <= 1.10


def test_filtro_atenua_fuera_de_banda(cfg):
    fs = float(cfg["fs"])
    n = 4000
    df = df_esquema(n, fs=fs)
    t = df["timestamp_s"].to_numpy()
    df["wheel_slip_rl"] = np.sin(2 * np.pi * 40 * t)
    out, _ = limpieza.filtrar(df, cfg, fs)
    y = out["wheel_slip_rl"].to_numpy()
    assert np.max(np.abs(y[n // 2 :])) < 0.2


def test_filtro_es_causal(cfg):
    fs = float(cfg["fs"])
    rng = np.random.default_rng(1)
    n = 500
    x = rng.normal(0.0, 1.0, n)
    df1 = df_esquema(n, fs=fs)
    df2 = df_esquema(n, fs=fs)
    df1["wheel_slip_rl"] = x
    x2 = x.copy()
    x2[-1] += 100.0
    df2["wheel_slip_rl"] = x2
    y1, _ = limpieza.filtrar(df1, cfg, fs)
    y2, _ = limpieza.filtrar(df2, cfg, fs)
    # cambiar la ultima muestra no debe alterar salidas anteriores
    assert np.allclose(
        y1["wheel_slip_rl"].to_numpy()[:-1], y2["wheel_slip_rl"].to_numpy()[:-1]
    )


def test_marca_fuera_de_rango(cfg):
    df = df_esquema(100)
    df.loc[10, "temp_core_c_fl"] = 500.0
    df.loc[20, "wheel_slip_fr"] = -5.0
    out, reg = limpieza.marcar_fuera_de_rango(df, cfg)
    assert np.isnan(out.loc[10, "temp_core_c_fl"])
    assert np.isnan(out.loc[20, "wheel_slip_fr"])
    assert reg["fuera_de_rango"] >= 2


def test_no_interpola_a_traves_de_la_frontera_de_vuelta(cfg):
    fs = float(cfg["fs"])
    df = df_esquema(300, fs=fs)
    df["lap"] = np.where(df.index < 150, 1, 2)
    # hueco que cruza la frontera
    df.loc[148:151, "wheel_slip_rl"] = np.nan
    # hueco corto dentro de una vuelta
    df.loc[50:52, "wheel_slip_rl"] = np.nan
    out, reg = limpieza.interpolar_huecos(df, cfg, fs)
    assert out.loc[148:151, "wheel_slip_rl"].isna().all()
    assert not out.loc[50:52, "wheel_slip_rl"].isna().any()
    assert reg["huecos_cortos_rellenados"] >= 3


def test_preprocesar_reduce_outliers(cfg):
    from sim import generador

    df_raw, _ = generador.generar_dataframe(cfg)
    df, registro, estado = limpieza.preprocesar(df_raw, cfg)
    assert set(registro) >= {"fuera_de_rango", "outliers", "huecos_largos_marcados"}
    assert "valido" in df.columns
    # las muestras marcadas como validas no tienen NaN
    assert np.isfinite(df.loc[df["valido"], "wheel_slip_rl"].to_numpy()).all()
    assert df["valido"].mean() > 0.99
    assert estado  # se guarda el estado del filtro para la Etapa 3
