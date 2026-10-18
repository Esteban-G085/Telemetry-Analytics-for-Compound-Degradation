"""Tests del motor de analisis en vivo y del logger CSV (Etapa 3)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from telemetria.adquisicion.fuentes import BusTiempoReal
from telemetria.adquisicion.motor_vivo import LoggerVivo, MotorVivo
from telemetria.pipeline.config import columnas_esquema

RUEDAS = ("fl", "fr", "rl", "rr")


def _muestra(i, lap, grip, degradacion=None):
    m = {
        "timestamp_s": i / 100.0,
        "lap": lap,
        "speed_kmh": 120.0,
        "throttle": 0.4,
        "brake": 0.0,
        "steering": 0.05,
        "fuel_kg": 40.0 - 0.001 * i,
    }
    for w in RUEDAS:
        m[f"temp_core_c_{w}"] = 95.0
        m[f"pressure_psi_{w}"] = 26.0
        m[f"wheel_slip_{w}"] = 0.2
        m[f"wheel_load_n_{w}"] = 4200.0
        m[f"dirty_level_{w}"] = 0.0
        m[f"grip_{w}"] = grip
    if degradacion is not None:
        m["degradacion"] = degradacion
    return m


def test_degradacion_desde_grip_autocalibrado(cfg):
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="ac")
    # el pico de grip se alcanza al calentar; luego cae
    for i in range(5000):
        grip = 0.995 + 0.00002 * i if i < 100 else max(0.9, 1.01 - i * 0.00002)
        bus.publicar(_muestra(i, lap=1 + i // 1000, grip=grip))
    estado = motor.estado()
    assert estado["degradacion_modo"] == "verdad"
    # al final el grip bajo: degradacion > 0
    assert estado["degradacion"]["fl"] > 0.0
    assert 0.0 <= estado["degradacion"]["fl"] <= 1.0


def test_degradacion_desde_columna_inyectada(cfg):
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    for i in range(200):
        bus.publicar(_muestra(i, lap=1, grip=0.0, degradacion=min(1.0, i / 200.0)))
    estado = motor.estado()
    assert estado["degradacion_modo"] == "verdad"
    assert estado["degradacion"]["rr"] == estado["degradacion"]["fl"]


def test_prediccion_tras_varias_vueltas(cfg):
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    # 6 vueltas con degradacion creciente
    i = 0
    for lap in range(1, 7):
        for _ in range(1000):
            bus.publicar(_muestra(i, lap=lap, grip=0.0, degradacion=0.05 * lap))
            i += 1
    estado = motor.estado()
    pred = estado["prediccion"]
    assert pred is not None
    assert len(pred["laps_pred"]) == cfg["vivo"]["anticipacion_vueltas"]
    assert len(pred["media"]) == len(pred["laps_pred"])
    # la prediccion debe continuar la tendencia creciente
    assert pred["media"][-1] >= pred["media"][0]


def test_estado_sin_datos(cfg):
    bus = BusTiempoReal()
    motor = MotorVivo(cfg, bus)
    estado = motor.estado()
    assert estado["activo"] is False
    assert estado["n"] == 0
    assert estado["prediccion"] is None or estado["prediccion"]["media"] == []


def test_logger_escribe_esquema_y_verdad(tmp_path):
    logger = LoggerVivo(tmp_path, "captura")
    for i in range(10):
        logger.registrar(_muestra(i, lap=1, grip=0.99, degradacion=0.01 * i))
    logger.cerrar()
    crudo = pd.read_csv(logger.ruta)
    assert list(crudo.columns) == columnas_esquema()
    assert len(crudo) == 10
    verdad = pd.read_csv(logger.ruta_verdad)
    assert list(verdad.columns) == ["timestamp_s", "lap", "degradacion"]


def test_logger_sin_verdad_no_deja_archivo(tmp_path):
    logger = LoggerVivo(tmp_path, "sin_verdad")
    for i in range(5):
        logger.registrar(_muestra(i, lap=1, grip=0.99))
    logger.cerrar()
    assert logger.ruta.exists()
    assert not logger.ruta_verdad.exists()
