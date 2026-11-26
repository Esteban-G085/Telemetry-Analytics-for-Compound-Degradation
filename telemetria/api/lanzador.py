"""Arranque del backend local para la GUI de escritorio.

La ventana nativa (PySide6) se abre en `telemetria.gui.main`; aquí solo se levanta
uvicorn en un hilo daemon y se espera a que `/health` responda.

🐴: se quitó el lanzador de navegador: la GUI nativa es la única interfaz.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request


def esperar_servidor(url: str, timeout_s: float = 40.0, paso_s: float = 0.2) -> bool:
    limite = time.perf_counter() + timeout_s
    while time.perf_counter() < limite:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(paso_s)
    return False


def arrancar_servidor(host: str, puerto: int):
    """Devuelve el hilo del servidor uvicorn (daemon)."""
    import uvicorn

    from telemetria.api.app import crear_app

    config = uvicorn.Config(crear_app(), host=host, port=puerto, log_level="warning")
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, name="uvicorn", daemon=True)
    hilo.start()
    return hilo
