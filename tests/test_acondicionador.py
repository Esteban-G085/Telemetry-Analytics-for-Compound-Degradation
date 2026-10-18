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


def test_piso_sigma_evita_marcar_cambios_reales_de_nivel():
    """Sin el piso, un tramo casi plano colapsa el MAD local y marca como outlier
    el cambio de nivel real (huecos falsos en el osciloscopio). El piso (fraccion
    de la dispersion global), igual que en el batch, lo evita pero conserva los
    picos absurdos.
    """
    fs = 100.0
    rng = np.random.default_rng(4)
    n = 3000
    x = np.empty(n)
    # Tramo con variabilidad realista: fija la dispersion global del canal.
    x[:1500] = 0.05 * np.sin(2 * np.pi * 1.0 * np.arange(1500) / fs)
    # "Recta": plano con micro-ruido y, despues, un cambio de nivel real.
    x[1500:2000] = 0.07 + rng.normal(0.0, 1e-5, 500)
    x[2000:] = 0.05 + rng.normal(0.0, 1e-5, 1000)
    x[2500] = 5.0  # pico realmente absurdo

    base = dict(ventana_outlier_s=0.5, mad_umbral=12.0)
    ac_sin = AcondicionadorCausal(fs, fs, 20.0, canales=("x",), piso_sigma=0.0, **base)
    ac_con = AcondicionadorCausal(fs, fs, 20.0, canales=("x",), piso_sigma=0.5, **base)
    y_sin = np.array(_decimar(ac_sin, x))
    y_con = np.array(_decimar(ac_con, x))

    # Sin piso: el cambio de nivel se marca como si fuera un pico (racha de NaN).
    assert np.isnan(y_sin[2000:2030]).sum() > 5
    # Con piso: el cambio de nivel ya no se marca...
    assert np.isnan(y_con[2000:2030]).sum() == 0
    # ...pero el pico absurdo si se sigue detectando.
    assert np.isnan(y_con[2500])


def test_huecos_nan_se_propagan():
    ac = AcondicionadorCausal(100.0, 100.0, 20.0, canales=("x",))
    salida = _decimar(ac, np.array([0.0, 1.0, np.nan, np.nan, 1.0, 0.0]))
    assert np.isnan(salida[2])
    assert np.isnan(salida[3])


def test_corte_invalido_lanza():
    import pytest

    with pytest.raises(ValueError):
        AcondicionadorCausal(100.0, 100.0, 60.0)  # 60 >= Nyquist 50
