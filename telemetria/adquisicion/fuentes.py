"""Bus en tiempo real y fuentes de datos en vivo (Etapa 3).

Dos fuentes comparten la misma interfaz y alimentan el mismo bus:

  - :class:`FuenteVivo` lee la memoria compartida de AC (F3) y decodifica un
    frame por cada ``packetId`` nuevo.
  - :class:`FuenteCSV` reproduce un CSV del proyecto ("modo seco"), util para
    desarrollar y probar sin abrir el juego y para el test de coherencia
    live-vs-batch (D14).

Ambas pasan la senal por :class:`~sim.acondicionador.AcondicionadorCausal` y
publican muestras decimadas en el :class:`BusTiempoReal`.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from telemetria.adquisicion.ac_info import MemoriaAC
from telemetria.adquisicion.acondicionador import AcondicionadorCausal


class BusTiempoReal:
    """Buffer circular thread-safe de muestras (dicts) con suscriptores."""

    def __init__(self, max_muestras: int = 12000):
        self._buf: deque[dict] = deque(maxlen=int(max_muestras))
        self._lock = threading.Lock()
        self._subs: list = []
        self.total = 0

    def publicar(self, muestra: dict) -> None:
        with self._lock:
            self._buf.append(muestra)
            self.total += 1
            subs = list(self._subs)
        for fn in subs:
            fn(muestra)

    def suscribir(self, fn) -> None:
        with self._lock:
            self._subs.append(fn)

    def ultimas(self, n: int | None = None) -> list[dict]:
        with self._lock:
            if n is None:
                return list(self._buf)
            return list(self._buf)[-int(n):]

    def vaciar(self) -> None:
        with self._lock:
            self._buf.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


def columnas_de(muestras: list[dict]) -> list[str]:
    """Columnas presentes en todas las muestras (en orden de aparicion)."""
    if not muestras:
        return []
    comunes = set(muestras[0])
    for m in muestras[1:]:
        comunes &= set(m)
    return [c for c in muestras[0] if c in comunes]


# --------------------------------------------------------------------------
# Fuente base
# --------------------------------------------------------------------------
class Fuente(threading.Thread):
    """Hilo productor. Las subclases implementan :meth:`_siguiente`."""

    def __init__(self, bus: BusTiempoReal, cfg: dict, nombre: str):
        super().__init__(daemon=True, name=nombre)
        self.bus = bus
        self.cfg = cfg
        self._detener = threading.Event()
        self._terminado = False
        self.acondicionador: AcondicionadorCausal | None = None
        self.errores: list[str] = []
        self.n_leidos = 0
        self.n_publicados = 0

    # --- API ---
    def detener(self) -> None:
        self._detener.set()

    @property
    def detenida(self) -> bool:
        return self._detener.is_set() or self._terminado

    # --- ganchos ---
    def _preparar(self) -> None:
        raise NotImplementedError

    def _siguiente(self) -> dict | None:
        raise NotImplementedError

    def _crear_acondicionador(self, fs_entrada: float) -> AcondicionadorCausal:
        v = self.cfg.get("vivo", {})
        return AcondicionadorCausal(
            fs_entrada=fs_entrada,
            fs_salida=float(v.get("fs_salida", self.cfg["fs"])),
            corte_hz=float(self.cfg["limpieza"]["filtro"]["corte_hz"]),
            orden=int(self.cfg["limpieza"]["filtro"]["orden"]),
            ventana_outlier_s=float(self.cfg["limpieza"]["outlier_ventana_s"]),
            mad_umbral=float(self.cfg["limpieza"]["outlier_mad_umbral"]),
        )

    def _emitir(self, fila: dict) -> None:
        self.n_leidos += 1
        if self.acondicionador is None:
            self.bus.publicar(fila)
            self.n_publicados += 1
            return
        salida = self.acondicionador.procesar(fila)
        if salida is not None:
            self.bus.publicar(salida)
            self.n_publicados += 1

    def run(self) -> None:  # noqa: D102
        try:
            self._preparar()
        except Exception as exc:  # noqa: BLE001 - se informa por `errores`
            self.errores.append(str(exc))
            self._terminado = True
            return
        try:
            while not self._detener.is_set():
                fila = self._siguiente()
                if fila is None:
                    if self._terminado:
                        break
                    continue
                self._emitir(fila)
        except Exception as exc:  # noqa: BLE001
            self.errores.append(str(exc))
        finally:
            self._terminado = True


# --------------------------------------------------------------------------
# Fuente AC (F3)
# --------------------------------------------------------------------------
class FuenteVivo(Fuente):
    """Lee ``acpmf_physics``/``acpmf_graphics`` de Assetto Corsa."""

    def __init__(self, bus: BusTiempoReal, cfg: dict, memoria: MemoriaAC | None = None):
        super().__init__(bus, cfg, nombre="fuente-ac")
        self.memoria = memoria or MemoriaAC(prefijo=str(cfg.get("vivo", {}).get("radio_memoria", "Local\\")))
        self._ultimo_packet = -1
        self._t0 = 0.0

    def _preparar(self) -> None:
        self.memoria.abrir()
        if not self.memoria.disponible:
            raise RuntimeError(self.memoria.error or "memoria de AC no disponible")
        v = self.cfg.get("vivo", {})
        fs_entrada = float(v.get("fs_entrada", self.cfg["sim"]["fs_original"]))
        self.acondicionador = self._crear_acondicionador(fs_entrada)
        self._t0 = time.perf_counter()
        self._ultimo_packet = self.memoria.packet_id

    def _siguiente(self) -> dict | None:
        if self.memoria is None or self.memoria.fisica is None:
            self._terminado = True
            return None
        pid = self.memoria.esperar_packet(self._ultimo_packet, timeout_s=0.1)
        if pid == self._ultimo_packet:
            return None
        self._ultimo_packet = pid
        ciclo = time.perf_counter() - self._t0
        return self.memoria.leer_muestra(ciclo=ciclo)

    def contexto(self) -> dict:
        return self.memoria.contexto()

    def detener(self) -> None:  # noqa: D102
        super().detener()
        self.memoria.cerrar()


# --------------------------------------------------------------------------
# Fuente CSV ("modo seco")
# --------------------------------------------------------------------------
class FuenteCSV(Fuente):
    """Reproduce un CSV del proyecto a ritmo real (o a maxima velocidad).

    Si existe ``<nombre>_verdad.csv`` al lado, inyecta la columna extra
    ``degradacion`` interpolada al timestamp de cada muestra (modo demo).
    """

    def __init__(
        self,
        ruta: str | Path,
        bus: BusTiempoReal,
        cfg: dict,
        *,
        ritmo_hz: float | None = None,
        bucle: bool = False,
    ):
        super().__init__(bus, cfg, nombre="fuente-csv")
        self.ruta = Path(ruta)
        self.ritmo_hz = ritmo_hz  # None -> tiempo real (fs_salida)
        self.bucle = bool(bucle)
        self.df: pd.DataFrame | None = None
        self._registros: list[dict] = []
        self._i = 0
        self._t0_wall = 0.0
        self._t0_csv = 0.0

    def _preparar(self) -> None:
        if not self.ruta.exists():
            raise FileNotFoundError(f"CSV no encontrado: {self.ruta}")
        self.df = pd.read_csv(self.ruta)
        n = len(self.df)
        if n < 2:
            raise ValueError("El CSV no tiene suficientes muestras")
        t = self.df["timestamp_s"].to_numpy(dtype=float)
        dt = float(np.median(np.diff(t)))
        fs_entrada = 1.0 / dt if dt > 0 else float(self.cfg["fs"])
        self.acondicionador = self._crear_acondicionador(fs_entrada)

        verdad = self.ruta.with_name(self.ruta.stem + "_verdad.csv")
        if verdad.exists():
            v = pd.read_csv(verdad)
            if {"timestamp_s", "degradacion"} <= set(v.columns):
                self.df["degradacion"] = np.interp(
                    t, v["timestamp_s"].to_numpy(dtype=float), v["degradacion"].to_numpy(dtype=float)
                )

        if self.ritmo_hz is None:
            self.ritmo_hz = float(self.cfg.get("vivo", {}).get("fs_salida", self.cfg["fs"]))
        self._t0_wall = time.perf_counter()
        self._t0_csv = float(t[0])
        # Iterar registros (dicts) es mucho mas rapido que `df.iloc[i]` por fila.
        self._registros = self.df.to_dict("records")

    def _siguiente(self) -> dict | None:
        if self._i >= len(self._registros):
            if self.bucle:
                self._i = 0
                self._t0_wall = time.perf_counter()
            else:
                self._terminado = True
                return None
        fila = self._registros[self._i]
        self._i += 1

        if self.ritmo_hz and self.ritmo_hz > 0:
            objetivo = self._t0_wall + (float(fila["timestamp_s"]) - self._t0_csv)
            espera = objetivo - time.perf_counter()
            if espera > 0:
                time.sleep(espera)
        return fila
