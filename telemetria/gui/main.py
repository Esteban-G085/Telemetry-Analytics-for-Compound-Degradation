"""Punto de entrada de la interfaz de escritorio (PySide6).

Arranca el backend FastAPI/uvicorn en un hilo daemon, espera a que responda
en /health y lanza la ventana nativa. El frontend del navegador ya no es
necesario para usar la aplicacion.

Uso:
    python -m telemetria gui
    # o directamente:
    python telemetria/gui/main.py
"""

from __future__ import annotations

import sys

from telemetria.api.lanzador import arrancar_servidor, esperar_servidor
from telemetria.gui.ventana_principal import VentanaPrincipal

HOST = "127.0.0.1"
PUERTO = 8000


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # 1. Levanta el backend en un hilo daemon (mismo proceso).
    arrancar_servidor(HOST, PUERTO)

    base = f"http://{HOST}:{PUERTO}"
    if not esperar_servidor(f"{base}/health", timeout_s=40.0):
        print(f"El backend no respondio en {base}", file=sys.stderr)
        return 1

    print(f"Backend listo en {base}")

    # 2. Lanza la ventana nativa.
    ventana = VentanaPrincipal()
    ventana.show()

    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
