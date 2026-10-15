"""Carga de configuracion y definicion del esquema de datos.

El esquema es el contrato que cualquier fuente (F1-F4) debe cumplir.
Ver plan_etapa1.md, seccion 3.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

RUEDAS = ("fl", "fr", "rl", "rr")

# Canales por rueda (el nombre final es "<canal>_<rueda>").
CANALES_RUEDA = (
    "temp_core_c",
    "pressure_psi",
    "wheel_slip",
    "wheel_load_n",
    "dirty_level",
)

# Columnas comunes a todas las muestras.
COLUMNAS_BASE = (
    "timestamp_s",
    "lap",
    "speed_kmh",
    "throttle",
    "brake",
    "steering",
    "fuel_kg",
)

RUTA_CONFIG_POR_DEFECTO = Path(__file__).resolve().parent.parent / "config.yaml"


def columnas_canal(canal: str) -> list[str]:
    """Columnas de un canal para las cuatro ruedas."""
    return [f"{canal}_{w}" for w in RUEDAS]


def columnas_esquema() -> list[str]:
    """Todas las columnas obligatorias del esquema del proyecto."""
    cols = list(COLUMNAS_BASE)
    for canal in CANALES_RUEDA:
        cols.extend(columnas_canal(canal))
    return cols


def canales_fisicos() -> list[str]:
    """Columnas con interpretacion fisica (para rangos y outliers)."""
    cols = ["speed_kmh"]
    for canal in ("temp_core_c", "pressure_psi", "wheel_slip", "wheel_load_n"):
        cols.extend(columnas_canal(canal))
    return cols


def canales_filtrables() -> list[str]:
    """Columnas que pasan por el filtro pasa-bajas."""
    cols = []
    for canal in CANALES_RUEDA:
        cols.extend(columnas_canal(canal))
    return cols


def fusionar(base: dict, extra: dict) -> dict:
    """Merge recursivo de ``extra`` sobre ``base`` (sin mutar ninguno)."""
    out = copy.deepcopy(base)
    for clave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(out.get(clave), dict):
            out[clave] = fusionar(out[clave], valor)
        else:
            out[clave] = copy.deepcopy(valor)
    return out


def cargar_config(ruta: str | Path | None = None, overrides: dict | None = None) -> dict:
    """Lee config.yaml y aplica overrides anidados (util en tests)."""
    ruta = Path(ruta) if ruta is not None else RUTA_CONFIG_POR_DEFECTO
    with open(ruta, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if overrides:
        cfg = fusionar(cfg, overrides)
    return cfg
