"""Metadatos reales de la resolución de Welch (Fase 1, §4.2)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.signal import welch

from telemetria.api.servicios import analisis

CANAL = "wheel_slip_fl"
FS = 100.0


def _sesion(n_limpio: int, n_crudo: int | None = None):
    def datos(n: int) -> pd.DataFrame:
        t = np.arange(n, dtype=float) / FS
        return pd.DataFrame({"lap": np.ones(n, dtype=int), CANAL: np.sin(2 * np.pi * 3 * t)})

    cfg = {
        "features": {
            "welch_nperseg": 128,
            "bandas_hz": {"baja": [0.5, 5.0], "media": [5.0, 15.0], "alta": [15.0, 40.0]},
        },
        "limpieza": {"filtro": {"corte_hz": 20.0}},
    }
    return SimpleNamespace(
        fs=FS,
        cfg=cfg,
        limpio=datos(n_limpio),
        crudo=None if n_crudo is None else datos(n_crudo),
    )


def test_espectro_informa_ventana_efectiva_cuando_es_menor():
    sesion = _sesion(40)
    resultado = analisis.espectro(sesion, CANAL)
    assert resultado["nperseg_solicitado"] == 128
    assert resultado["nperseg"] == 40
    assert resultado["n_muestras_limpio"] == 40
    assert resultado["delta_f"] == round(FS / 40, 4)

    x = sesion.limpio[CANAL].to_numpy(dtype=float)
    freqs, psd = welch(x, fs=FS, nperseg=40, noverlap=20)
    np.testing.assert_allclose(resultado["freqs"], freqs, atol=1e-9)
    np.testing.assert_allclose(
        resultado["psd_limpio_db"], 10 * np.log10(np.maximum(psd, 1e-20)), atol=1e-6
    )


def test_espectro_diferencia_resolucion_cruda_y_filtrada():
    resultado = analisis.espectro(_sesion(40, 200), CANAL)
    assert resultado["nperseg"] == 40
    assert resultado["delta_f"] == round(FS / 40, 4)
    assert resultado["nperseg_crudo"] == 128
    assert resultado["delta_f_crudo"] == round(FS / 128, 4)
    assert len(resultado["freqs"]) == 21
    assert len(resultado["freqs_crudo"]) == 65
    assert len(resultado["freqs_crudo"]) == len(resultado["psd_crudo_db"])


def test_espectro_sin_crudo_valido_no_inventa_frecuencias():
    resultado = analisis.espectro(_sesion(40, 5), CANAL)
    assert resultado["psd_crudo_db"] is None
    assert resultado["freqs_crudo"] is None
    assert resultado["nperseg_crudo"] is None
    assert resultado["delta_f_crudo"] is None


def test_espectro_muestras_insuficientes():
    with pytest.raises(ValueError, match="Muestras insuficientes"):
        analisis.espectro(_sesion(5), CANAL)
