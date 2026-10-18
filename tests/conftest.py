"""Fixtures comunes."""

import pytest

from telemetria.pipeline.config import cargar_config

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


# --- Fixtures del backend (Etapa 2) -----------------------------------------
# Se construyen aqui para que las reutilicen los tests de API rest/ws.
@pytest.fixture(scope="module")
def datos_demo(tmp_path_factory):
    """Genera un CSV pequeno (6 vueltas) con su verdad en una carpeta temporal."""
    from telemetria.adquisicion import generador

    cfg = cargar_config(overrides=OVERRIDES)
    dir_raw = tmp_path_factory.mktemp("raw")
    df, verdad = generador.generar_dataframe(cfg, semilla=7)
    df.to_csv(dir_raw / "demo.csv", index=False)
    verdad.to_csv(dir_raw / "demo_verdad.csv", index=False)
    return dir_raw


@pytest.fixture(scope="module")
def cliente(datos_demo):
    """TestClient de FastAPI con la sesion de demo ya cargada."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from telemetria.api.app import crear_app

    app = crear_app(dir_raw=datos_demo, overrides=OVERRIDES)
    with TestClient(app) as c:
        respuesta = c.post("/api/sesiones/cargar", json={"nombre": "demo.csv"})
        assert respuesta.status_code == 200, respuesta.text
        yield c
