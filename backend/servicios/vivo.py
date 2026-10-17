"""Sesion en vivo (Etapa 3): orquesta fuente + bus + motor + logger.

Un unico objeto vive en ``app.state.vivo``. Arranca un hilo (fuente AC o CSV),
publica muestras decimadas en el bus, calcula el estado en vivo y deja un CSV
reprocesable en ``data/vivo/``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from sim.fuentes import BusTiempoReal, FuenteCSV, FuenteVivo
from sim.motor_vivo import LoggerVivo, MotorVivo

from backend.servicios.cache_memoria import RAIZ, CacheMemoria

FUENTES = ("ac", "seco")


class VivoSesion:
    def __init__(self, cache: CacheMemoria, dir_vivo: str | Path | None = None):
        self.cache = cache
        self.dir_vivo = Path(dir_vivo) if dir_vivo is not None else RAIZ / "data" / "vivo"
        self._lock = threading.Lock()
        self.bus: BusTiempoReal | None = None
        self.fuente = None
        self.motor: MotorVivo | None = None
        self.logger: LoggerVivo | None = None
        self.ruta_csv: str | None = None
        self.fuente_nombre: str | None = None
        self.archivo: str | None = None
        self.iniciada_en: float | None = None
        self.error: str | None = None

    # --- estado ---
    @property
    def activo(self) -> bool:
        return self.fuente is not None and self.fuente.is_alive()

    def config(self) -> dict:
        return self.cache.config()

    # --- control ---
    def iniciar(
        self,
        fuente: str = "ac",
        archivo: str | None = None,
        ritmo_hz: float | None = None,
        bucle: bool = False,
    ) -> dict:
        fuente = (fuente or "ac").lower()
        if fuente not in FUENTES:
            raise ValueError(f"fuente desconocida: {fuente} (usa {FUENTES})")
        with self._lock:
            self._detener_sin_lock()
            cfg = self.config()
            v = cfg.get("vivo", {})
            self.bus = BusTiempoReal(int(v.get("max_muestras", 12000)))
            self.fuente_nombre = fuente
            self.archivo = archivo
            self.error = None

            if fuente == "seco":
                ruta = self._resolver_archivo(archivo)
                self.motor = MotorVivo(cfg, self.bus, fuente="seco")
                self.fuente = FuenteCSV(ruta, self.bus, cfg, ritmo_hz=ritmo_hz, bucle=bucle)
                base = ruta.stem
            else:
                self.motor = MotorVivo(cfg, self.bus, fuente="ac")
                self.fuente = FuenteVivo(self.bus, cfg)
                base = "ac"

            nombre = f"{base}_{time.strftime('%Y%m%d_%H%M%S')}"
            self.logger = LoggerVivo(self.dir_vivo, nombre)
            self.bus.suscribir(self.logger.registrar)
            self.ruta_csv = str(self.logger.ruta)
            self.iniciada_en = time.time()
            self.fuente.start()
        # deja arrancar el hilo para poder reportar un error temprano
        time.sleep(0.05)
        return self.estado()

    def detener(self) -> dict:
        with self._lock:
            self._detener_sin_lock()
        return self.estado()

    def _detener_sin_lock(self) -> None:
        if self.fuente is not None:
            try:
                self.fuente.detener()
                self.fuente.join(timeout=1.5)
            except Exception:  # noqa: BLE001
                pass
        if self.logger is not None:
            self.logger.cerrar()
        self.fuente = None
        self.logger = None
        self.iniciada_en = None

    def _resolver_archivo(self, archivo: str | None) -> Path:
        if not archivo:
            archivo = "sim_test_99.csv"
        p = Path(archivo)
        candidatos = [p] if p.is_absolute() else [
            Path(self.cache.dir_raw) / archivo,
            RAIZ / "data" / "raw" / archivo,
            RAIZ / "data" / "vivo" / archivo,
            RAIZ / archivo,
        ]
        for c in candidatos:
            if c.exists():
                return c.resolve()
        raise FileNotFoundError(f"CSV no encontrado para el modo seco: {archivo}")

    # --- consulta ---
    def estado(self) -> dict:
        if self.motor is None:
            return {"activo": False, "fuente": None, "n": 0, "degradacion_modo": "none"}
        estado = self.motor.estado()
        # `activo` = capturando ahora mismo (el motor lo usa como "hay datos").
        estado["activo"] = self.activo
        errores = list(getattr(self.fuente, "errores", []) or [])
        if errores:
            self.error = errores[-1]
        estado["error"] = self.error
        estado["ruta_csv"] = self.ruta_csv
        estado["segundos"] = (
            round(time.time() - self.iniciada_en, 2) if self.iniciada_en else None
        )
        return estado

    def ventana(self, n: int | None = None, canales: list[str] | None = None) -> dict:
        if self.motor is None:
            return {"t": [], "series": {}, "lap": [], "n": 0}
        return self.motor.ventana(n=n, canales=canales)

    def listar(self) -> list[dict]:
        self.dir_vivo.mkdir(parents=True, exist_ok=True)
        salida = []
        for ruta in sorted(self.dir_vivo.glob("*.csv")):
            if ruta.stem.endswith("_verdad"):
                continue
            verdad = ruta.with_name(ruta.stem + "_verdad.csv")
            salida.append(
                {
                    "nombre": ruta.name,
                    "kb": round(ruta.stat().st_size / 1024.0, 1),
                    "tiene_verdad": verdad.exists(),
                }
            )
        # tambien ofrece los CSV de data/raw como fuente del modo seco
        for ruta in sorted((RAIZ / "data" / "raw").glob("*.csv")):
            if ruta.stem.endswith("_verdad"):
                continue
            salida.append(
                {
                    "nombre": ruta.name,
                    "kb": round(ruta.stat().st_size / 1024.0, 1),
                    "tiene_verdad": ruta.with_name(ruta.stem + "_verdad.csv").exists(),
                    "origen": "raw",
                }
            )
        return salida
