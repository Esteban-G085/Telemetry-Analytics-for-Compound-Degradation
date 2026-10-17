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


# --------------------------------------------------------------------------
# Simulador de fallo de sensores (Vista 5, §3.5)
# --------------------------------------------------------------------------
# Que features dependen de cada canal crudo. ``pressure_psi`` no alimenta ninguna
# feature del modelo (queda vacio a proposito: muestra que su fallo es inocuo).
MAPA_SENSOR: dict[str, tuple[str, ...]] = {
    "wheel_slip": ("slip_", "psd_", "trabajo_friccion_"),
    "temp_core_c": ("temp_", "grados_segundo_"),
    "wheel_load_n": ("carga_", "trabajo_friccion_"),
    "pressure_psi": (),
    "speed_kmh": ("speed_",),
    "throttle": ("throttle_",),
    "brake": ("brake_",),
    "steering": ("steering_",),
}


def columnas_de_sensor(columnas: list[str], canal: str, rueda: str | None = None) -> list[str]:
    """Features que se pierden si falla ``canal`` (opcionalmente en una ``rueda``)."""
    familias = MAPA_SENSOR.get(canal, ())
    if not familias:
        return []
    if rueda is None:
        return [c for c in columnas if any(f in c for f in familias)]
    sufijo = "_" + str(rueda)
    return [c for c in columnas if any(f in c for f in familias) and c.endswith(sufijo)]


# --------------------------------------------------------------------------
# Dispersión y correlación de features (Vista 2, §3.2)
# --------------------------------------------------------------------------
def lista_features(sesion: Sesion) -> list[str]:
    """Nombres de las features numericas que entran al modelo."""
    if sesion.feats.empty:
        return []
    _, cols = modelo.matriz_features(sesion.feats)
    return list(cols)


def _agregar_por_vuelta(sesion: Sesion, nombre: str, verdad: pd.Series) -> tuple[list[int], list[float]]:
    if nombre == "degradacion":
        laps = [int(l) for l in verdad.index]
        return laps, [float(verdad.get(l, np.nan)) for l in laps]
    if nombre not in sesion.feats.columns:
        raise ValueError(f"Feature desconocida: {nombre}")
    agg = sesion.feats.groupby("lap")[nombre].mean()
    laps = [int(l) for l in agg.index]
    return laps, [float(v) for v in agg.to_numpy()]


def dispersion(sesion: Sesion, x: str, y: str | None = None) -> dict:
    """Dispersion por vuelta de dos features (o de una vs. la degradacion)."""
    if sesion.feats.empty:
        raise ValueError("La sesion no genero ventanas validas")
    verdad = sesion.degradacion_vuelta()
    laps_x, xs = _agregar_por_vuelta(sesion, x, verdad)
    y = y or "degradacion"
    laps_y, ys = _agregar_por_vuelta(sesion, y, verdad)
    mapa_y = dict(zip(laps_y, ys))

    px, py, laps = [], [], []
    for lap, xv in zip(laps_x, xs):
        yv = mapa_y.get(lap)
        if yv is None or not (np.isfinite(xv) and np.isfinite(yv)):
            continue
        px.append(xv)
        py.append(yv)
        laps.append(lap)

    corr = pendiente = intercepto = None
    recta = None
    if len(px) >= 3:
        a = np.asarray(px, dtype=float)
        b = np.asarray(py, dtype=float)
        if a.std() > 0 and b.std() > 0:
            corr = float(np.corrcoef(a, b)[0, 1])
            pendiente, intercepto = (float(v) for v in np.polyfit(a, b, 1))
            x0, x1 = float(a.min()), float(a.max())
            recta = {"x": [x0, x1], "y": [pendiente * x0 + intercepto, pendiente * x1 + intercepto]}
    return {
        "x": x,
        "y": y,
        "laps": laps,
        "px": px,
        "py": py,
        "n": len(px),
        "corr": corr,
        "pendiente": pendiente,
        "intercepto": intercepto,
        "recta": recta,
    }


