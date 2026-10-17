"""Aplicacion local (Etapa 3).

Levanta el backend FastAPI/uvicorn en un hilo y abre la interfaz en el navegador
por defecto. Opcionalmente arranca la captura en vivo nada mas abrir.

Uso:
    python desktop.py                       # abre la app (sin captura)
    python desktop.py --modo seco           # arranca el modo seco con el CSV demo
    python desktop.py --modo ac             # arranca la captura desde AC
    python desktop.py --sin-navegador       # solo el servidor (diagnostico)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


# --------------------------------------------------------------------------
# Servidor
# --------------------------------------------------------------------------
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

    from backend.app import crear_app

    config = uvicorn.Config(crear_app(), host=host, port=puerto, log_level="warning")
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, name="uvicorn", daemon=True)
    hilo.start()
    return hilo


def pedir_json(url: str, cuerpo: dict | None = None) -> dict | None:
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    peticion = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}, method="GET" if datos is None else "POST"
    )
    try:
        with urllib.request.urlopen(peticion, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# Navegador
# --------------------------------------------------------------------------
def abrir_navegador(url: str) -> None:
    webbrowser.open(url)
    print(f"Servidor en {url}. Pulsa Ctrl+C para salir.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Telemetry Analytics (Etapa 3)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--modo", choices=["ac", "seco"], default=None, help="arranca la captura al abrir")
    parser.add_argument("--archivo", default="sim_test_99.csv", help="CSV para --modo seco")
    parser.add_argument("--ritmo-max", action="store_true", help="modo seco a maxima velocidad")
    parser.add_argument("--sin-navegador", action="store_true", help="solo el servidor (diagnostico)")
    args = parser.parse_args(argv)

    base = f"http://{args.host}:{args.puerto}"
    arrancar_servidor(args.host, args.puerto)

    if not esperar_servidor(f"{base}/health"):
        print("El servidor no respondio a tiempo.", file=sys.stderr)
        return 1
    print(f"Backend listo en {base}")

    if args.modo:
        cuerpo = {"fuente": args.modo, "archivo": args.archivo if args.modo == "seco" else None}
        if args.modo == "seco" and args.ritmo_max:
            cuerpo["ritmo_hz"] = 0
        resultado = pedir_json(f"{base}/api/vivo/iniciar", cuerpo)
        if resultado and resultado.get("error"):
            print(f"Aviso de captura: {resultado['error']}")
        else:
            print(f"Captura iniciada (modo {args.modo}).")

    if args.sin_navegador:
        print("Modo --sin-navegador: Ctrl+C para salir.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            return 0

    abrir_navegador(base)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
