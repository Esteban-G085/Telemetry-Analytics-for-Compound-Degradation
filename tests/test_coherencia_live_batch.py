"""Coherencia entre el pipeline en vivo y el batch (Etapa 3, D14).

Reproduce un CSV crudo por la ruta en vivo (outliers causales + filtro causal +
decimacion) y compara la senal con `limpieza.preprocesar`. No se exige igualdad
exacta: el batch remuestrea con `resample_poly` (FIR de fase lineal, cuyo retardo
de grupo no compensa) y otra inicializacion del filtro. Se espera correlacion muy
alta y un error pequeno frente a la dispersion de la senal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetria.adquisicion import generador
from telemetria.adquisicion.fuentes import BusTiempoReal, FuenteCSV
from telemetria.pipeline import limpieza
from telemetria.pipeline.config import cargar_config

# Descartamos el primer segundo (transitorio del filtro con estado inicial 0).
DESCARTE_S = 1.0
CANALES = ("speed_kmh", "wheel_slip_fl", "temp_core_c_fl", "wheel_load_n_fl")


@pytest.fixture(scope="module")
def cfg_live():
    # Pocas vueltas: el objetivo es la coherencia, no el realismo del stint.
    return cargar_config(
        overrides={"fs": 100.0, "sim": {"vueltas": 3, "fs_original": 200.0, "jitter_s": 0.0005}}
    )


def _reproducir(cfg, df, tmp_path):
    ruta = tmp_path / "sim_coherencia.csv"
    df.to_csv(ruta, index=False)
    bus = BusTiempoReal(max_muestras=2_000_000)
    fuente = FuenteCSV(ruta, bus, cfg, ritmo_hz=0)
    fuente.start()
    fuente.join(timeout=120)
    assert not fuente.errores, fuente.errores
    vivo = pd.DataFrame(bus.ultimas())
    assert len(vivo) > 0
    return vivo


def test_coherencia_senal_live_vs_batch(cfg_live, tmp_path):
    df, _verdad = generador.generar_dataframe(cfg_live, semilla=11)
    vivo = _reproducir(cfg_live, df, tmp_path)
    limpio, _registro, _estado = limpieza.preprocesar(df, cfg_live)

    t_batch = limpio["timestamp_s"].to_numpy(dtype=float)
    t_vivo = vivo["timestamp_s"].to_numpy(dtype=float)

    for canal in CANALES:
        y_vivo = np.interp(t_batch, t_vivo, vivo[canal].to_numpy(dtype=float))
        y_batch = limpio[canal].to_numpy(dtype=float)
        util = (t_batch > t_batch[0] + DESCARTE_S) & np.isfinite(y_vivo) & np.isfinite(y_batch)
        assert util.sum() > 100, canal

        a, b = y_vivo[util], y_batch[util]
        corr = float(np.corrcoef(a, b)[0, 1])
        rmse = float(np.sqrt(np.mean((a - b) ** 2)))
        rel = rmse / (float(np.std(b)) + 1e-9)

        assert corr > 0.97, f"{canal}: corr={corr:.3f}"
        assert rel < 0.2, f"{canal}: rmse_rel={rel:.3f}"


def test_coherencia_por_vuelta(cfg_live, tmp_path):
    """El promedio por vuelta de la senal en vivo sigue al del batch."""
    df, _verdad = generador.generar_dataframe(cfg_live, semilla=11)
    vivo = _reproducir(cfg_live, df, tmp_path)
    limpio, _registro, _estado = limpieza.preprocesar(df, cfg_live)

    t_batch = limpio["timestamp_s"].to_numpy(dtype=float)
    lap_batch = limpio["lap"].to_numpy()
    vivo = vivo.assign(lap=np.interp(vivo["timestamp_s"], t_batch, lap_batch).round())

    mb = limpio.groupby("lap")["speed_kmh"].mean()
    mv = vivo.groupby("lap")["speed_kmh"].mean()
    comunes = sorted(set(mb.index) & set(mv.index))
    assert len(comunes) >= 3
    a = mb.loc[comunes].to_numpy()
    b = mv.loc[comunes].to_numpy()
    assert float(np.corrcoef(a, b)[0, 1]) > 0.9
    assert float(np.mean(np.abs(a - b))) < 3.0  # km/h


def test_captura_cruda_reprocesable_en_batch(cfg_live, tmp_path):
    """El CSV crudo del logger se reprocesa en batch sin doble filtrado (A1/C).

    Es el test que faltaba del logger -> batch: confirma que la captura cruda
    (antes del acondicionador) atraviesa `limpieza.preprocesar` y produce
    senal limpia, que es lo que permite volver a analizar una sesion grabada.
    """
    from telemetria.adquisicion.motor_vivo import LoggerVivo

    df, _verdad = generador.generar_dataframe(cfg_live, semilla=5)
    df = df.iloc[:10000].reset_index(drop=True)
    ruta = tmp_path / "sim.csv"
    df.to_csv(ruta, index=False)

    bus = BusTiempoReal(max_muestras=2_000_000)
    logger = LoggerVivo(tmp_path / "vivo", "captura")
    fuente = FuenteCSV(ruta, bus, cfg_live, ritmo_hz=0)
    fuente.suscribir_crudo(logger.registrar)  # fila cruda, antes del acondicionador
    fuente.start()
    assert fuente.esperar_arranque(5.0)
    fuente.join(timeout=120)
    assert not fuente.errores, fuente.errores
    logger.cerrar()

    crudo = pd.read_csv(logger.ruta)
    assert len(crudo) > 0
    assert "grip_fl" in crudo.columns  # columnas extra del logger (A5)
    # D4: la captura es cruda (no paso por el acondicionador). Si se hubiera
    # grabado la senal filtrada, el batch aplicaria un segundo filtro.
    assert len(crudo) == len(df)
    assert np.allclose(crudo["speed_kmh"].to_numpy(), df["speed_kmh"].to_numpy(), atol=1e-9)
    limpio, _registro, _estado = limpieza.preprocesar(crudo, cfg_live)
    assert len(limpio) > 0
    assert limpio["speed_kmh"].notna().sum() > 0