def correlacion(sesion: Sesion, features: list[str] | None = None, max_features: int = 12) -> dict:
    """Matriz de correlacion (por vuelta) entre features y la degradacion."""
    if sesion.feats.empty:
        raise ValueError("La sesion no genero ventanas validas")
    cols = lista_features(sesion)
    if features:
        cols = [c for c in features if c in cols]
    else:
        # Una feature por familia (la de mayor |correlacion| con la degradacion),
        # para no devolver una matriz gigante e ilegible.
        verdad = sesion.degradacion_vuelta()
        lap_deg = pd.Series({int(l): float(verdad.get(l, np.nan)) for l in sesion.feats["lap"].unique()})
        por_familia: dict[str, tuple[float, str]] = {}
        agg = sesion.feats.groupby("lap")[cols].mean()
        for c in cols:
            serie = agg[c]
            fin = serie.notna() & lap_deg.reindex(serie.index).notna()
            if fin.sum() < 3:
                continue
            r = abs(float(np.corrcoef(serie[fin], lap_deg.reindex(serie.index)[fin])[0, 1]))
            if not np.isfinite(r):
                continue
            fam = c.split("_")[0]
            if fam not in por_familia or r > por_familia[fam][0]:
                por_familia[fam] = (r, c)
        cols = [c for _, c in sorted(por_familia.values(), reverse=True)][:max_features]

    verdad = sesion.degradacion_vuelta()
    agg = sesion.feats.groupby("lap")[cols].mean()
    agg["degradacion"] = [float(verdad.get(int(l), np.nan)) for l in agg.index]
    etiquetas = list(agg.columns)
    matriz = agg.corr().to_numpy(dtype=float)
    return {
        "etiquetas": etiquetas,
        "matriz": [[None if not np.isfinite(v) else float(v) for v in fila] for fila in matriz],
        "n": int(agg.shape[0]),
    }


def _ajustar_y_evaluar(
    sesion: Sesion, X: np.ndarray, laps: np.ndarray, tr, te, verdad: pd.Series
) -> tuple[dict, np.ndarray]:
    m_tr = np.isin(laps, tr)
    ridge = modelo.entrenar_ridge(X[m_tr], sesion.y_ventana[m_tr], laps[m_tr], sesion.cfg)
    pred = modelo.predecir_ridge(ridge, X)
    serie = pd.DataFrame({"lap": laps, "pred": pred}).groupby("lap")["pred"].mean()
    pred_te = np.array([serie.get(int(l), np.nan) for l in te], dtype=float)
    true_te = np.array([verdad.get(int(l), np.nan) for l in te], dtype=float)
    return evaluacion.metricas(true_te, pred_te), pred_te


def _mae_kalman(sesion: Sesion, pred_te: np.ndarray, true_te: np.ndarray) -> float | None:
    """MAE del suavizado de Kalman aplicado a la serie de Ridge (nivel)."""
    finito = np.isfinite(pred_te) & np.isfinite(true_te)
    if finito.sum() < 2:
        return None
    kc = sesion.cfg["modelo"]["kalman"]
    kal = modelo.KalmanDegradacion(
        kc["q_nivel"], kc["q_pendiente"], kc["r"], monotono=kc.get("monotono", True)
    )
    res = kal.filtrar(pred_te[finito])
    return float(np.mean(np.abs(true_te[finito] - res["nivel"])))


def sensores(sesion: Sesion, caidos: list[dict] | None = None, prop_test: float | None = None) -> dict:
    """MAE de Ridge al desconectar canales (Vista 5, §3.5).

    ``caidos`` es una lista de ``{"canal": ..., "rueda": ...}``. Se quitan del
    modelo todas las features derivadas de esos canales y se compara el MAE de
    test con el baseline (sin fallos). Tambien se reporta el MAE del suavizado
    de Kalman sobre la serie de Ridge, para ver como compensa el ruido.
    """
    feats = sesion.feats
    if feats.empty:
        raise ValueError("La sesion no genero ventanas validas")

    X_all, cols = modelo.matriz_features(feats)
    laps = feats["lap"].to_numpy()
    verdad = sesion.degradacion_vuelta()
    tr, te = modelo.split_temporal(np.unique(laps), _prop_test(sesion, prop_test))

    met_base, pred_base = _ajustar_y_evaluar(sesion, X_all, laps, tr, te, verdad)

    quitadas: set[str] = set()
    for s in caidos or []:
        quitadas.update(columnas_de_sensor(cols, s.get("canal", ""), s.get("rueda")))
    keep = [i for i, c in enumerate(cols) if c not in quitadas]
    if not keep:
        raise ValueError("El fallo simulado quita todas las features del modelo")

    met, pred = _ajustar_y_evaluar(sesion, X_all[:, keep], laps, tr, te, verdad)

    mae_base = float(met_base["mae"])
    mae = float(met["mae"])
    return {
        "caidos": list(caidos or []),
        "columnas_quitadas": sorted(quitadas),
        "n_features_base": len(cols),
        "n_features": len(keep),
        "mae_base": mae_base,
        "mae": mae,
        "delta": mae - mae_base,
        "delta_rel": (mae / mae_base - 1.0) if mae_base > 0 else None,
        "mae_kalman_base": _mae_kalman(sesion, pred_base, np.array([verdad.get(int(l), np.nan) for l in te], dtype=float)),
        "mae_kalman": _mae_kalman(sesion, pred, np.array([verdad.get(int(l), np.nan) for l in te], dtype=float)),
        "metricas": {k: float(v) for k, v in met.items()},
        "metricas_base": {k: float(v) for k, v in met_base.items()},
        "laps_test": [int(l) for l in te],
    }
