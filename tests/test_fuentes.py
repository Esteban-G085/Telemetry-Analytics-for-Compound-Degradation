"""Tests de las fuentes en vivo: bus y reproduccion CSV ('modo seco')."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sim.fuentes import BusTiempoReal, FuenteCSV, columnas_de


def _csv_en(tmp_path, n=1000, fs=333.0, lap_por=250):
    t = np.arange(n) / fs
    df = pd.DataFrame(
        {
            "timestamp_s": t,
            "lap": (np.arange(n) // lap_por) + 1,
            "speed_kmh": 100.0 + 20.0 * np.sin(2 * np.pi * 0.5 * t),
            "throttle": 0.5,
            "brake": 0.0,
            "steering": 0.0,
            "fuel_kg": 50.0,
        }
    )
    for w in ("fl", "fr", "rl", "rr"):
        df[f"temp_core_c_{w}"] = 90.0
        df[f"pressure_psi_{w}"] = 25.0
        df[f"wheel_slip_{w}"] = 0.1 * np.sin(2 * np.pi * 3 * t)
        df[f"wheel_load_n_{w}"] = 4000.0
        df[f"dirty_level_{w}"] = 0.0
    ruta = tmp_path / "seco.csv"
    df.to_csv(ruta, index=False)
    return ruta


def test_bus_circular_y_columnas():
    bus = BusTiempoReal(max_muestras=3)
    for i in range(5):
        bus.publicar({"a": i, "b": i * 2})
    assert len(bus) == 3
    assert [m["a"] for m in bus.ultimas()] == [2, 3, 4]
    assert columnas_de(bus.ultimas()) == ["a", "b"]


def test_fuente_csv_decima_y_publica(tmp_path, cfg):
    ruta = _csv_en(tmp_path)
    bus = BusTiempoReal(max_muestras=100000)
    fuente = FuenteCSV(ruta, bus, cfg, ritmo_hz=0)
    fuente.start()
    fuente.join(timeout=30)
    assert not fuente.errores, fuente.errores
    salida = bus.ultimas()
    # fs_original 333 -> fs_salida 100
    assert abs(len(salida) - 1000 * 100 / 333.0) <= 5
    # el esquema completo viaja en cada muestra
    from src.config import columnas_esquema

    assert all(c in salida[0] for c in columnas_esquema())


def test_fuente_csv_inyecta_verdad(tmp_path, cfg):
    ruta = _csv_en(tmp_path)
    verdad = pd.DataFrame(
        {"timestamp_s": [0.0, 3.0], "lap": [1, 4], "degradacion": [0.0, 1.0]}
    )
    verdad.to_csv(ruta.with_name(ruta.stem + "_verdad.csv"), index=False)
    bus = BusTiempoReal(max_muestras=100000)
    fuente = FuenteCSV(ruta, bus, cfg, ritmo_hz=0)
    fuente.start()
    fuente.join(timeout=30)
    salida = bus.ultimas()
    assert "degradacion" in salida[0]
    assert salida[-1]["degradacion"] > salida[0]["degradacion"]


def test_fuente_csv_archivo_inexistente(tmp_path, cfg):
    bus = BusTiempoReal()
    fuente = FuenteCSV(tmp_path / "no_existe.csv", bus, cfg, ritmo_hz=0)
    fuente.start()
    fuente.join(timeout=10)
    assert fuente.errores
