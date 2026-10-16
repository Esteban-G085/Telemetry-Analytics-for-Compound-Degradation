"""Calculos de modelos y espectro sobre una sesion ya procesada.

Reutiliza `src.modelo`, `src.evaluacion` y `scipy.signal.welch`; no reimplementa
la ciencia de la Etapa 1. Aqui solo se orquesta y se adapta la salida a JSON.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
from scipy.signal import welch

from src import evaluacion, modelo

from backend.servicios.adaptador_pipeline import Sesion


def _cfg_alpha(cfg: dict, alpha: float) -> dict:
    """Copia de config con una unica alpha de Ridge (fija el slider, sin CV)."""
    c = copy.deepcopy(cfg)
    c["modelo"]["ridge_alphas"] = [float(alpha)]
    return c


def _prop_test(sesion: Sesion, prop_test: float | None) -> float:
    return float(prop_test if prop_test is not None else sesion.cfg["modelo"]["prop_test"])


def _referencia(sesion: Sesion) -> dict:
    """Series por vuelta de referencia para la Vista 3 (§3.3).

    ``verdad`` es la degradacion real (F1/F2) o el proxy si no hay verdad
    registrada; ``proxy`` es siempre el proxy de tiempos. Ambas ya estan
    normalizadas en [0, 1] por `src.etiquetas`.
    """
    verdad = sesion.degradacion_vuelta()
    proxy = sesion.proxy.set_index("lap")["degradacion_proxy"].sort_index()
    return {
        "verdad_laps": [int(l) for l in verdad.index],
        "verdad": [float(v) for v in verdad.to_numpy()],
        "proxy_laps": [int(l) for l in proxy.index],
        "proxy": [float(v) for v in proxy.to_numpy()],
    }


# --------------------------------------------------------------------------
# Ridge
# --------------------------------------------------------------------------
def ridge_por_vuelta(
    sesion: Sesion,
    *,
    alpha: float | None = None,
    excluir: tuple[str, ...] = (),
    prop_test: float | None = None,
) -> dict:
    """Ridge a nivel ventana agregado por vuelta.

    ``alpha=None`` usa la validacion cruzada de la Etapa 1; un valor concreto
    fija la regularizacion (comportamiento del slider de la Vista 4).
    """
    feats = sesion.feats
    if feats.empty:
        raise ValueError("La sesion no genero ventanas validas")

    X, cols = modelo.matriz_features(feats, excluir=tuple(excluir))
    laps = feats["lap"].to_numpy()
    tr, te = modelo.split_temporal(np.unique(laps), _prop_test(sesion, prop_test))
    m_tr = np.isin(laps, tr)

    cfg_fit = _cfg_alpha(sesion.cfg, alpha) if alpha is not None else sesion.cfg
    ridge = modelo.entrenar_ridge(X[m_tr], sesion.y_ventana[m_tr], laps[m_tr], cfg_fit)
    pred = modelo.predecir_ridge(ridge, X)

    serie = pd.DataFrame({"lap": laps, "pred": pred}).groupby("lap")["pred"].mean()
    verdad = sesion.degradacion_vuelta()

    te = [int(l) for l in te]
    pred_te = np.array([serie.get(l, np.nan) for l in te], dtype=float)
    true_te = np.array([verdad.get(l, np.nan) for l in te], dtype=float)
    met = evaluacion.metricas(true_te, pred_te)

    umbral = float(sesion.cfg["etiquetas"]["umbral_caida"])
    return {
        "alpha": float(ridge["alpha"]),
        "cv_mae": float(ridge["cv_mae"]),
        "excluir": list(excluir),
        "laps_all": [int(l) for l in serie.index],
        "pred_all": [float(v) for v in serie.to_numpy()],
        "laps_test": te,
        "pred_test": [float(v) for v in pred_te],
        "true_test": [float(v) for v in true_te],
        "metricas": {k: float(v) for k, v in met.items()},
        "error_caida": evaluacion.error_vuelta_caida(true_te, pred_te, umbral),
        "importancias": modelo.importancias(ridge, cols).to_dict("records"),
        **_referencia(sesion),
    }


# --------------------------------------------------------------------------
# Kalman
# --------------------------------------------------------------------------
def kalman_por_vuelta(
    sesion: Sesion,
    *,
    q_nivel: float,
    q_pendiente: float,
    r: float,
    monotono: bool = True,
    prop_test: float | None = None,
) -> dict:
    """Filtro nivel+pendiente sobre la degradacion por vuelta."""
    verdad = sesion.degradacion_vuelta()
    laps = np.array(sorted(int(l) for l in verdad.index))
    tr, te = modelo.split_temporal(laps, _prop_test(sesion, prop_test))

    y_tr = verdad.loc[tr].to_numpy(dtype=float)
    y_te = verdad.loc[te].to_numpy(dtype=float)

    kal = modelo.KalmanDegradacion(q_nivel, q_pendiente, r, monotono=monotono)
    res = kal.filtrar(y_tr)
    medias, var = kal.predecir(res, len(te))

    z = float(sesion.cfg["evaluacion"]["z"])
    desv = np.sqrt(np.maximum(var, 0.0))
    met = evaluacion.metricas(y_te, medias)
    umbral = float(sesion.cfg["etiquetas"]["umbral_caida"])
    return {
        "laps_train": [int(l) for l in tr],
        "laps_test": [int(l) for l in te],
        "nivel": [float(v) for v in res["nivel"]],
        "pendiente": [float(v) for v in res["pendiente"]],
        "pred": [float(v) for v in medias],
        "var": [float(v) for v in var],
        "banda_inf": [float(v) for v in medias - z * desv],
        "banda_sup": [float(v) for v in medias + z * desv],
        "verdad_test": [float(v) for v in y_te],
        "z": z,
        "metricas": {k: float(v) for k, v in met.items()},
        "cobertura": evaluacion.cobertura_bandas(y_te, medias, var, z),
        "error_caida": evaluacion.error_vuelta_caida(y_te, medias, umbral),
        **_referencia(sesion),
    }


# --------------------------------------------------------------------------
# Espectro (Welch)
# --------------------------------------------------------------------------
def espectro(
    sesion: Sesion,
    canal: str,
    *,
    lap: int | None = None,
    nperseg: int | None = None,
) -> dict:
    """PSD de Welch del canal, crudo vs. limpio, en dB/Hz."""
    fs = sesion.fs
    nperseg_cfg = int(sesion.cfg["features"]["welch_nperseg"])
    nperseg = int(nperseg if nperseg is not None else nperseg_cfg)

    limpio = sesion.limpio
    crudo = sesion.crudo
    if canal not in limpio.columns:
        raise ValueError(f"Canal desconocido: {canal}")

    if lap is not None:
        limpio = limpio[limpio["lap"] == lap]
        if crudo is not None:
            crudo = crudo[crudo["lap"] == lap]

    def _psd(df: pd.DataFrame | None):
        if df is None or df.empty:
            return None
        x = df[canal].to_numpy(dtype=float)
        x = x[np.isfinite(x)]
        n = int(min(nperseg, len(x)))
        if n < 8:
            return None
        noverlap = n // 2
        f, p = welch(x, fs=fs, nperseg=n, noverlap=noverlap)
        return f, p

    res_limpio = _psd(limpio)
    res_crudo = _psd(crudo)
    if res_limpio is None:
        raise ValueError("Muestras insuficientes para estimar la PSD")

    freqs = [float(v) for v in res_limpio[0]]

    def _db(p):
        return [float(10.0 * np.log10(max(v, 1e-20))) for v in p]

    bandas = sesion.cfg["features"]["bandas_hz"]
    return {
        "canal": canal,
        "lap": lap,
        "fs": fs,
        "nperseg": nperseg,
        "delta_f": round(fs / nperseg, 4),
        "freqs": freqs,
        "psd_limpio_db": _db(res_limpio[1]),
        "psd_crudo_db": _db(res_crudo[1]) if res_crudo is not None else None,
        "bandas": bandas,
        "corte_hz": float(sesion.cfg["limpieza"]["filtro"]["corte_hz"]),
    }


def robustez_snr(sesion: Sesion, snr_db: list[float] | None = None, prop_test: float | None = None) -> list[dict]:
    """MAE de Ridge contra ruido inyectado en el input (Vista 5)."""
    feats = sesion.feats
    X, _ = modelo.matriz_features(feats)
    laps = feats["lap"].to_numpy()
    tr, te = modelo.split_temporal(np.unique(laps), _prop_test(sesion, prop_test))
    m_tr = np.isin(laps, tr)
    m_te = np.isin(laps, te)
    ridge = modelo.entrenar_ridge(X[m_tr], sesion.y_ventana[m_tr], laps[m_tr], sesion.cfg)
    valores = snr_db if snr_db is not None else sesion.cfg["evaluacion"]["snr_db"]
    return evaluacion.prueba_robustez_snr(
        ridge, X[m_te], sesion.y_ventana[m_te], valores, rng=np.random.default_rng(7)
    )
