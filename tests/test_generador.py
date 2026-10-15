"""Tests del generador de datos simulados (F1)."""

import numpy as np

from sim import generador
from src.config import columnas_esquema


def test_columnas_del_esquema(cfg):
    df, verdad = generador.generar_dataframe(cfg)
    assert list(df.columns) == columnas_esquema()
    assert {"timestamp_s", "lap", "degradacion"} <= set(verdad.columns)


def test_reproducible_con_la_misma_semilla(cfg):
    a, va = generador.generar_dataframe(cfg, semilla=123)
    b, vb = generador.generar_dataframe(cfg, semilla=123)
    assert np.allclose(a["wheel_slip_fl"].to_numpy(), b["wheel_slip_fl"].to_numpy(), equal_nan=True)
    assert np.allclose(va["degradacion"].to_numpy(), vb["degradacion"].to_numpy())


def test_degradacion_monotona_y_en_rango(cfg):
    _, verdad = generador.generar_dataframe(cfg)
    d = verdad["degradacion"].to_numpy()
    assert np.all(np.diff(d) >= -1e-12)
    assert d.min() >= 0.0 and d.max() <= 1.0


def test_numero_de_vueltas(cfg):
    _, verdad = generador.generar_dataframe(cfg)
    assert verdad["lap"].nunique() == cfg["sim"]["vueltas"]


def test_contiene_ruido_y_huecos(cfg):
    df, _ = generador.generar_dataframe(cfg)
    assert df.isna().to_numpy().any(), "el generador debe inyectar huecos"
    # los outliers deben superar el rango fisico en algun punto
    assert (df["wheel_slip_fl"].abs() > 1.5).any() or (df["temp_core_c_fl"] > 250).any()


def test_degradacion_rapida_lenta_configurable(cfg):
    import copy

    c_lineal = copy.deepcopy(cfg)
    c_lineal["sim"]["tasa_degradacion"] = 0.0
    c_acelerado = copy.deepcopy(cfg)
    c_acelerado["sim"]["tasa_degradacion"] = 3.0

    _, v_lineal = generador.generar_dataframe(c_lineal, semilla=5)
    _, v_acelerado = generador.generar_dataframe(c_acelerado, semilla=5)
    d_lineal = v_lineal.groupby("lap")["degradacion"].mean().to_numpy()
    d_acelerado = v_acelerado.groupby("lap")["degradacion"].mean().to_numpy()
    # misma cantidad de vueltas, valores validos, pero forma distinta
    assert len(d_lineal) == len(d_acelerado) == cfg["sim"]["vueltas"]
    assert d_lineal.max() <= 1.0 + 1e-9 and d_acelerado.max() <= 1.0 + 1e-9
    assert np.all(np.diff(d_lineal) >= -1e-12) and np.all(np.diff(d_acelerado) >= -1e-12)
    assert not np.allclose(d_lineal, d_acelerado)


def test_masa_afecta_el_tiempo_de_vuelta():
    """Mas masa (mas combustible) => vueltas mas lentas."""
    t_ligero, *_ = generador._perfil_trayectoria(2, 100.0, masa_fn=lambda lap, frac: 1300.0)
    t_pesado, *_ = generador._perfil_trayectoria(2, 100.0, masa_fn=lambda lap, frac: 1450.0)
    assert t_pesado[-1] > t_ligero[-1]


def test_menos_agarre_por_degradacion_alarga_la_vuelta():
    """Menos grip en curva (goma gastada) => vueltas mas lentas."""
    t_ok, *_ = generador._perfil_trayectoria(2, 100.0, grip_vuelta=np.ones(2))
    t_malo, *_ = generador._perfil_trayectoria(2, 100.0, grip_vuelta=np.full(2, 0.9))
    assert t_malo[-1] > t_ok[-1]


def test_tiempo_de_vuelta_crece_con_el_desgaste(cfg):
    """En el dataset completo el tiempo de vuelta debe subir con la degradacion."""
    df_raw, verdad = generador.generar_dataframe(cfg, semilla=3)
    df, _, _ = __import__("src.limpieza", fromlist=["preprocesar"]).preprocesar(df_raw, cfg)
    t_vuelta = df.groupby("lap")["timestamp_s"].apply(lambda s: s.max() - s.min())
    d_vuelta = verdad.groupby("lap")["degradacion"].mean()
    # correlacion positiva entre duracion de la vuelta y desgaste
    assert np.corrcoef(t_vuelta.to_numpy(), d_vuelta.to_numpy())[0, 1] > 0.3
