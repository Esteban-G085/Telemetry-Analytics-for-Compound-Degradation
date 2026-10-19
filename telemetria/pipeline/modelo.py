"""Modelos de prediccion de degradacion: Ridge y filtro de Kalman (Etapa 1).

Dos granularidades:
  - Ridge: nivel ventana (features -> escalar de degradacion).
  - Kalman: nivel vuelta (seguimiento y prediccion del escalar).
Ambos se comparan a nivel de vuelta.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import StandardScaler

from telemetria.pipeline.etiquetas import verdad_por_vuelta


# --------------------------------------------------------------------------
# Ridge
# --------------------------------------------------------------------------
def matriz_features(tabla: pd.DataFrame, excluir: tuple[str, ...] = ()):
    """Devuelve (X, columnas) a partir de una tabla de features.

    ``excluir`` permite la ablacion por subcadenas (por ejemplo quitar las
    features derivadas de slip o temperatura). Nunca incluye la etiqueta
    (``degradacion``) ni columnas auxiliares.
    """
    reservadas = {"lap", "degradacion", "t_inicio"}
    columnas = [
        c
        for c in tabla.columns
        if c not in reservadas and np.issubdtype(tabla[c].dtype, np.number)
    ]
    if excluir:
        columnas = [c for c in columnas if not any(e in c for e in excluir)]
    return tabla[columnas].to_numpy(dtype=float), columnas


def split_temporal(laps, prop_test: float):
    """Divide vueltas en train/test por bloques contiguos (sin mezclar)."""
    laps = np.sort(np.unique(np.asarray(laps)))
    n_test = max(1, int(round(len(laps) * prop_test)))
    corte = max(1, len(laps) - n_test)
    return laps[:corte], laps[corte:]


def entrenar_ridge(X: np.ndarray, y: np.ndarray, laps, cfg: dict) -> dict:
    """Entrena Ridge con validacion cruzada temporal agrupada por vuelta.

    El escalador se ajusta SOLO con el train de cada fold (sin fuga). Se
    descartan las columnas constantes en train y se acota la estandarizacion
    (``ridge_clip``) para que una feature casi constante no explote al
    extrapolar fuera del rango visto.
    """
    laps = np.asarray(laps)
    alphas = list(cfg["modelo"]["ridge_alphas"])
    k = int(cfg["modelo"]["cv_bloques"])
    clip = float(cfg["modelo"].get("ridge_clip", 0.0) or 0.0)
    vueltas = np.sort(np.unique(laps))
    k = max(2, min(k, len(vueltas)))
    bloques = np.array_split(vueltas, k)

    # solo columnas con variacion real en train
    utiles = X.std(axis=0) > 0.0
    if not utiles.any():
        utiles = np.ones(X.shape[1], dtype=bool)
    X = X[:, utiles]

    mejor_err = np.inf
    mejor_alpha = alphas[0]
    for alpha in alphas:
        errores = []
        for i in range(1, k):
            tr = np.concatenate(bloques[:i])
            va = bloques[i]
            m_tr = np.isin(laps, tr)
            m_va = np.isin(laps, va)
            if m_tr.sum() == 0 or m_va.sum() == 0:
                continue
            esc = StandardScaler().fit(X[m_tr])
            esc.scale_ = np.maximum(esc.scale_, 1e-8)
            pred = _predecir(esc, Ridge(alpha=alpha).fit(esc.transform(X[m_tr]), y[m_tr]), X[m_va], clip)
            errores.append(mean_absolute_error(y[m_va], pred))
        err = float(np.mean(errores)) if errores else np.inf
        if err < mejor_err:
            mejor_err, mejor_alpha = err, alpha

    escalador = StandardScaler().fit(X)
    escalador.scale_ = np.maximum(escalador.scale_, 1e-8)
    modelo = Ridge(alpha=mejor_alpha).fit(escalador.transform(X), y)
    return {
        "escalador": escalador,
        "ridge": modelo,
        "alpha": mejor_alpha,
        "cv_mae": mejor_err,
        "utiles": utiles,
        "clip": clip,
    }


def _predecir(escalador, ridge, X: np.ndarray, clip: float) -> np.ndarray:
    Z = escalador.transform(X)
    if clip and clip > 0:
        Z = np.clip(Z, -clip, clip)
    return ridge.predict(Z)


def predecir_ridge(modelo: dict, X: np.ndarray) -> np.ndarray:
    return _predecir(
        modelo["escalador"],
        modelo["ridge"],
        X[:, modelo["utiles"]],
        modelo.get("clip", 0.0),
    )


def importancias(modelo: dict, columnas: list[str]) -> pd.DataFrame:
    """Coeficientes estandarizados (utiles para la verificacion fisica)."""
    cols = [c for c, u in zip(columnas, modelo["utiles"]) if u]
    return pd.DataFrame(
        {"feature": cols, "coeficiente": modelo["ridge"].coef_}
    ).sort_values("coeficiente")


# --------------------------------------------------------------------------
# Filtro de Kalman
# --------------------------------------------------------------------------
class KalmanDegradacion:
    """Modelo nivel + tendencia sobre la degradacion por vuelta.

    Estado x = [nivel, pendiente]. Q y R se fijan a mano (no se estiman).
    """

    def __init__(self, q_nivel: float, q_pendiente: float, r: float, monotono: bool = True):
        self.F = np.array([[1.0, 1.0], [0.0, 1.0]])
        self.H = np.array([[1.0, 0.0]])
        self.Q = np.diag([q_nivel, q_pendiente])
        self.R = np.array([[r]])
        self.I = np.eye(2)
        self.monotono = monotono

    def paso(self, x: np.ndarray, P: np.ndarray, obs: float, r: float | None = None,
             nivel_prev: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Una iteracion predictor-corrector (permite Kalman incremental, B5).

        ``r`` permite dar a una observacion concreta un ruido distinto al global
        (por ejemplo la vuelta en curso, que es una media parcial ruidosa, B4).
        ``nivel_prev`` reproduce el clamp monotono entre iteraciones.
        """
        R = self.R if r is None else np.array([[float(r)]])
        x = self.F @ x
        P = self.F @ P @ self.F.T + self.Q
        S = self.H @ P @ self.H.T + R
        K = P @ self.H.T @ np.linalg.inv(S)
        x = x + (K @ (np.array([[obs]]) - self.H @ x)).ravel()
        P = (self.I - K @ self.H) @ P
        if self.monotono:
            if nivel_prev is not None and x[0] < nivel_prev:
                x[0] = nivel_prev
            if x[1] < 0.0:
                x[1] = 0.0
        return x, P

    def filtrar(self, observaciones) -> dict:
        obs = np.asarray(observaciones, dtype=float)
        n = len(obs)
        x = np.array([obs[0], 0.0])
        P = np.diag([1.0, 1e-4])
        nivel = np.zeros(n)
        pendiente = np.zeros(n)
        var_nivel = np.zeros(n)
        for k in range(n):
            x, P = self.paso(x, P, float(obs[k]), nivel_prev=(nivel[k - 1] if k > 0 else None))
            nivel[k] = x[0]
            pendiente[k] = x[1]
            var_nivel[k] = P[0, 0]
        return {
            "nivel": nivel,
            "pendiente": pendiente,
            "var_nivel": var_nivel,
            "x": x,
            "P": P,
        }

    def predecir(self, resultado: dict, pasos: int):
        """Predice las proximas ``pasos`` vueltas con su varianza.

        La varianza de la prediccion incluye tanto la propagacion de la
        covarianza filtrada como el **ruido de proceso acumulado** del horizonte:
        ``Var_h = F^h P F^h' + sum_{j=0}^{h-1} F^j Q F^j'``. Omitir el segundo
        termino subestima las bandas.
        """
        x, P = resultado["x"], resultado["P"]
        medias = np.zeros(pasos)
        varianzas = np.zeros(pasos)
        acumulado = np.zeros((2, 2))
        Fj = self.I.copy()
        for h in range(1, pasos + 1):
            acumulado = acumulado + Fj @ self.Q @ Fj.T
            Fh = np.linalg.matrix_power(self.F, h)
            medias[h - 1] = float((Fh @ x)[0])
            varianzas[h - 1] = float(((Fh @ P @ Fh.T) + acumulado)[0, 0])
            Fj = Fj @ self.F
        return medias, varianzas


# --------------------------------------------------------------------------
# Utilidades de etiquetas a nivel ventana / vuelta
# --------------------------------------------------------------------------
def etiquetas_por_ventana(features: pd.DataFrame, verdad: pd.DataFrame, cfg: dict) -> np.ndarray:
    """Degradacion media de cada ventana, interpolando la verdad por muestra."""
    t = verdad["timestamp_s"].to_numpy(dtype=float)
    d = verdad["degradacion"].to_numpy(dtype=float)
    w = float(cfg["ventana_s"])
    t0 = features["t_inicio"].to_numpy(dtype=float)
    d0 = np.interp(t0, t, d)
    d1 = np.interp(t0 + w, t, d)
    return 0.5 * (d0 + d1)


def preparar_vuelta(por_vuelta: pd.DataFrame, verdad: pd.DataFrame) -> pd.DataFrame:
    v = verdad_por_vuelta(verdad)
    return por_vuelta.merge(v, on="lap", how="inner").sort_values("lap").reset_index(drop=True)
