"""Utilidades compartidas por los tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from telemetria.pipeline.config import RUEDAS, columnas_esquema


def df_esquema(n: int, fs: float = 100.0, lap: int = 1) -> pd.DataFrame:
    """DataFrame con el esquema completo y valores base razonables."""
    t = np.arange(n) / fs
    df = pd.DataFrame({"timestamp_s": t, "lap": np.full(n, lap, dtype=int)})
    df["speed_kmh"] = 100.0
    df["throttle"] = 0.2
    df["brake"] = 0.0
    df["steering"] = 0.0
    df["fuel_kg"] = 50.0
    for w in RUEDAS:
        df[f"temp_core_c_{w}"] = 90.0
        df[f"pressure_psi_{w}"] = 25.0
        df[f"wheel_slip_{w}"] = 0.0
        df[f"wheel_load_n_{w}"] = 4000.0
        df[f"dirty_level_{w}"] = 0.0
    return df[columnas_esquema()].copy()


def df_degradacion(degrad, fuel, k_fuel: float = 0.035, base_s: float = 90.0, fs: float = 100.0):
    """DataFrame por vueltas con duraciones controladas.

    duracion_i = base + k_fuel*fuel_i + degrad_i
    """
    degrad = np.asarray(degrad, dtype=float)
    fuel = np.asarray(fuel, dtype=float)
    dur = base_s + k_fuel * fuel + degrad
    empieza = np.concatenate([[0.0], np.cumsum(dur)[:-1]])

    ts, laps, fuels = [], [], []
    for i, (s, d) in enumerate(zip(empieza, dur)):
        t = np.arange(s, s + d, 1.0 / fs)
        ts.append(t)
        laps.append(np.full(t.size, i + 1))
        fuels.append(np.full(t.size, fuel[i]))

    t = np.concatenate(ts)
    df = df_esquema(t.size, fs=fs)
    df["timestamp_s"] = t
    df["lap"] = np.concatenate(laps)
    df["fuel_kg"] = np.concatenate(fuels)
    return df


def decodificar_float32(datos: bytes, n_canales: int) -> np.ndarray:
    """Inverso de la trama binaria del WS (`empaquetar_float32`)."""
    a = np.frombuffer(datos, dtype="<f4")
    if n_canales <= 0 or a.size % n_canales:
        raise ValueError("Tamano de trama incompatible con n_canales")
    return a.reshape(n_canales, a.size // n_canales)
