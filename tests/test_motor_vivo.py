"""Tests del motor de análisis en vivo y del logger CSV (Etapa 3)."""

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


def test_degradacion_desde_grip(cfg):
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="ac")
    # el pico de grip se alcanza al calentar; luego cae
    for i in range(5000):
        grip = 0.995 + 0.00002 * i if i < 100 else max(0.9, 1.01 - i * 0.00002)
        bus.publicar(_muestra(i, lap=1 + i // 1000, grip=grip))
    estado = motor.estado()
    assert estado["degradacion_modo"] == "verdad"
    assert 0.0 < estado["degradacion"]["fl"] <= 1.0
    assert 0.0 < estado["degradacion_media"] <= 1.0


def test_degradacion_desde_columna_inyectada(cfg):
    """``grip = 0.0`` es centinela de "sin senal": manda la columna inyectada."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    for i in range(200):
        bus.publicar(_muestra(i, lap=1, grip=0.0, degradacion=min(1.0, i / 200.0)))
    estado = motor.estado()
    assert estado["degradacion_modo"] == "verdad"
    assert estado["degradacion"]["rr"] == estado["degradacion"]["fl"]
    assert estado["degradacion"]["fl"] > 0.9


def test_grip_nan_cae_a_columna_inyectada(cfg):
    """Grip NaN no habilita la rama de grip: se usa la columna ``degradacion``."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    for i in range(200):
        bus.publicar(
            _muestra(i, lap=1, grip=float("nan"), degradacion=min(1.0, i / 200.0))
        )
    estado = motor.estado()
    assert estado["degradacion_modo"] == "verdad"
    assert estado["degradacion"]["fl"] > 0.9


def test_prediccion_tras_varias_vueltas(cfg):
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    i = 0
    for lap in range(1, 7):
        for _ in range(1000):
            bus.publicar(_muestra(i, lap=lap, grip=0.0, degradacion=0.05 * lap))
            i += 1
    pred = motor.estado()["prediccion"]
    assert len(pred["laps_pred"]) == cfg["vivo"]["anticipacion_vueltas"]
    assert len(pred["media"]) == len(pred["laps_pred"])
    assert pred["media"][-1] >= pred["media"][0]


def test_estado_sin_datos(cfg):
    bus = BusTiempoReal()
    motor = MotorVivo(cfg, bus)
    estado = motor.estado()
    assert estado["activo"] is False
    assert estado["n"] == 0
    assert estado["prediccion"]["media"] == []


def test_logger_escribe_esquema(tmp_path):
    logger = LoggerVivo(tmp_path, "captura")
    for i in range(10):
        logger.registrar(_muestra(i, lap=1, grip=0.99, degradacion=0.01 * i))
    logger.cerrar()
    crudo = pd.read_csv(logger.ruta)
    assert list(crudo.columns) == columnas_esquema() + list(LoggerVivo.COLUMNAS_EXTRA)
    assert len(crudo) == 10


def test_logger_guarda_grip_y_degradacion(tmp_path):
    logger = LoggerVivo(tmp_path, "captura")
    for i in range(5):
        logger.registrar(_muestra(i, lap=1, grip=0.95 - i * 0.001))
    logger.cerrar()
    crudo = pd.read_csv(logger.ruta)
    assert crudo["grip_fl"].notna().all()
    assert crudo["degradacion"].isna().all()  # sin etiqueta -> vacio


def test_logger_crea_archivo_al_primer_registro(tmp_path):
    """El CSV no existe hasta el primer registro: una fuente que no arranca
    no deja un archivo con solo la cabecera."""
    logger = LoggerVivo(tmp_path, "perezoso")
    assert not logger.ruta.exists()
    logger.registrar(_muestra(0, lap=1, grip=0.95))
    assert logger.ruta.exists()
    logger.cerrar()


def test_logger_ignora_escritura_tras_cerrar(tmp_path):
    """Escribir despues de cerrar no lanza: escritura tardia de un hilo."""
    logger = LoggerVivo(tmp_path, "tardia")
    logger.registrar(_muestra(0, lap=1, grip=0.95))
    logger.cerrar()
    n = logger.n
    logger.registrar(_muestra(1, lap=1, grip=0.95))  # no debe lanzar ni crecer
    assert logger.n == n


def test_reinicio_stint_al_retroceder_vuelta(cfg):
    """Si la vuelta retrocede (nueva sesion) se limpia la historia."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    for lap in (1, 2, 3, 4):
        for _ in range(300):
            bus.publicar(_muestra(0, lap=lap, grip=0.0, degradacion=0.1 * lap))
    assert motor._por_vuelta  # hay historia acumulada
    bus.publicar(_muestra(0, lap=1, grip=0.0, degradacion=0.0))
    assert motor._por_vuelta == {}
    assert motor._cuenta == 1  # la muestra nueva ya abre el acumulador


def test_espectro_interpola_huecos(cfg):
    """El Welch en vivo no debe concatenar muestras separadas por NaN."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    ventana = []
    for i in range(200):
        m = _muestra(i, lap=1, grip=0.0, degradacion=0.0)
        if 50 <= i < 60:
            m["wheel_slip_fl"] = float("nan")  # hueco interno
        ventana.append(m)
    esp = motor._espectro(ventana)
    assert esp is not None
    assert all(np.isfinite(v) for v in esp["psd_db"])


def test_features_no_vacias_con_ventana_2s(cfg):
    """Con la ventana de 2 s las features en vivo dejan de ser None."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    assert motor.W == 200
    for i in range(motor.W):
        bus.publicar(_muestra(i, lap=1, grip=0.0, degradacion=0.0))
    assert motor.estado()["features"] is not None
