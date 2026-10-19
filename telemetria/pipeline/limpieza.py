"""Remuestreo, validacion y limpieza de senales (Etapa 1).

Orden del preprocesado:
  0. remuestreo a rejilla uniforme (con antialias)
  1. validacion de esquema
  2. marcado de valores fuera de rango fisico
  3. deteccion de outliers con mediana/MAD en ventana causal
  4. interpolacion de huecos cortos (sin cruzar vueltas)
  5. filtro pasa-bajas Butterworth en forma SOS, causal
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pandas as pd
from scipy.signal import butter, resample_poly, sosfilt, sosfilt_zi

from telemetria.pipeline.config import (
    RUEDAS,
    canales_filtrables,
    canales_fisicos,
    columnas_esquema,
)


def validar_esquema(df: pd.DataFrame) -> bool:
    """Verifica que el DataFrame cumple el contrato del proyecto."""
    faltan = [c for c in columnas_esquema() if c not in df.columns]
    if faltan:
        raise ValueError(f"Faltan columnas obligatorias: {faltan}")
    no_numericas = [
        c for c in columnas_esquema() if not np.issubdtype(df[c].dtype, np.number)
    ]
    if no_numericas:
        raise ValueError(f"Columnas no numericas: {no_numericas}")
    return True


def _resample_poly_df(df: pd.DataFrame, up: int, down: int, fs: float) -> pd.DataFrame:
    columnas = [c for c in df.columns if c != "timestamp_s"]
    datos = {}
    for c in columnas:
        # numpy.float64 -> float64 y NaN ya resueltos por el llamador
        datos[c] = resample_poly(np.asarray(df[c], dtype=float), up, down)
    n = len(next(iter(datos.values())))
    salida = pd.DataFrame(datos)
    salida["timestamp_s"] = np.arange(n) / fs
    if "lap" in salida:
        salida["lap"] = salida["lap"].round().astype(int)
    return salida[["timestamp_s"] + [c for c in columnas]]


def resamplear(
    df: pd.DataFrame,
    fs: float,
    fs_origen: float | None = None,
    columnas: list[str] | None = None,
) -> pd.DataFrame:
    """Lleva la senal a una rejilla uniforme a ``fs`` Hz con antialias.

    Interpola primero a una rejilla a la frecuencia de origen y luego
    decima con ``resample_poly`` (que incluye el filtro antialias).
    Preserva los NaN marcados en el origen.
    """
    fs = float(fs)
    t = df["timestamp_s"].to_numpy(dtype=float).copy()
    orden = np.argsort(t)
    df = df.iloc[orden].reset_index(drop=True)
    t = df["timestamp_s"].to_numpy(dtype=float)
    t = np.maximum.accumulate(t)
    t = t - t[0]

    if fs_origen is None:
        dt_med = float(np.median(np.diff(t)))
        fs_origen = 1.0 / dt_med
    fs_origen = float(fs_origen)

    n_u = int(np.floor(t[-1] * fs_origen)) + 1
    t_u = np.arange(n_u) / fs_origen

    columnas = columnas or [c for c in df.columns if c != "timestamp_s"]

    up, down = Fraction(fs / fs_origen).limit_denominator(200).as_integer_ratio()

    interpolado = {"timestamp_s": t_u}
    mascaras = {}
    for c in columnas:
        x = df[c].to_numpy(dtype=float)
        nan = np.isnan(x)
        if nan.any():
            x = pd.Series(x).interpolate(limit_direction="both").to_numpy(dtype=float)
        interpolado[c] = np.interp(t_u, t, x)
        if nan.any():
            mascaras[c] = np.interp(t_u, t, nan.astype(float)) > 0.5

    base = pd.DataFrame(interpolado)

    if (up, down) != (1, 1):
        salida = _resample_poly_df(base, up, down, fs)
        for c, m in mascaras.items():
            m_dec = resample_poly(m.astype(float), up, down) > 0.5
            salida.loc[m_dec, c] = np.nan
    else:
        salida = base
        salida["timestamp_s"] = np.arange(len(salida)) / fs
        for c, m in mascaras.items():
            salida.loc[m, c] = np.nan

    if "lap" in salida:
        # tras decimar, redondear de nuevo (puede haber quedado float por NaN)
        salida["lap"] = salida["lap"].ffill().bfill().round().astype(int)

    return salida.reset_index(drop=True)


def marcar_fuera_de_rango(
    df: pd.DataFrame, cfg: dict, diagnostico: dict | None = None
) -> tuple[pd.DataFrame, dict]:
    """Marca fuera de rango fisico.

    Si se pasa ``diagnostico`` (dict) se guarda en
    ``diagnostico["mascara_fuera_rango"]`` un dict ``columna -> mascara bool``.
    Lo usa el backend de la Etapa 2 para dibujar que muestras se descartaron.
    """
    df = df.copy()
    rangos = cfg["limpieza"]["rangos"]
    marcados = 0
    mascaras: dict[str, np.ndarray] = {}
    for col in canales_fisicos():
        canal = col.split("_")[:-1] if col.endswith(tuple(f"_{w}" for w in RUEDAS)) else None
        if canal is not None:
            canal = "_".join(canal)
        else:
            canal = col
        if canal not in rangos:
            continue
        lo, hi = rangos[canal]
        x = df[col].to_numpy(dtype=float)
        fuera = (x < lo) | (x > hi)
        marcados += int(np.sum(fuera))
        if diagnostico is not None:
            mascaras[col] = fuera.copy()
        if fuera.any():
            x = x.copy()
            x[fuera] = np.nan
            df[col] = x
    if diagnostico is not None:
        diagnostico["mascara_fuera_rango"] = mascaras
    return df, {"fuera_de_rango": marcados}


def detectar_outliers(
    df: pd.DataFrame, cfg: dict, fs: float, diagnostico: dict | None = None
) -> tuple[pd.DataFrame, dict]:
    """Detecta outliers con mediana/MAD en ventana causal.

    Para no confundir cambios de nivel (recta <-> curva) con outliers, el
    umbral local tiene un piso: una fraccion de la dispersion robusta global
    del canal. Asi, en tramos quietos (MAD ~ 0) no se marca todo.

    Si se pasa ``diagnostico`` (dict) se guarda en
    ``diagnostico["mascara_outliers"]`` un dict ``columna -> mascara bool``.
    """
    df = df.copy()
    li = cfg["limpieza"]
    win = max(5, int(round(li["outlier_ventana_s"] * fs)))
    umbral = float(li["outlier_mad_umbral"])
    min_p = max(3, win // 4)
    piso = float(li.get("outlier_piso_sigma", 0.2))
    marcados = 0
    mascaras: dict[str, np.ndarray] = {}
    for col in canales_fisicos():
        s = df[col]
        x = s.to_numpy(dtype=float)
        finito = np.isfinite(x)
        if finito.sum() < 10:
            continue
        centro_global = np.median(x[finito])
        sigma = 1.4826 * np.median(np.abs(x[finito] - centro_global))
        if not np.isfinite(sigma) or sigma <= 0:
            continue

        med = s.rolling(win, min_periods=min_p).median()
        mad = (s - med).abs().rolling(win, min_periods=min_p).median()
        escala = np.maximum(1.4826 * mad, piso * sigma)
        fuera = ((s - med).abs() > umbral * escala) & med.notna()
        marcados += int(fuera.sum())
        if diagnostico is not None:
            mascaras[col] = fuera.to_numpy().copy()
        if fuera.any():
            x = x.copy()
            x[fuera.to_numpy()] = np.nan
            df[col] = x
    if diagnostico is not None:
        diagnostico["mascara_outliers"] = mascaras
    return df, {"outliers": marcados}


def interpolar_huecos(df: pd.DataFrame, cfg: dict, fs: float) -> tuple[pd.DataFrame, dict]:
    li = cfg["limpieza"]
    max_m = max(1, int(round(li["hueco_max_s"] * fs)))
    # Solo las senales del esquema definen la validez. Las columnas extra de las
    # capturas en vivo (``packetId``, ``grip_*``, ``degradacion``) son metadatos
    # etiquetados y a menudo vacios: si se incluyeran, invalidarian todas las
    # muestras y el CSV crudo del logger no seria reprocesable en batch (A1/C).
    del_esquema = set(columnas_esquema())
    columnas = [
        c for c in df.columns if c in del_esquema and c not in ("timestamp_s", "lap")
    ]
    rellenados = 0
    partes = []
    for _, sub in df.groupby("lap", sort=True):
        sub = sub.copy()
        for c in columnas:
            antes = int(sub[c].isna().sum())
            if antes:
                sub[c] = sub[c].interpolate(
                    method="linear", limit=max_m, limit_area="inside"
                )
                rellenados += antes - int(sub[c].isna().sum())
        partes.append(sub)
    out = pd.concat(partes).sort_values("timestamp_s").reset_index(drop=True)

    restantes = int(out[columnas].isna().to_numpy().sum())
    # los huecos largos (y los que tocan el borde de una vuelta) quedan como NaN
    # y se marcan como invalidos; no se rellenan nunca.
    out["valido"] = ~out[columnas].isna().any(axis=1)

    return out, {
        "huecos_cortos_rellenados": rellenados,
        "huecos_largos_marcados": restantes,
    }


def filtrar(df: pd.DataFrame, cfg: dict, fs: float) -> tuple[pd.DataFrame, dict]:
    """Aplica Butterworth pasa-bajas causal (SOS) y guarda el estado final."""
    f = cfg["limpieza"]["filtro"]
    corte = float(f["corte_hz"])
    if corte >= fs / 2.0:
        raise ValueError(
            f"Frecuencia de corte {corte} Hz >= Nyquist {fs / 2.0} Hz"
        )
    sos = butter(int(f["orden"]), corte / (fs / 2.0), btype="low", output="sos")

    df = df.copy()
    estado = {}
    for col in canales_filtrables():
        x = df[col].to_numpy(dtype=float)
        zi = sosfilt_zi(sos) * x[0]
        y, zf = sosfilt(sos, x, zi=zi)
        df[col] = y
        estado[col] = zf
    return df, estado


def preprocesar(
    df_raw: pd.DataFrame, cfg: dict, intermedios: dict | None = None
) -> tuple[pd.DataFrame, dict, dict]:
    """Pipeline de limpieza completo. Devuelve (senal_limpia, registro, estado).

    Si se pasa ``intermedios`` (un dict), se guarda ahi la senal remuestreada
    antes de filtrar, util para las figuras del reporte.
    """
    validar_esquema(df_raw)
    fs = float(cfg["fs"])

    fs_origen = df_raw.attrs.get("fs_origen")
    df = resamplear(df_raw, fs, fs_origen=fs_origen)
    if intermedios is not None:
        intermedios["resampleado"] = df.copy()

    registro = {}
    df, r = marcar_fuera_de_rango(df, cfg, diagnostico=intermedios)
    registro.update(r)
    df, r = detectar_outliers(df, cfg, fs, diagnostico=intermedios)
    registro.update(r)
    df, r = interpolar_huecos(df, cfg, fs)
    registro.update(r)

    # El filtro no admite NaN: se rellena solo para filtrar y luego se
    # restauran los NaN en las muestras marcadas como invalidas.
    columnas = [c for c in df.columns if c not in ("timestamp_s", "lap", "valido")]
    invalido = ~df["valido"].to_numpy()
    para_filtrar = df.copy()
    for c in columnas:
        if para_filtrar[c].isna().any():
            para_filtrar[c] = para_filtrar[c].interpolate(limit_direction="both")

    para_filtrar, estado = filtrar(para_filtrar, cfg, fs)
    for c in columnas:
        if invalido.any():
            para_filtrar.loc[invalido, c] = np.nan
    df = para_filtrar

    registro["valido"] = int(df["valido"].sum())
    return df, registro, estado
