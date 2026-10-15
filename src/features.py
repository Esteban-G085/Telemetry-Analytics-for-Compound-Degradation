"""Segmentacion en ventanas y extraccion de features (Etapa 1).

Las funciones de ventana reciben un fragmento (una ventana) y no un archivo
completo: eso es lo que permite reutilizarlas en la Etapa 3 (tiempo real).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import welch

from src.config import RUEDAS

CANALES_RUEDA_FEATURES = ("wheel_slip", "temp_core_c", "wheel_load_n")


def _potencia_bandas(x: np.ndarray, fs: float, cfg: dict) -> tuple[float, float, float]:
    nperseg = int(cfg["features"]["welch_nperseg"])
    nperseg = int(min(nperseg, len(x)))
    if nperseg < 8:
        return 0.0, 0.0, 0.0
    noverlap = int(min(cfg["features"]["welch_noverlap"], nperseg - 1))
    freqs, psd = welch(x, fs=fs, nperseg=nperseg, noverlap=noverlap)
    bandas = cfg["features"]["bandas_hz"]

    def banda(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        if not m.any():
            return 0.0
        return float(np.trapezoid(psd[m], freqs[m]))

    return banda(*bandas["baja"]), banda(*bandas["media"]), banda(*bandas["alta"])


def features_ventana(ventana: pd.DataFrame, cfg: dict) -> dict:
    """Features de una ventana (todas las ruedas). Devuelve un dict plano."""
    fs = float(cfg["fs"])
    dt = 1.0 / fs
    umbral = float(cfg["features"]["temp_umbral_c"])

    speed = ventana["speed_kmh"].to_numpy(dtype=float)
    f: dict[str, float] = {
        "speed_mean": float(np.mean(speed)),
        "speed_std": float(np.std(speed)),
        "throttle_mean": float(np.mean(ventana["throttle"].to_numpy(dtype=float))),
        "brake_mean": float(np.mean(ventana["brake"].to_numpy(dtype=float))),
        "steering_std": float(np.std(ventana["steering"].to_numpy(dtype=float))),
    }

    speed_ms = speed / 3.6
    for w in RUEDAS:
        slip = ventana[f"wheel_slip_{w}"].to_numpy(dtype=float)
        carga = ventana[f"wheel_load_n_{w}"].to_numpy(dtype=float)
        temp = ventana[f"temp_core_c_{w}"].to_numpy(dtype=float)

        f[f"slip_mean_{w}"] = float(np.mean(slip))
        f[f"slip_std_{w}"] = float(np.std(slip))
        f[f"slip_absmax_{w}"] = float(np.max(np.abs(slip)))
        f[f"slip_rms_{w}"] = float(np.sqrt(np.mean(slip**2)))
        f[f"slip_energia_{w}"] = float(np.sum(slip**2) * dt)

        f[f"temp_mean_{w}"] = float(np.mean(temp))
        f[f"temp_std_{w}"] = float(np.std(temp))
        f[f"temp_max_{w}"] = float(np.max(temp))

        f[f"carga_mean_{w}"] = float(np.mean(carga))
        f[f"carga_max_{w}"] = float(np.max(carga))

        f[f"trabajo_friccion_{w}"] = float(np.sum(np.abs(slip) * carga * speed_ms) * dt)
        f[f"grados_segundo_{w}"] = float(np.sum(np.maximum(0.0, temp - umbral)) * dt)

        p_baja, p_media, p_alta = _potencia_bandas(slip, fs, cfg)
        f[f"psd_baja_{w}"] = p_baja
        f[f"psd_media_{w}"] = p_media
        f[f"psd_alta_{w}"] = p_alta
    return f


def features_por_ventanas(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Desliza la ventana por la senal limpia y devuelve una fila por ventana.

    Solo conserva ventanas enteras dentro de una misma vuelta.
    """
    fs = float(cfg["fs"])
    W = int(round(float(cfg["ventana_s"]) * fs))
    H = int(round(float(cfg["hop_s"]) * fs))
    if W <= 0 or H <= 0:
        raise ValueError("ventana_s y hop_s deben ser positivos")

    lap = df["lap"].to_numpy()
    valido = df["valido"].to_numpy() if "valido" in df.columns else np.ones(len(df), bool)
    ts = df["timestamp_s"].to_numpy()

    filas = []
    for inicio in range(0, len(df) - W + 1, H):
        fin = inicio + W
        if not valido[inicio:fin].all():
            continue
        if lap[inicio] != lap[fin - 1]:
            continue
        ventana = df.iloc[inicio:fin]
        feats = features_ventana(ventana, cfg)
        feats["lap"] = int(lap[inicio])
        feats["t_inicio"] = float(ts[inicio])
        filas.append(feats)

    if not filas:
        return pd.DataFrame()
    return pd.DataFrame(filas)


def agregar_por_vuelta(features: pd.DataFrame) -> pd.DataFrame:
    """Promedia las features de las ventanas de cada vuelta."""
    if features.empty:
        return features
    base = features.drop(columns=["t_inicio"])
    cols_num = [c for c in base.columns if c != "lap"]
    agrupado = base.groupby("lap")[cols_num].mean()
    conteo = base.groupby("lap").size().rename("n_ventanas")
    return pd.concat([agrupado, conteo], axis=1).reset_index()
