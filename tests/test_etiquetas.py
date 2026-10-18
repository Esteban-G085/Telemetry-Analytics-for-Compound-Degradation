"""Tests de etiquetas y del proxy."""

import numpy as np

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
    import copy

    c = copy.deepcopy(cfg)
    c["etiquetas"]["calibrar_k_fuel"] = True
    df = df_degradacion(degrad=[0.0, 0.3, 0.6, 0.9], fuel=[60.0, 40.0, 20.0, 0.0])
    tab = etiquetas.proxy_degradacion(df, c, fs=float(c["fs"]))
    p = tab["degradacion_proxy"].to_numpy()
    assert np.all(np.diff(p) >= -1e-9)
    assert p.min() >= 0.0 and p.max() <= 1.0 + 1e-9
