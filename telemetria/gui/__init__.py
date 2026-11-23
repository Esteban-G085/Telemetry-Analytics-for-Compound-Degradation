"""Interfaz de escritorio nativa (PySide6) para Telemetry Analytics.

Reemplaza el dashboard del navegador (Vite + uPlot) por una ventana nativa
de escritorio. El backend FastAPI se mantiene igual y esta GUI se conecta a
sus endpoints REST y WebSocket como cualquier otro cliente.

Estructura:
    cliente_api.py   - Cliente REST (httpx) + WebSocket (QWebSocket)
    vista_base.py    - Clase base para todas las pestañas
    vistas/          - Una pestaña por pantalla (sesiones, telemetria, etc.)
    ventana_principal.py - QMainWindow con barra de estado y pestañas
    main.py          - Punto de entrada: arranca backend + ventana
"""
