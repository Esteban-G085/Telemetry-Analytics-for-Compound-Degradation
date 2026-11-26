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
from sklearn.isotonic import IsotonicRegression


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


def ajustar_k_fuel_conjunto(tab: pd.DataFrame, cfg: dict) -> tuple[float, np.ndarray]:
    """Estima ``k_fuel`` y la degradacion monotona al mismo tiempo.

    La regresion de las primeras vueltas confunde masa de combustible con
    desgaste: al quemar combustible la vuelta se acorta, y al desgastarse el
    neumatico se alarga. Aqui se busca el ``k_fuel`` que mejor explica las
    duraciones una vez eliminada una tendencia **creciente** por vuelta
    (regresion isotona). Devuelve el k elegido y esa tendencia en segundos.
    """
    et = cfg["etiquetas"]
    por_defecto = float(et["k_fuel_s_kg"])
    kg = tab["combustible_kg"].to_numpy(dtype=float)
    t = tab["tiempo_vuelta_s"].to_numpy(dtype=float)
    if (
        len(tab) < 3
        or not np.isfinite(kg).all()
        or not np.isfinite(t).all()
        or float(np.ptp(kg)) <= 0.0
    ):
        return por_defecto, t - por_defecto * kg

    malla = et.get("k_fuel_grid", [0.0, 0.08, 0.001])
    try:
        inicio, fin, paso = (float(v) for v in malla)
        ks = np.arange(inicio, fin + 0.5 * paso, paso) if paso > 0 else np.array([por_defecto])
    except (TypeError, ValueError):
        ks = np.asarray(malla, dtype=float)
    if not ks.size:
        return por_defecto, t - por_defecto * kg

    orden = np.arange(len(tab))
    isotona = IsotonicRegression(increasing=True)
    candidatos = []
    for k in ks:
        residuo = t - float(k) * kg
        delta = isotona.fit_transform(orden, residuo)
        candidatos.append((float(np.sum((residuo - delta) ** 2)), float(k), delta))
    mejor_sse = min(c[0] for c in candidatos)
    # Un k demasiado grande siempre deja un residuo creciente (la isotona lo
    # copia y da SSE=0), asi que la funcion objetivo es plana por encima del
    # valor real. Desempata eligiendo el k mas pequeno que explica la serie:
    # es la correccion minima necesaria para que la degradacion no decrezca.
    tolerancia = max(1e-9, 1e-3 * mejor_sse)
    _, mejor_k, mejor_delta = next(c for c in candidatos if c[0] <= mejor_sse + tolerancia)
    return mejor_k, np.asarray(mejor_delta, dtype=float)


def proxy_degradacion(
    df: pd.DataFrame, cfg: dict, fs: float | None = None, metodo: str | None = None
) -> pd.DataFrame:
    """Proxy de degradacion por vuelta a partir del tiempo corregido.

    ``metodo='conjunto'`` usa :func:`ajustar_k_fuel_conjunto` en lugar de la
    calibracion por regresion de las primeras vueltas. La salida y la clave
    ``degradacion_proxy`` no cambian.
    """
    et = cfg["etiquetas"]
    tab = tiempos_por_vuelta(df, fs=fs)
    metodo = metodo or et.get("metodo_proxy", "corregido")

    k_fuel = float(et["k_fuel_s_kg"])
    if metodo == "conjunto":
        k_fuel, delta_ajustado = ajustar_k_fuel_conjunto(tab, cfg)
        tab["k_fuel_ajustado"] = k_fuel
        tab["t_corr_s"] = tab["tiempo_vuelta_s"] - k_fuel * tab["combustible_kg"]
        delta = np.asarray(delta_ajustado, dtype=float)
    else:
        if et.get("calibrar_k_fuel", False):
            k_fuel = calibrar_k_fuel(tab, et.get("k_fuel_calib_vueltas", 3), k_fuel)
        tab["k_fuel_s_kg"] = k_fuel
        tab["t_corr_s"] = tab["tiempo_vuelta_s"] - k_fuel * tab["combustible_kg"]
        delta = None

    ref_laps = list(et["ref_vueltas"])
    ref = tab.loc[tab["lap"].isin(ref_laps), "t_corr_s"].median()
    if delta is None:
        delta = (tab["t_corr_s"] - ref).clip(lower=0.0).to_numpy(dtype=float)
    else:
        delta = np.clip(delta - ref, 0.0, None)
    tab["delta_s"] = delta

    ventana = int(et["savgol_ventana"])
    orden = int(et["savgol_orden"])
    if len(delta) >= ventana and ventana > orden:
        delta = savgol_filter(delta, ventana, orden)
    delta = np.clip(delta, 0.0, None)
    delta = np.maximum.accumulate(delta)  # monotono

    maximo = float(delta.max()) if delta.size else 0.0
    tab["degradacion_proxy"] = delta / maximo if maximo > 0 else 0.0
    return tab


def proxy_por_energia(feats: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Degradacion proxy desde el trabajo de friccion acumulado por vuelta.

    Es una señal de desgaste alternativa al tiempo de vuelta: suma el trabajo
    de friccion de las cuatro ruedas por ventana y lo acumula a lo largo del
    stint. Se normaliza a ``[0, 1]`` con la misma filosofia que el proxy de
    tiempo. No cambia claves de la API; la columna nueva es interna.
    """
    if feats.empty or "lap" not in feats.columns:
        return pd.DataFrame(columns=["lap", "degradacion_energia"])

    columnas = [c for c in feats.columns if c.startswith("trabajo_friccion_")]
    if not columnas:
        columnas = [c for c in feats.columns if c.startswith("slip_energia_")]
    if not columnas:
        raise ValueError("No hay features de energia (trabajo_friccion/slip_energia)")

    energia_ventana = feats[columnas].clip(lower=0.0).sum(axis=1).to_numpy(dtype=float)
    tab = (
        pd.DataFrame({"lap": feats["lap"].to_numpy(), "energia": energia_ventana})
        .groupby("lap", as_index=False)["energia"]
        .sum()
        .sort_values("lap")
        .reset_index(drop=True)
    )
    acumulado = np.maximum.accumulate(tab["energia"].to_numpy(dtype=float))
    tab["energia_acumulada"] = acumulado

    # La primera vuelta es la referencia (neumatico fresco), igual que en el
    # proxy de tiempo: se mide trabajo acumulado *desde* esa vuelta.
    delta = acumulado - acumulado[0]
    et = cfg["etiquetas"]
    ventana, orden = int(et["savgol_ventana"]), int(et["savgol_orden"])
    if len(delta) >= ventana and ventana > orden:
        delta = savgol_filter(delta, ventana, orden)
    delta = np.clip(delta, 0.0, None)
    delta = np.maximum.accumulate(delta)

    maximo = float(delta.max()) if delta.size else 0.0
    tab["degradacion_energia"] = delta / maximo if maximo > 0 else 0.0
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
