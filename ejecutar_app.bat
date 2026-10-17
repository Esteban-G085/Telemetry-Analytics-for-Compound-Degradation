@echo off
rem Arranca la app de escritorio (Etapa 3). Doble clic o: ejecutar_app.bat --modo seco
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" desktop.py %*
) else (
  python desktop.py %*
)
