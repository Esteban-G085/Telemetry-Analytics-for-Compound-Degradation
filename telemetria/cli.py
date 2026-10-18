"""Punto de entrada unico de Telemetry Analytics.

Uso:
    python -m telemetria                       # abre la app local (navegador)
    python -m telemetria app --modo seco       # arranca la captura en seco
    python -m telemetria app --modo ac         # captura desde Assetto Corsa
    python -m telemetria app --sin-navegador   # solo el servidor (diagnostico)
    python -m telemetria pipeline              # pipeline offline de la Etapa 1
    python -m telemetria pipeline --entrada data/raw/sim_42.csv

Si se omite el subcomando se asume `app`, de modo que `python -m telemetria`
abre la interfaz local (equivale a `python -m telemetria app`).
"""

from __future__ import annotations

import sys

COMANDOS = ("app", "pipeline")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] in COMANDOS:
        comando, resto = argv[0], argv[1:]
    else:
        comando, resto = "app", argv

    if comando == "pipeline":
        from telemetria.pipeline.orquestador import main as pipeline_main

        pipeline_main(resto)
        return 0

    from telemetria.api.lanzador import main as app_main

    return app_main(resto)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
