"""Tests del acondicionador causal en vivo (Etapa 3, D4)."""

from __future__ import annotations

import numpy as np

from telemetria.adquisicion.acondicionador import AcondicionadorCausal


def _decimar(ac: AcondicionadorCausal, x: np.ndarray) -> list[float]:
    salida = []
    for v in x:
        fila = ac.procesar({"x": float(v)})
        if fila is not None:
            salida.append(fila["x"])
    return salida


def test_decimacion_a_frecuencia_objetivo():
    fs_in, fs_out = 333.0, 100.0
    ac = AcondicionadorCausal(fs_in, fs_out, 20.0, canales=("x",))
    n = 3330
    x = np.zeros(n)
    y = _decimar(ac, x)
    esperado = n * fs_out / fs_in
    assert abs(len(y) - esperado) <= 5


def test_filtro_atenua_alta_frecuencia():
    fs_in, fs_out = 333.0, 100.0
    rng = np.random.default_rng(0)
    t = np.arange(3330) / fs_in
    limpio = np.sin(2 * np.pi * 2.0 * t)
    ruido = limpio + rng.normal(0.0, 0.3, t.size)
    ac = AcondicionadorCausal(fs_in, fs_out, 20.0, canales=("x",))
    y = np.array(_decimar(ac, ruido))
    # la señal filtrada sigue la componente lenta y tiene menos "rugosidad"
    assert np.std(np.diff(y)) < np.std(np.diff(ruido))
    assert abs(float(np.mean(y))) < 0.3


def test_outlier_se_marca_y_no_contamina():
    ac = AcondicionadorCausal(
        100.0, 100.0, 20.0, canales=("x",), ventana_outlier_s=0.5, mad_umbral=6.0
    )
    rng = np.random.default_rng(1)
    x = rng.normal(0.0, 0.01, 500)
    x[400] = 50.0  # pico absurdo
    salida = _decimar(ac, x)
    assert len(salida) == 500
    assert np.isnan(salida[400])  # marcado como no valido
    # el pico no arrastro la señal: la cola queda contenida
    assert np.nanmax(np.abs(salida[401:])) < 1.0


def test_huecos_nan_se_propagan():
    ac = AcondicionadorCausal(100.0, 100.0, 20.0, canales=("x",))
    salida = _decimar(ac, np.array([0.0, 1.0, np.nan, np.nan, 1.0, 0.0]))
    assert np.isnan(salida[2])
    assert np.isnan(salida[3])


def test_corte_invalido_lanza():
    import pytest

    with pytest.raises(ValueError):
        AcondicionadorCausal(100.0, 100.0, 60.0)  # 60 >= Nyquist 50
