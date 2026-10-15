"""Metricas y evaluacion (Etapa 1)."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def metricas(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    r2 = float(r2_score(y_true, y_pred)) if len(y_true) > 1 else float("nan")
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": r2,
    }


def baselines(y_train, y_test) -> dict:
    y_train = np.asarray(y_train, dtype=float)
    y_test = np.asarray(y_test, dtype=float)
    return {
        "baseline_media": metricas(y_test, np.full_like(y_test, y_train.mean())),
        "baseline_ultimo": metricas(y_test, np.full_like(y_test, y_train[-1])),
    }


def vuelta_de_caida(y, umbral: float):
    """Primer indice (0-based) donde y supera el umbral, o None."""
    y = np.asarray(y, dtype=float)
    idx = np.argmax(y >= umbral)
    if y.size == 0 or y[idx] < umbral:
        return None
    return int(idx)


def error_vuelta_caida(y_true, y_pred, umbral: float) -> float:
    i_true = vuelta_de_caida(y_true, umbral)
    i_pred = vuelta_de_caida(y_pred, umbral)
    if i_true is None or i_pred is None:
        return float("nan")
    return float(abs(i_pred - i_true))


def cobertura_bandas(y_true, media, varianza, z: float = 1.96) -> float:
    """Fraccion de observaciones dentro de la banda (deberia rondar 0.95)."""
    y_true = np.asarray(y_true, dtype=float)
    media = np.asarray(media, dtype=float)
    desv = np.sqrt(np.asarray(varianza, dtype=float))
    lo = media - z * desv
    hi = media + z * desv
    return float(np.mean((y_true >= lo) & (y_true <= hi)))


def verificacion_fisica(importancias) -> list[dict]:
    """Contrasta el signo de los coeficientes con la fisica esperada.

    Se espera coeficiente **positivo** en los grupos ligados al desgaste
    (grados-segundo, temperatura, slip, carga, trabajo de friccion, PSD).
    Ojo: las features estan muy correlacionadas entre si, asi que los signos
    individuales **no** son concluyentes; esto es un diagnostico, no una
    aprobacion automatica.

    Por cada grupo se devuelve:
      - ``aciertos``: cuantos coeficientes tienen el signo esperado;
      - ``suma``: suma de los coeficientes del grupo (mas robusta que el signo
        individual cuando hay colinealidad, porque los efectos que se cancelan
        entre si se compensan a nivel de grupo);
      - ``coincide``: si la suma tiene el signo esperado.
    """
    grupos = ("grados_segundo", "temp", "slip", "carga", "trabajo", "psd")
    filas = []
    for grupo in grupos:
        sub = importancias[importancias["feature"].str.contains(grupo, regex=False)]
        if sub.empty:
            continue
        coef = sub["coeficiente"].to_numpy(dtype=float)
        filas.append(
            {
                "grupo": grupo,
                "n": int(len(coef)),
                "esperado": "positivo",
                "aciertos": int((coef > 0).sum()),
                "suma": float(coef.sum()),
                "coincide": bool(coef.sum() > 0),
            }
        )
    return filas


def sensibilidad_kalman(y_train, y_test, cfg: dict, valores_r=None) -> list[dict]:
    """MAE y cobertura de las bandas de Kalman para varios R.

    Con ~10 vueltas de test la cobertura solo puede tomar valores multiplos de
    0.1, asi que no tiene sentido perseguir un 0.95 exacto. Lo util es ver como
    cambian MAE y cobertura al mover R (el plan pide reportar sensibilidad).
    """
    from src.modelo import KalmanDegradacion

    kc = cfg["modelo"]["kalman"]
    if valores_r is None:
        valores_r = kc.get("sensibilidad_r", [kc["r"]])
    z = float(cfg["evaluacion"]["z"])
    y_train = np.asarray(y_train, dtype=float)
    y_test = np.asarray(y_test, dtype=float)
    filas = []
    for r in valores_r:
        kal = KalmanDegradacion(
            kc["q_nivel"], kc["q_pendiente"], float(r), monotono=kc.get("monotono", True)
        )
        res = kal.filtrar(y_train)
        medias, var = kal.predecir(res, len(y_test))
        met = metricas(y_test, medias)
        filas.append(
            {
                "r": float(r),
                "mae": float(met["mae"]),
                "cobertura": cobertura_bandas(y_test, medias, var, z),
            }
        )
    return filas


def prueba_robustez_snr(modelo: dict, X, y_true, snr_db, rng=None, z: float | None = None):
    """MAE contra SNR creciente de ruido agregado al input (no a la etiqueta)."""
    from src.modelo import predecir_ridge

    rng = rng or np.random.default_rng(0)
    X = np.asarray(X, dtype=float)
    y_true = np.asarray(y_true, dtype=float)
    desv = X.std(axis=0, keepdims=True)
    filas = []
    for snr in snr_db:
        sigma = desv * (10.0 ** (-np.asarray(snr, dtype=float) / 20.0))
        Xn = X + rng.normal(0.0, 1.0, X.shape) * sigma
        pred = predecir_ridge(modelo, Xn)
        filas.append({"snr_db": float(snr), "mae": float(mean_absolute_error(y_true, pred))})
    return filas
