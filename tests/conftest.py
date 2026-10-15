"""Fixtures comunes."""

import pytest

from src.config import cargar_config

# Configuracion pequena para que los tests corran rapido.
OVERRIDES = {
    "fs": 100.0,
    "sim": {
        "vueltas": 6,
        "fs_original": 200.0,
        "jitter_s": 0.0005,
    },
}


@pytest.fixture
def cfg():
    return cargar_config(overrides=OVERRIDES)


@pytest.fixture
def base_cfg():
    return cargar_config()
