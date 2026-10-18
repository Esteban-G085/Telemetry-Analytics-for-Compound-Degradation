"""Etiquetas de degradacion (Etapa 1).

Etiqueta canonica (D6): degradacion acumulada normalizada en [0, 1].

  - F1 (simulada): degradacion verdadera por muestra -> promedio por vuelta.
  - F2 (Live Telemetry): `wear% / 100` (fuente real, fase posterior).
  - F3/F4 (sin desgaste): proxy desde el tiempo de vuelta corregido por
    combustible, suavizado y forzado monótono.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter


def tiempos_por_vuelta(df: pd.DataFrame, fs: float | None = None) -> pd.DataFrame:
    """Tiempo de vuelta, combustible medio y numero de muestras por vuelta."""
    inicios = df.groupby("lap")["timestamp_s"].min()
    finals = df.groupby("lap")["timestamp_s"].max()
    n = df.groupby("lap").size()
    dt = (1.0 / fs) if fs else 0.0

    laps = inicios.index.to_numpy()
    t_ini = inicios.to_numpy()
    duraciones = np.empty(len(laps))
    for i in range(len(laps)):
        if i + 1 < len(laps):
            duraciones[i] = t_ini[i + 1] - t_ini[i]
        else:
            duraciones[i] = finals.to_numpy()[i] - t_ini[i] + dt

    return pd.DataFrame(
        {
            "lap": laps,
            "tiempo_vuelta_s": duraciones,
            "combustible_kg": df.groupby("lap")["fuel_kg"].mean().to_numpy(),
            "n_muestras": n.to_numpy(),
        }
    )


def calibrar_k_fuel(tab: pd.DataFrame, n_vueltas: int = 3, por_defecto: float = 0.035) -> float:
    """Estima ``k_fuel`` (s/kg) por regresion del tiempo de vuelta contra el combustible.

    Al arranque de un stint el desgaste es bajo, asi que la variacion del tiempo
    de vuelta la domina el peso del combustible: ``t = t0 + k_fuel * kg`` (mas
    combustible -> mas masa -> vuelta mas lenta). Si no hay datos suficientes o
    la pendiente no es fisica (<= 0), se devuelve el valor por defecto.

    Nota: el generador simulado (F1) NO modela el efecto de la masa de
    combustible sobre el tiempo de vuelta, asi que aqui la regresion da una
    pendiente ~0 y se cae al valor de config. La funcion queda lista para las
    fuentes reales (F2), donde si existe ese efecto.
    """
    sub = tab.sort_values("lap").head(max(2, int(n_vueltas)))
    kg = sub["combustible_kg"].to_numpy(dtype=float)
    t = sub["tiempo_vuelta_s"].to_numpy(dtype=float)
    if len(sub) < 2 or not np.isfinite(kg).all() or not np.isfinite(t).all():
        return float(por_defecto)
    if float(np.ptp(kg)) <= 0.0:
        return float(por_defecto)
    pendiente = float(np.polyfit(kg, t, 1)[0])
    # una pendiente demasiado pequena o negativa no es fisica: usa el valor fijo
    if not np.isfinite(pendiente) or pendiente < 0.1 * por_defecto:
        return float(por_defecto)
    return pendiente


def proxy_degradacion(df: pd.DataFrame, cfg: dict, fs: float | None = None) -> pd.DataFrame:
    """Proxy de degradacion por vuelta a partir del tiempo corregido."""
    et = cfg["etiquetas"]
    tab = tiempos_por_vuelta(df, fs=fs)

    k_fuel = float(et["k_fuel_s_kg"])
    if et.get("calibrar_k_fuel", False):
        k_fuel = calibrar_k_fuel(tab, et.get("k_fuel_calib_vueltas", 3), k_fuel)
    tab["k_fuel_s_kg"] = k_fuel
    tab["t_corr_s"] = tab["tiempo_vuelta_s"] - k_fuel * tab["combustible_kg"]

    ref_laps = list(et["ref_vueltas"])
    ref = tab.loc[tab["lap"].isin(ref_laps), "t_corr_s"].median()
    tab["delta_s"] = (tab["t_corr_s"] - ref).clip(lower=0.0)

    delta = tab["delta_s"].to_numpy(dtype=float)
    ventana = int(et["savgol_ventana"])
    orden = int(et["savgol_orden"])
    if len(delta) >= ventana and ventana > orden:
        delta = savgol_filter(delta, ventana, orden)
    delta = np.clip(delta, 0.0, None)
    delta = np.maximum.accumulate(delta)  # monotono

    maximo = float(delta.max()) if delta.size else 0.0
    tab["degradacion_proxy"] = delta / maximo if maximo > 0 else 0.0
    return tab


def verdad_por_vuelta(verdad: pd.DataFrame) -> pd.DataFrame:
    """Promedia la degradacion verdadera por vuelta (fuente F1)."""
    return (
        verdad.groupby("lap")["degradacion"]
        .mean()
        .rename("degradacion")
        .reset_index()
    )


def comparar_proxy(tab_proxy: pd.DataFrame, verdad: pd.DataFrame) -> dict:
    """Metricas de calidad del proxy contra la degradacion verdadera."""
    m = tab_proxy[["lap", "degradacion_proxy"]].merge(verdad, on="lap", how="inner")
    if len(m) < 2:
        return {"n": len(m), "mae": float("nan"), "rmse": float("nan"), "corr": float("nan")}
    a = m["degradacion_proxy"].to_numpy(dtype=float)
    b = m["degradacion"].to_numpy(dtype=float)
    dif = a - b
    corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else float("nan")
    return {
        "n": int(len(m)),
        "mae": float(np.mean(np.abs(dif))),
        "rmse": float(np.sqrt(np.mean(dif**2))),
        "corr": corr,
    }
