"""Punto de entrada unico de Telemetry Analytics.

Uso:
    python -m telemetria                       # abre la GUI de escritorio (PySide6)
    python -m telemetria gui                   # igual que arriba (interfaz nativa)
    python -m telemetria pipeline              # pipeline offline de la Etapa 1
    python -m telemetria pipeline --entrada data/raw/sim_42.csv

Si se omite el subcomando se asume `gui`, de modo que `python -m telemetria`
abre la interfaz de escritorio nativa (equivale a `python -m telemetria gui`).

🐴: se quitó el subcomando `app` (lanzador de navegador): solo existe la GUI nativa.
"""

from __future__ import annotations

import sys

COMANDOS = ("gui", "pipeline")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] in COMANDOS:
        comando, resto = argv[0], argv[1:]
    else:
        comando, resto = "gui", argv

    if comando == "gui":
        from telemetria.gui.main import main as gui_main

        return gui_main(resto)

    from telemetria.pipeline.orquestador import main as pipeline_main

    pipeline_main(resto)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
