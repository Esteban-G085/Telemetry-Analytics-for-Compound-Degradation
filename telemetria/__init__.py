"""Telemetry Analytics para Assetto Corsa (Etapas 1-3).

Un unico paquete reune las tres partes del proyecto:

- `telemetria.pipeline`: ciencia de datos offline de la Etapa 1 (limpieza,
  features, etiquetas, Ridge/Kalman, evaluacion y reporte).
- `telemetria.adquisicion`: generacion simulada y captura en vivo desde la
  memoria compartida de AC (Etapa 3).
- `telemetria.api`: backend FastAPI (REST + WebSocket) que sirve el dashboard
  (Etapas 2 y 3).

El punto de entrada esta en :mod:`telemetria.cli`, ejecutable con
`python -m telemetria`.
"""

__version__ = "2.0.0"
