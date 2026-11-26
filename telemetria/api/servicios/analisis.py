"""Calculos de modelos y espectro sobre una sesion ya procesada.

Reutiliza `src.modelo`, `src.evaluacion` y `scipy.signal.welch`; no reimplementa
la ciencia de la Etapa 1. Aqui solo se orquesta y se adapta la salida a JSON.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
from scipy.signal import welch

from telemetria.pipeline import evaluacion, modelo

from telemetria.api.servicios.adaptador_pipeline import Sesion


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
        "referencia_usada": (
            "verdad_simulada" if getattr(sesion, "verdad", None) is not None else "proxy"
        ),
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

    pred_train = np.array([serie.get(int(l), np.nan) for l in tr], dtype=float)
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
        "laps_train": [int(l) for l in tr],
        "pred_train": [float(v) for v in pred_train],
        "laps_test": te,
        "pred_test": [float(v) for v in pred_te],
        "n_laps_train": int(len(tr)),
        "n_laps_test": int(len(te)),
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
        "n_laps_train": int(len(tr)),
        "n_laps_test": int(len(te)),
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
        return {
            "n_efectivo": n,
            "n_muestras": int(len(x)),
            "freqs": [float(v) for v in f],
            "psd": p,
        }

    res_limpio = _psd(limpio)
    res_crudo = _psd(crudo)
    if res_limpio is None:
        raise ValueError("Muestras insuficientes para estimar la PSD")

    def _db(p):
        return [float(10.0 * np.log10(max(v, 1e-20))) for v in p]

    bandas = sesion.cfg["features"]["bandas_hz"]
    n_limpio = res_limpio["n_efectivo"]
    return {
        "canal": canal,
        "lap": lap,
        "fs": fs,
        # ``nperseg`` es el tamaño REAL usado por Welch. El valor pedido por la
        # GUI/config se conserva aparte para no confundir resolución deseada y
        # resolución obtenida.
        "nperseg": n_limpio,
        "nperseg_solicitado": int(nperseg),
        "n_muestras_limpio": res_limpio["n_muestras"],
        "delta_f": round(fs / n_limpio, 4),
        "freqs": res_limpio["freqs"],
        "psd_limpio_db": _db(res_limpio["psd"]),
        "nperseg_crudo": res_crudo["n_efectivo"] if res_crudo is not None else None,
        "n_muestras_crudo": res_crudo["n_muestras"] if res_crudo is not None else None,
        "delta_f_crudo": (
            round(fs / res_crudo["n_efectivo"], 4) if res_crudo is not None else None
        ),
        "freqs_crudo": res_crudo["freqs"] if res_crudo is not None else None,
        "psd_crudo_db": _db(res_crudo["psd"]) if res_crudo is not None else None,
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
# Features del modelo
# --------------------------------------------------------------------------
def lista_features(sesion: Sesion) -> list[str]:
    """Nombres de las features numericas que entran al modelo."""
    if sesion.feats.empty:
        return []
    _, cols = modelo.matriz_features(sesion.feats)
    return list(cols)


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


def sensores(
    sesion: Sesion,
    caidos: list[dict] | None = None,
    prop_test: float | None = None,
    modo: str = "combinado",
) -> dict:
    """MAE de Ridge al desconectar canales (Vista 5, §3.5).

    Existen dos experimentos distintos:

    * ``modo="combinado"`` desconecta todos los sensores solicitados a la vez.
      Es el contrato historico de la API y mantiene las claves planas.
    * ``modo="individual"`` desconecta un sensor cada vez. Cada fila se
      re-entrena por separado contra el **mismo** baseline temporal; nunca se
      reparte el MAE de una evaluacion conjunta entre los sensores.

    ``caidos`` es una lista de ``{"canal": ..., "rueda": ...}``. Tambien se
    reporta el MAE del suavizado de Kalman sobre la serie de Ridge, para ver
    como compensa el ruido.
    """
    if modo not in ("combinado", "individual"):
        raise ValueError(f"Modo de ablacion desconocido: {modo}")

    feats = sesion.feats
    if feats.empty:
        raise ValueError("La sesion no genero ventanas validas")

    X_all, cols = modelo.matriz_features(feats)
    laps = feats["lap"].to_numpy()
    verdad = sesion.degradacion_vuelta()
    tr, te = modelo.split_temporal(np.unique(laps), _prop_test(sesion, prop_test))
    if len(tr) < 2 or len(te) < 1:
        raise ValueError("La sesion no tiene suficientes vueltas para comparar el fallo")

    met_base, pred_base = _ajustar_y_evaluar(sesion, X_all, laps, tr, te, verdad)
    mae_base = float(met_base["mae"])
    true_te = np.array([verdad.get(int(l), np.nan) for l in te], dtype=float)
    mae_kalman_base = _mae_kalman(sesion, pred_base, true_te)
    laps_test = [int(l) for l in te]
    solicitados = list(caidos or [])

    def _evaluar(entradas: list[dict]) -> dict:
        quitadas: set[str] = set()
        for s in entradas:
            quitadas.update(columnas_de_sensor(cols, s.get("canal", ""), s.get("rueda")))
        keep = [i for i, c in enumerate(cols) if c not in quitadas]
        resultado = {
            "caidos": [dict(s) for s in entradas],
            "columnas_quitadas": sorted(quitadas),
            "n_features_base": len(cols),
            "n_features": len(keep),
            "mae_base": mae_base,
            "metricas_base": {k: float(v) for k, v in met_base.items()},
            "mae_kalman_base": mae_kalman_base,
            "laps_test": list(laps_test),
            "error": None,
        }
        if not keep:
            resultado["error"] = (
                "El fallo simulado quita todas las features del modelo; "
                "no se puede ajustar Ridge sin entradas."
            )
            return resultado
        try:
            met, pred = _ajustar_y_evaluar(sesion, X_all[:, keep], laps, tr, te, verdad)
        except ValueError as exc:
            resultado["error"] = f"No hay suficientes muestras para repetir el experimento: {exc}"
            return resultado
        mae = float(met["mae"])
        resultado.update(
            {
                "mae": mae,
                "delta": mae - mae_base,
                "delta_rel": (mae / mae_base - 1.0) if mae_base > 0 else None,
                "mae_kalman": _mae_kalman(sesion, pred, true_te),
                "metricas": {k: float(v) for k, v in met.items()},
            }
        )
        return resultado

    if modo == "individual":
        resultados = [_evaluar([s]) for s in solicitados]
    else:
        combinado = _evaluar(solicitados)
        if combinado["error"]:
            raise ValueError(combinado["error"])
        resultados = [combinado]

    respuesta = {
        "modo": modo,
        "caidos": solicitados,
        "baseline": {
            "mae": mae_base,
            "metricas": {k: float(v) for k, v in met_base.items()},
            "mae_kalman": mae_kalman_base,
            "n_features": len(cols),
            "laps_test": list(laps_test),
        },
        "resultados": resultados,
        "mae_base": mae_base,
        "n_features_base": len(cols),
        "laps_test": list(laps_test),
    }
    if modo == "combinado":
        # Contrato historico: la GUI anterior y otros clientes leen estas
        # claves planas. Solo se rellenan para la evaluacion conjunta.
        respuesta.update({k: v for k, v in resultados[0].items() if k != "caidos"})
    return respuesta
