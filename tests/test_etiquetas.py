"""Tests de etiquetas y del proxy."""

import copy

import numpy as np
import pandas as pd

from telemetria.pipeline import etiquetas
from tests.ayudas import df_degradacion


def test_proxy_ignora_el_efecto_del_combustible(cfg):
    # Sin degradacion real: las vueltas se acortan solo por quemar gasolina.
    fuel = [60.0, 40.0, 20.0, 0.0]
    df = df_degradacion(degrad=[0.0, 0.0, 0.0, 0.0], fuel=fuel)
    tab = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]))
    assert tab["degradacion_proxy"].max() < 1e-6


def test_proxy_crece_con_la_degradacion(cfg):
    fuel = [60.0, 40.0, 20.0, 0.0]
    df = df_degradacion(degrad=[0.0, 0.3, 0.6, 0.9], fuel=fuel)
    tab = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]))
    p = tab["degradacion_proxy"].to_numpy()
    assert np.all(np.diff(p) >= -1e-9)
    assert p.min() >= 0.0 and p.max() <= 1.0 + 1e-9
    assert p[-1] > p[0]


def test_tiempos_por_vuelta(cfg):
    fuel = [60.0, 40.0, 20.0, 0.0]
    df = df_degradacion(degrad=[0.0, 0.3, 0.6, 0.9], fuel=fuel)
    tab = etiquetas.tiempos_por_vuelta(df, fs=float(cfg["fs"]))
    assert len(tab) == 4
    assert "tiempo_vuelta_s" in tab.columns
    assert np.all(np.diff(tab["tiempo_vuelta_s"]) < 0)  # se acortan por combustible


def test_comparar_proxy(cfg):
    df = df_degradacion(degrad=[0.0, 0.3, 0.6, 0.9], fuel=[60.0, 40.0, 20.0, 0.0])
    tab = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]))
    verdad = tab[["lap"]].copy()
    verdad["degradacion"] = tab["degradacion_proxy"]
    res = etiquetas.comparar_proxy(tab, verdad)
    assert res["n"] == 4
    assert res["mae"] < 1e-6
    assert res["corr"] > 0.99


def test_calibrar_k_fuel_recupera_la_pendiente():
    import pandas as pd

    # t = 90.5 + 0.025 * kg  (sin degradacion)
    tab = pd.DataFrame(
        {
            "lap": [1, 2, 3],
            "combustible_kg": [60.0, 40.0, 20.0],
            "tiempo_vuelta_s": [92.0, 91.5, 91.0],
        }
    )
    assert abs(etiquetas.calibrar_k_fuel(tab, 3, 0.035) - 0.025) < 1e-9


def test_calibrar_k_fuel_cae_al_valor_por_defecto():
    import pandas as pd

    # tiempo constante -> pendiente 0, no fisica -> valor por defecto
    tab = pd.DataFrame(
        {
            "lap": [1, 2, 3],
            "combustible_kg": [60.0, 40.0, 20.0],
            "tiempo_vuelta_s": [90.0, 90.0, 90.0],
        }
    )
    assert etiquetas.calibrar_k_fuel(tab, 3, 0.035) == 0.035


def test_proxy_respeta_el_k_fuel_calibrado(cfg):
    # con calibracion activada el resultado debe seguir siendo monótono y en [0,1]
    c = copy.deepcopy(cfg)
    c["etiquetas"]["calibrar_k_fuel"] = True
    df = df_degradacion(degrad=[0.0, 0.3, 0.6, 0.9], fuel=[60.0, 40.0, 20.0, 0.0])
    tab = etiquetas.proxy_degradacion(df, c, fs=float(c["fs"]))
    p = tab["degradacion_proxy"].to_numpy()
    assert np.all(np.diff(p) >= -1e-9)
    assert p.min() >= 0.0 and p.max() <= 1.0 + 1e-9


def test_ajuste_conjunto_recupera_k_sin_degradacion(cfg):
    # Sin desgaste, la unica tendencia posible es la del combustible: el
    # ajuste conjunto recupera el k inyectado.
    df = df_degradacion(degrad=[0.0, 0.0, 0.0, 0.0], fuel=[60.0, 40.0, 20.0, 0.0], k_fuel=0.025)
    tab = etiquetas.tiempos_por_vuelta(df, fs=float(cfg["fs"]))
    k, delta = etiquetas.ajustar_k_fuel_conjunto(tab, cfg)
    assert abs(k - 0.025) < 1e-3
    assert np.all(np.diff(delta) >= -1e-9)


def test_ajuste_conjunto_con_degradacion_es_monotono(cfg):
    # Con desgaste, k y la pendiente de degradacion son parcialmente
    # indistinguibles: se comprueba la banda identificable y la monotonía.
    c = copy.deepcopy(cfg)
    c["etiquetas"]["metodo_proxy"] = "conjunto"
    df = df_degradacion(degrad=[0.0, 0.3, 0.6, 0.9], fuel=[60.0, 40.0, 20.0, 0.0], k_fuel=0.025)
    tab = etiquetas.proxy_degradacion(df, c, fs=float(c["fs"]))
    p = tab["degradacion_proxy"].to_numpy()
    k = float(tab["k_fuel_ajustado"].iloc[0])
    assert 0.0 < k <= 0.025 + 1e-9  # nunca por encima del valor inyectado
    assert k < float(cfg["etiquetas"]["k_fuel_s_kg"])  # corrige mas que el fijo
    assert np.all(np.diff(p) >= -1e-9)
    assert p.min() >= 0.0 and p.max() <= 1.0 + 1e-9


def test_metodo_conjunto_por_parametro_no_cambia_el_default(cfg):
    df = df_degradacion(degrad=[0.0, 0.3, 0.6, 0.9], fuel=[60.0, 40.0, 20.0, 0.0])
    por_defecto = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]))
    conjunto = etiquetas.proxy_degradacion(df, cfg, fs=float(cfg["fs"]), metodo="conjunto")
    assert "k_fuel_ajustado" not in por_defecto.columns
    assert "k_fuel_ajustado" in conjunto.columns
    assert list(conjunto["degradacion_proxy"].index) == list(por_defecto["degradacion_proxy"].index)


def test_proxy_por_energia(cfg):
    feats = pd.DataFrame(
        {
            "lap": [1, 1, 2, 2, 3, 3, 4, 4],
            "trabajo_friccion_fl": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0],
            "trabajo_friccion_fr": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0],
        }
    )
    tab = etiquetas.proxy_por_energia(feats, cfg)
    p = tab["degradacion_energia"].to_numpy()
    assert list(tab["lap"]) == [1, 2, 3, 4]
    assert np.all(np.diff(p) >= -1e-9)
    assert abs(p[0]) < 1e-9 and abs(p[-1] - 1.0) < 1e-9


def test_proxy_por_energia_cae_a_slip_energia(cfg):
    feats = pd.DataFrame(
        {
            "lap": [1, 2, 3],
            "slip_energia_fl": [1.0, 2.0, 3.0],
        }
    )
    tab = etiquetas.proxy_por_energia(feats, cfg)
    assert np.all(np.diff(tab["degradacion_energia"].to_numpy()) >= -1e-9)
