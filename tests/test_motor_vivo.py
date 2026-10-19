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
    """``grip = 0.0`` es centinela de "sin senal": manda la columna inyectada."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    for i in range(200):
        bus.publicar(_muestra(i, lap=1, grip=0.0, degradacion=min(1.0, i / 200.0)))
    estado = motor.estado()
    assert estado["degradacion_modo"] == "verdad"
    assert estado["degradacion"]["rr"] == estado["degradacion"]["fl"]
    assert estado["degradacion"]["fl"] is not None
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
    assert estado["degradacion"]["fl"] is not None
    assert estado["degradacion"]["fl"] > 0.9


def test_pico_ignora_espurio_aislado(cfg):
    """Un pico espurio (una muestra) no fija el pico: lo corrige el P95."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="ac")
    i = 0
    for lap in range(1, 7):  # 6 vueltas -> se cierran 5 y se calibra
        for k in range(200):
            grip = 0.99
            if lap == 2 and k == 50:
                grip = 0.9999  # espurio de una sola muestra
            bus.publicar(_muestra(i, lap=lap, grip=grip))
            i += 1
    assert motor._calibrando_pico is False
    # el pico es P95 (~0.99), no el espurio 0.9999
    assert motor.pico["fl"] < 0.995


def test_reinicio_pico_por_cambio_neumaticos(cfg):
    """Si el grip vuelve a subir (neumaticos nuevos), se recalibra el pico."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="ac")
    i = 0
    for lap in range(1, 7):  # set 1: grip ~1.0, se calibra el pico
        for _ in range(200):
            bus.publicar(_muestra(i, lap=lap, grip=1.0))
            i += 1
    assert motor._calibrando_pico is False
    assert abs(motor.pico["fl"] - 1.0) < 1e-6
    # desgaste del set 1 (mismo lap: no cierra vuelta)
    for _ in range(200):
        bus.publicar(_muestra(i, lap=7, grip=0.85))
        i += 1
    assert motor.deg_actual["fl"] > 0.1
    # cambio de neumaticos: el grip salta a ~1.0 otra vez
    for _ in range(100):
        bus.publicar(_muestra(i, lap=7, grip=1.0))
        i += 1
    assert motor._calibrando_pico is True
    # con el set nuevo (provisional) la degradacion vuelve a ~0
    assert motor.deg_actual["fl"] < 0.05


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
    assert list(crudo.columns) == columnas_esquema() + list(LoggerVivo.COLUMNAS_EXTRA)
    assert len(crudo) == 10
    verdad = pd.read_csv(logger.ruta_verdad)
    assert list(verdad.columns) == ["timestamp_s", "lap", "degradacion"]


def test_logger_guarda_grip_y_degradacion(tmp_path):
    logger = LoggerVivo(tmp_path, "captura")
    for i in range(5):
        logger.registrar(_muestra(i, lap=1, grip=0.95 - i * 0.001))
    logger.cerrar()
    crudo = pd.read_csv(logger.ruta)
    assert crudo["grip_fl"].notna().all()
    assert crudo["degradacion"].isna().all()  # sin etiqueta -> vacio, no archivo verdad
    assert not logger.ruta_verdad.exists()


def test_logger_registrar_degradacion_verdad_ac(tmp_path):
    logger = LoggerVivo(tmp_path, "ac")
    for i in range(5):
        logger.registrar(_muestra(i, lap=1, grip=0.95))
    logger.registrar_degradacion(1.23, 1, 0.05)
    logger.cerrar()
    verdad = pd.read_csv(logger.ruta_verdad)
    assert len(verdad) == 1
    assert verdad["degradacion"].iloc[0] == 0.05


def test_logger_sin_verdad_no_deja_archivo(tmp_path):
    logger = LoggerVivo(tmp_path, "sin_verdad")
    for i in range(5):
        logger.registrar(_muestra(i, lap=1, grip=0.99))
    logger.cerrar()
    assert logger.ruta.exists()
    assert not logger.ruta_verdad.exists()


def test_logger_crea_archivo_al_primer_registro(tmp_path):
    """El CSV no existe hasta el primer registro: una fuente que no arranca
    no deja un archivo con solo la cabecera (B6)."""
    logger = LoggerVivo(tmp_path, "perezoso")
    assert not logger.ruta.exists()
    logger.registrar(_muestra(0, lap=1, grip=0.95))
    assert logger.ruta.exists()
    logger.cerrar()


def test_logger_ignora_escritura_tras_cerrar(tmp_path):
    """Escribir despues de cerrar no lanza: escritura tardia de un hilo (B11)."""
    logger = LoggerVivo(tmp_path, "tardia")
    logger.registrar(_muestra(0, lap=1, grip=0.95))
    logger.cerrar()
    n = logger.n
    logger.registrar(_muestra(1, lap=1, grip=0.95))  # no debe lanzar ni crecer
    logger.registrar_degradacion(1.0, 1, 0.1)
    assert logger.n == n


# --- Bloque 3: prediccion, espectro y reinicio de stint --------------------
def test_filtro_incremental_equivale_a_filtrar(cfg):
    """El Kalman incremental del motor reproduce el filtrado completo (B5)."""
    from telemetria.adquisicion.motor_vivo import _FiltroKalmanVivo
    from telemetria.pipeline.modelo import KalmanDegradacion

    obs = [0.05, 0.11, 0.14, 0.20, 0.27, 0.31]
    kc = cfg["modelo"]["kalman"]
    kal = KalmanDegradacion(
        float(kc["q_nivel"]), float(kc["q_pendiente"]), float(kc["r"]), monotono=True
    )
    res = kal.filtrar(obs)
    filtro = _FiltroKalmanVivo(cfg)
    for o in obs:
        filtro.agregar(o)
    x, P, _ = filtro.estado_actual()
    assert np.allclose(x, res["x"])
    assert np.allclose(P, res["P"])
    m1, v1 = kal.predecir(res, 3)
    m2, v2 = filtro.kal.predecir({"x": x, "P": P}, 3)
    assert np.allclose(m1, m2) and np.allclose(v1, v2)


def test_prediccion_por_rueda_no_enmascara(cfg):
    """Una rueda que se degrada mas se ve en su propia prediccion (B4)."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="ac")
    i = 0
    for lap in range(1, 7):
        for _ in range(1000):
            m = _muestra(i, lap=lap, grip=1.0)
            m["grip_fl"] = 1.0 - 0.02 * lap  # se degrada poco
            m["grip_rr"] = 1.0 - 0.06 * lap  # se degrada mucho mas
            bus.publicar(m)
            i += 1
    pred = motor.estado()["prediccion"]
    assert "por_rueda" in pred
    assert set(pred["por_rueda"]) == set(RUEDAS)
    fl = pred["por_rueda"]["fl"]["media"][-1]
    rr = pred["por_rueda"]["rr"]["media"][-1]
    assert rr > fl  # la rueda que mas sufre no queda enmascarada por la media


def test_reinicio_stint_al_retroceder_vuelta(cfg):
    """Si la vuelta retrocede (nueva sesion) se limpia la historia (B10)."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    for lap in (1, 2, 3, 4):
        for _ in range(300):
            bus.publicar(_muestra(0, lap=lap, grip=0.0, degradacion=0.1 * lap))
    assert motor._por_vuelta  # hay historia acumulada
    assert motor._filtro.n > 0
    # reinicio de sesion: la vuelta vuelve a 1
    bus.publicar(_muestra(0, lap=1, grip=0.0, degradacion=0.0))
    assert motor._por_vuelta == {}
    assert motor._filtro.n == 0
    assert motor._calibrando_pico is True


def test_espectro_interpola_huecos(cfg):
    """El Welch en vivo no debe concatenar muestras separadas por NaN (B9)."""
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
    """Con la ventana de 2 s las features en vivo dejan de ser None (D1)."""
    bus = BusTiempoReal(max_muestras=100000)
    motor = MotorVivo(cfg, bus, fuente="seco")
    assert motor.W == 200
    for i in range(motor.W):
        bus.publicar(_muestra(i, lap=1, grip=0.0, degradacion=0.0))
    assert motor.estado()["features"] is not None
