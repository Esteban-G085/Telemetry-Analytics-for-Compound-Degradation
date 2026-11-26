"""Validacion sintetica: recuperacion de parametros conocidos (pitwall-style).

El generador de pruebas inyecta ``k_fuel`` y una degradacion conocida. Estos
tests comprueban que el pipeline los recupera (o que la parte no
identificable queda documentada), sin tocar la API ni el comportamiento por
defecto.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from telemetria.pipeline import etiquetas, features, modelo
from tests.ayudas import df_degradacion

RUEDAS = ("fl", "fr", "rl", "rr")


def _degradacion_con_energia(degrad, fuel, k_fuel, cfg):
    """Stint sintetico con trabajo de friccion creciente con el desgaste."""
    df = df_degradacion(degrad, fuel, k_fuel=k_fuel, fs=float(cfg["fs"]))
    for i, lap in enumerate(np.unique(df["lap"])):
        mascara = df["lap"] == lap
        for rueda in RUEDAS:
            df.loc[mascara, f"wheel_slip_{rueda}"] = 0.01 + 0.004 * i
    return df, features.features_por_ventanas(df, cfg)


def test_tiempos_por_vuelta_recupera_las_duraciones(cfg):
    degrad = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    fuel = [60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
    k_fuel = 0.025
    df = df_degradacion(degrad, fuel, k_fuel=k_fuel, fs=float(cfg["fs"]))
    tab = etiquetas.tiempos_por_vuelta(df, fs=float(cfg["fs"]))

    esperado = 90.0 + k_fuel * np.asarray(fuel) + np.asarray(degrad)
    np.testing.assert_allclose(tab["tiempo_vuelta_s"], esperado, atol=0.02)


def test_ajuste_conjunto_recupera_k_sin_degradacion(cfg):
    df = df_degradacion([0.0, 0.0, 0.0, 0.0], [60.0, 40.0, 20.0, 0.0], k_fuel=0.025)
    tab = etiquetas.tiempos_por_vuelta(df, fs=float(cfg["fs"]))
    k, delta = etiquetas.ajustar_k_fuel_conjunto(tab, cfg)
    assert abs(k - 0.025) < 1e-3
    assert np.all(np.diff(delta) >= -1e-9)


def test_ajuste_conjunto_respeta_la_banda_identificable(cfg):
    """Con desgaste, k por debajo del real se puede absorber en la tendencia.

    El estimador elige la correccion minima que hace creciente la serie; por
    eso el k estimado nunca supera al inyectado. La diferencia exacta no es
    identificable solo con tiempos por vuelta (ver README).
    """
    degrad = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    fuel = [60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
    df = df_degradacion(degrad, fuel, k_fuel=0.025, fs=float(cfg["fs"]))
    tab = etiquetas.tiempos_por_vuelta(df, fs=float(cfg["fs"]))
    k, delta = etiquetas.ajustar_k_fuel_conjunto(tab, cfg)

    # 0.1 s/vuelta de desgaste se pueden confundir con 0.1/10 = 0.01 s/kg.
    assert 0.025 - 0.011 <= k <= 0.025 + 1e-9
    assert np.all(np.diff(delta) >= -1e-9)


def test_ajuste_conjunto_recupera_k_con_consumo_no_lineal(cfg):
    """Un consumo de combustible no lineal rompe la colinealidad con la vuelta."""
    degrad = [0.0, 0.05, 0.1, 0.15]
    fuel = [60.0, 50.0, 40.0, 0.0]
    df = df_degradacion(degrad, fuel, k_fuel=0.025, fs=float(cfg["fs"]))
    tab = etiquetas.tiempos_por_vuelta(df, fs=float(cfg["fs"]))
    k, _ = etiquetas.ajustar_k_fuel_conjunto(tab, cfg)
    assert abs(k - 0.025) < 0.002


def test_proxies_correlacionan_con_la_degradacion_conocida(cfg):
    degrad = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    fuel = [60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
    df, feats = _degradacion_con_energia(degrad, fuel, 0.025, cfg)
    verdad = pd.DataFrame({"lap": np.arange(1, 7), "degradacion": degrad})

    tab_tiempo = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]))
    tab_energia = etiquetas.proxy_por_energia(feats, cfg).rename(
        columns={"degradacion_energia": "degradacion_proxy"}
    )
    calidad_tiempo = etiquetas.comparar_proxy(tab_tiempo, verdad)
    calidad_energia = etiquetas.comparar_proxy(tab_energia, verdad)

    assert calidad_tiempo["corr"] > 0.9
    assert calidad_energia["corr"] > 0.95
    assert calidad_tiempo["mae"] < 0.25


def test_kalman_sigue_la_degradacion_conocida(cfg):
    degrad = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    k = cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(
        k["q_nivel"], k["q_pendiente"], k["r"], monotono=k.get("monotono", True)
    )
    res = kal.filtrar(degrad)

    # Con la Q/R de produccion el filtro va retrasado, pero no pierde la
    # tendencia ni invierte el orden de las vueltas.
    assert np.all(np.diff(res["nivel"]) >= -1e-9)
    assert res["pendiente"][-1] > 0.0
    assert float(np.max(np.abs(res["nivel"] - degrad))) < 0.1


def test_sesgo_entre_el_proxy_fijo_y_el_conjunto(cfg):
    """Diferencia media medida entre la correccion fija y la conjunta."""
    degrad = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    fuel = [60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
    df = df_degradacion(degrad, fuel, k_fuel=0.025, fs=float(cfg["fs"]))

    fijo = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]), metodo="corregido")
    conjunto = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]), metodo="conjunto")
    sesgo = float(np.mean(np.abs(fijo["delta_s"].to_numpy() - conjunto["delta_s"].to_numpy())))

    assert np.isfinite(sesgo)
    assert sesgo > 0.0  # el metodo fijo no puede seguir al conjunto
    c = copy.deepcopy(cfg)
    c["etiquetas"]["metodo_proxy"] = "conjunto"
    assert etiquetas.proxy_degradacion(df, c, fs=float(cfg["fs"])).equals(
        etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]), metodo="conjunto")
    )
