"""Adaptador del pipeline de la Etapa 1 para el backend.

Procesa un CSV (o DataFrame) en memoria y guarda todo lo que el dashboard
necesita: senal limpia, senal cruda remuestreada, registro de calidad,
etiquetas (proxy/verdad), features por ventana y las mascaras de outliers.

No hace I/O de disco innecesario: `telemetria.pipeline` trabaja sobre DataFrames ya cargados.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from telemetria.pipeline import etiquetas, features, limpieza, modelo
from telemetria.pipeline.config import columnas_esquema


@dataclass
class Sesion:
    """Sesion procesada (una por CSV cargado)."""

    id: str
    nombre: str
    ruta: str | None
    fs: float
    cfg: dict
    limpio: pd.DataFrame
    crudo: pd.DataFrame | None
    registro: dict
    proxy: pd.DataFrame
    verdad: pd.DataFrame | None  # por vuelta: lap, degradacion
    verdad_muestra: pd.DataFrame | None  # por muestra (solo F1)
    feats: pd.DataFrame  # features por ventana
    y_ventana: np.ndarray  # etiqueta de cada ventana
    mascara_outliers: dict = field(default_factory=dict)
    mascara_fuera_rango: dict = field(default_factory=dict)

    @property
    def laps(self) -> list[int]:
        return [int(v) for v in np.unique(self.limpio["lap"].to_numpy())]

    def vueltas_meta(self) -> list[dict]:
        """Metadatos por vuelta (duracion, muestras, combustible medio)."""
        tab = etiquetas.tiempos_por_vuelta(self.limpio, fs=self.fs)
        return [
            {
                "lap": int(r.lap),
                "duracion_s": round(float(r.tiempo_vuelta_s), 3),
                "n_muestras": int(r.n_muestras),
                "combustible_kg": round(float(r.combustible_kg), 3),
            }
            for r in tab.itertuples()
        ]

    def degradacion_vuelta(self) -> pd.Series:
        """Serie indexada por vuelta: verdad si existe, si no el proxy."""
        if self.verdad is not None:
            base = self.verdad
        else:
            base = self.proxy.rename(columns={"degradacion_proxy": "degradacion"})
        return base.set_index("lap")["degradacion"].sort_index()


def _procesar(df_raw: pd.DataFrame, cfg: dict, *, sid: str, nombre: str, ruta: str | None,
              verdad_muestra: pd.DataFrame | None) -> Sesion:
    intermedios: dict = {}
    limpio, registro, _estado = limpieza.preprocesar(df_raw, cfg, intermedios=intermedios)
    crudo = intermedios.get("resampleado")

    fs = float(cfg["fs"])
    feats = features.features_por_ventanas(limpio, cfg)
    proxy = etiquetas.proxy_degradacion(limpio, cfg, fs=fs)

    verdad_vuelta = None
    if verdad_muestra is not None:
        verdad_vuelta = etiquetas.verdad_por_vuelta(verdad_muestra)

    if not feats.empty and verdad_muestra is not None:
        y_ventana = modelo.etiquetas_por_ventana(feats, verdad_muestra, cfg)
    elif not feats.empty:
        mapa = dict(zip(proxy["lap"], proxy["degradacion_proxy"]))
        y_ventana = feats["lap"].map(mapa).to_numpy(dtype=float)
    else:
        y_ventana = np.asarray([], dtype=float)

    return Sesion(
        id=sid,
        nombre=nombre,
        ruta=ruta,
        fs=fs,
        cfg=cfg,
        limpio=limpio,
        crudo=crudo,
        registro=registro,
        proxy=proxy,
        verdad=verdad_vuelta,
        verdad_muestra=verdad_muestra,
        feats=feats,
        y_ventana=y_ventana,
        mascara_outliers=intermedios.get("mascara_outliers", {}),
        mascara_fuera_rango=intermedios.get("mascara_fuera_rango", {}),
    )


def _leer_verdad(ruta_csv: Path) -> pd.DataFrame | None:
    compañera = ruta_csv.with_name(ruta_csv.stem + "_verdad.csv")
    return pd.read_csv(compañera) if compañera.exists() else None


def procesar_csv(ruta: str | Path, cfg: dict) -> Sesion:
    """Carga y procesa un CSV de `data/raw/` (busca `<nombre>_verdad.csv`)."""
    ruta = Path(ruta)
    df_raw = pd.read_csv(ruta)
    return _procesar(
        df_raw, cfg, sid=ruta.stem, nombre=ruta.name, ruta=str(ruta),
        verdad_muestra=_leer_verdad(ruta),
    )


def procesar_contenido(datos: bytes, cfg: dict, nombre: str) -> Sesion:
    """Procesa un CSV subido como bytes (drag & drop / subida)."""
    df_raw = pd.read_csv(io.BytesIO(datos))
    sid = Path(nombre).stem or "subida"
    return _procesar(df_raw, cfg, sid=sid, nombre=nombre, ruta=None, verdad_muestra=None)


def columnas_disponibles(sesion: Sesion) -> list[str]:
    """Columnas numericas que el dashboard puede graficar."""
    cols = [c for c in columnas_esquema() if c in sesion.limpio.columns]
    return cols
