@echo off
rem Arranca la app local (Etapa 3). Doble clic o: ejecutar_app.bat --modo seco
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m telemetria app %*
) else (
  python -m telemetria app %*
)
