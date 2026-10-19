"""Sesion en vivo (Etapa 3): orquesta fuente + bus + motor + logger.

Un unico objeto vive en ``app.state.vivo``. Arranca un hilo (fuente AC o CSV),
publica muestras decimadas en el bus, calcula el estado en vivo y deja un CSV
reprocesable en ``data/vivo/``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from telemetria.adquisicion.fuentes import BusTiempoReal, FuenteCSV, FuenteVivo
from telemetria.adquisicion.motor_vivo import LoggerVivo, MotorVivo

from telemetria.api.servicios.cache_memoria import RAIZ, CacheMemoria

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
        # Resolver el archivo ANTES de tocar la sesion en curso (B6): un CSV
        # invalido no debe detener la captura que ya estaba corriendo.
        ruta = self._resolver_archivo(archivo) if fuente == "seco" else None
        with self._lock:
            cfg = self.config()
            v = cfg.get("vivo", {})
            bus = BusTiempoReal(int(v.get("max_muestras", 12000)))
            motor = MotorVivo(cfg, bus, fuente=fuente)
            if fuente == "seco":
                nueva = FuenteCSV(ruta, bus, cfg, ritmo_hz=ritmo_hz, bucle=bucle)
                base = ruta.stem
            else:
                nueva = FuenteVivo(bus, cfg)
                base = "ac"

            nombre = f"{base}_{time.strftime('%Y%m%d_%H%M%S')}"
            logger = LoggerVivo(self.dir_vivo, nombre)
            # CSV crudo: se suscribe a la fuente antes del acondicionador (A1/D7).
            nueva.suscribir_crudo(logger.registrar)
            if fuente == "ac":
                # En AC la verdad se deriva del grip en el motor (A5).
                motor.logger = logger

            # Recien ahora se detiene la sesion anterior y se publica la nueva.
            self._detener_sin_lock()
            self.bus = bus
            self.motor = motor
            self.fuente = nueva
            self.logger = logger
            self.fuente_nombre = fuente
            self.archivo = archivo
            self.ruta_csv = str(logger.ruta)
            self.iniciada_en = time.time()
            self.error = None

            nueva.start()
            # No responder "activo" antes de confirmar que la fuente arranco (B6).
            if not nueva.esperar_arranque(timeout=5.0):
                err = nueva.errores[-1] if nueva.errores else "la fuente no arranco"
                self._detener_sin_lock()
                self.fuente_nombre = fuente
                self.archivo = archivo
                self.error = err
                raise RuntimeError(err)
        return self.estado()

    def detener(self) -> dict:
        with self._lock:
            self._detener_sin_lock()
        return self.estado()

    def _detener_sin_lock(self) -> None:
        if self.fuente is not None:
            try:
                self.fuente.detener()
                self.fuente.join(timeout=2.0)
                # Si el hilo sigue vivo no se fuerza el cierre del archivo:
                # `LoggerVivo.registrar` ignora escrituras tras `cerrar` (B11),
                # asi que cerrarlo es seguro aunque tarde un poco mas.
                if self.fuente.is_alive():
                    self.fuente.join(timeout=2.0)
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
            return {
                "activo": False,
                "fuente": None,
                "n": 0,
                "degradacion_modo": "none",
                "paquetes_perdidos": 0,
                "errores_subs": 0,
            }
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
        # Diagnostico de captura (B2/B3): frames salteados y fallos de suscriptores.
        estado["paquetes_perdidos"] = int(getattr(self.fuente, "paquetes_perdidos", 0) or 0)
        estado["fs_medida"] = getattr(self.fuente, "fs_medida", None)
        estado["errores_subs"] = int(getattr(self.bus, "errores_subs", 0) or 0) + int(
            getattr(self.fuente, "errores_subs_crudos", 0) or 0
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
