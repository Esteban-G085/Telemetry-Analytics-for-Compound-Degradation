@echo off
rem Arranca la app de escritorio (PySide6). Doble clic para abrir la ventana nativa.
rem Opciones: ejecutar_app.bat gui | app | pipeline
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m telemetria %*
) else (
  python -m telemetria %*
)
