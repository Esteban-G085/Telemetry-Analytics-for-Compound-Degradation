"""Motor de análisis en vivo y logger CSV (Etapa 3).

:class:`MotorVivo` consume el :class:`~sim.fuentes.BusTiempoReal` y calcula, sin
mirar al futuro, la **degradación agregada** desde el ``grip`` de AC (máximo
observado) o desde la columna ``degradacion`` inyectada en modo seco, además de
features, predicción agregada con Kalman y el espectro de Welch de la ventana.

:class:`LoggerVivo` escribe el CSV **crudo** (antes del acondicionador, para
reprocesarlo en batch) con el esquema del proyecto y las columnas extra
``packetId``, ``grip_*`` y ``degradacion``.

🐴: se quitaron el Kalman por rueda, la calibración P95 del pico, la detección
de cambio de neumáticos y el ``_verdad.csv``: con una sola serie agregada basta
para el estado y el osciloscopio de la GUI.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch

from telemetria.pipeline import features
from telemetria.pipeline.config import RUEDAS, columnas_esquema
from telemetria.pipeline.modelo import KalmanDegradacion

from telemetria.adquisicion.fuentes import BusTiempoReal, columnas_de


def _rellenar_huecos(x: np.ndarray) -> np.ndarray | None:
    """Recorta extremos NaN e interpola los huecos internos (B9)."""
    finitos = np.isfinite(x)
    if finitos.all():
        return x
    if not finitos.any():
        return None
    i0 = int(np.argmax(finitos))
    i1 = x.size - 1 - int(np.argmax(finitos[::-1]))
    tramo = x[i0 : i1 + 1]
    t = np.arange(tramo.size, dtype=float)
    f = np.isfinite(tramo)
    return np.interp(t, t[f], tramo[f])


class MotorVivo:
    def __init__(self, cfg: dict, bus: BusTiempoReal, *, fuente: str = "ac"):
        self.cfg = cfg
        self.bus = bus
        self.fuente = fuente
        v = cfg.get("vivo", {})
        self.W = int(round(float(v.get("ventana_s", cfg["ventana_s"])) * float(cfg["fs"])))
        self.anticipacion = int(v.get("anticipacion_vueltas", 3))
        self.nperseg = int(cfg["features"]["welch_nperseg"])

        self._lock = threading.Lock()
        self.n = 0
        self.ultimo: dict | None = None
        self.pico = 0.0
        self.deg_actual: dict[str, float] = {w: float("nan") for w in RUEDAS}
        self._modo = "none"
        self.lap: int | None = None
        self._por_vuelta: dict[int, float] = {}
        self._suma = 0.0
        self._cuenta = 0
        bus.suscribir(self._on_muestra)

    # --- consumo ---
    def _on_muestra(self, m: dict) -> None:
        with self._lock:
            self.n += 1
            self.ultimo = m
            lap = m.get("lap")
            lap = int(lap) if lap is not None else None
            if lap is not None and self.lap is not None and lap != self.lap:
                if lap < self.lap:
                    # Nueva sesión/stint: se limpia la historia (neumáticos nuevos).
                    self._por_vuelta = {}
                    self._suma = 0.0
                    self._cuenta = 0
                else:
                    self._cerrar_vuelta(self.lap)
            self.lap = lap
            self._actualizar_degradacion(m)

    def _actualizar_degradacion(self, m: dict) -> None:
        # ``grip = 0.0`` y NaN son centinelas de "sin señal" (modo seco/tests):
        # solo habilita la rama de grip un valor finito y positivo.
        grips = {w: _num(m.get(f"grip_{w}")) for w in RUEDAS}
        validos = [g for g in grips.values() if g is not None and g > 0]
        if validos:
            self._modo = "verdad"
            self.pico = max(self.pico, max(validos))
            for w in RUEDAS:
                g = grips[w]
                self.deg_actual[w] = (
                    float(np.clip((self.pico - g) / self.pico, 0.0, 1.0))
                    if g is not None and g > 0
                    else float("nan")
                )
        else:
            d = _num(m.get("degradacion"))
            self._modo = "verdad" if d is not None else "none"
            valor = d if d is not None else float("nan")
            for w in RUEDAS:
                self.deg_actual[w] = valor

        media = float(np.mean([v for v in self.deg_actual.values() if v == v])) if any(
            v == v for v in self.deg_actual.values()
        ) else None
        if media is not None:
            self._suma += media
            self._cuenta += 1

    def _cerrar_vuelta(self, lap: int) -> None:
        if self._cuenta > 0:
            self._por_vuelta[int(lap)] = self._suma / self._cuenta
        self._suma = 0.0
        self._cuenta = 0

    # --- estado ---
    def estado(self) -> dict:
        with self._lock:
            ultimo = dict(self.ultimo) if self.ultimo else None
            deg = dict(self.deg_actual)
            modo = self._modo
            lap = self.lap
            n = self.n

        degradacion = {w: _num(deg[w]) for w in RUEDAS}
        validos = [v for v in degradacion.values() if v is not None]
        media = float(np.mean(validos)) if validos else None
        ventana = self.bus.ultimas(self.W)

        return {
            "activo": n > 0,
            "fuente": self.fuente,
            "t": None if ultimo is None else round(float(ultimo.get("timestamp_s", 0.0)), 3),
            "n": n,
            "lap": lap,
            "packetId": None if ultimo is None else ultimo.get("packetId"),
            "grip": {w: _num(ultimo.get(f"grip_{w}")) if ultimo else None for w in RUEDAS},
            "degradacion": degradacion,
            "degradacion_media": None if media is None else round(media, 4),
            "degradacion_modo": modo,
            "prediccion": self._predecir(),
            "features": self._features(ventana),
            "espectro": self._espectro(ventana),
            "canales": self._canales(),
        }

    def ventana(self, n: int | None = None, canales: list[str] | None = None) -> dict:
        muestras = self.bus.ultimas(n or self.W)
        cols = canales or [c for c in ("speed_kmh",) if self._hay(c)]
        cols = [c for c in cols if self._hay(c)]
        return {
            "t": [round(float(m.get("timestamp_s", 0.0)), 3) for m in muestras],
            "series": {c: [_num(m.get(c)) for m in muestras] for c in cols},
            "lap": [m.get("lap") for m in muestras],
            "n": len(muestras),
        }

    # --- cálculos ---
    def _hay(self, col: str) -> bool:
        with self._lock:
            return bool(self.ultimo and col in self.ultimo)

    def _canales(self) -> list[str]:
        with self._lock:
            muestras = self.bus.ultimas(1)
        return columnas_de(muestras)

    def _features(self, ventana: list[dict]) -> dict | None:
        if len(ventana) < self.W:
            return None
        cols = columnas_esquema()
        if not all(c in ventana[0] for c in cols):
            return None
        df = pd.DataFrame(ventana)
        if len(np.unique(df["lap"].to_numpy())) != 1:
            return None
        datos = df[cols].to_numpy(dtype=float)
        if not np.isfinite(datos).all():
            return None
        try:
            f = features.features_ventana(df[cols], self.cfg)
        except Exception:  # noqa: BLE001 - ventana degenerada
            return None
        return {k: _num(v) for k, v in f.items()}

    def _espectro(self, ventana: list[dict]) -> dict | None:
        canal = "wheel_slip_fl"
        if len(ventana) < max(16, self.nperseg):
            return None
        x = _rellenar_huecos(
            np.array([m.get(canal, np.nan) for m in ventana], dtype=float)
        )
        if x is None or x.size < 16:
            return None
        nps = int(min(self.nperseg, x.size))
        freqs, psd = welch(x, fs=float(self.cfg["fs"]), nperseg=nps, noverlap=nps // 2)
        return {
            "canal": canal,
            "freqs": [round(float(f), 4) for f in freqs],
            "psd_db": [round(float(10.0 * np.log10(max(v, 1e-20))), 3) for v in psd],
        }

    def _predecir(self) -> dict:
        with self._lock:
            serie = dict(self._por_vuelta)
        laps = sorted(serie)
        obs = [serie[l] for l in laps]
        salida = {
            "laps_obs": laps,
            "obs": [round(float(v), 4) for v in obs],
            "media": [],
            "banda_inf": [],
            "banda_sup": [],
            "laps_pred": [],
        }
        if len(obs) < 2:
            return salida
        kc = self.cfg["modelo"]["kalman"]
        kal = KalmanDegradacion(
            float(kc["q_nivel"]), float(kc["q_pendiente"]), float(kc["r"]),
            monotono=bool(kc.get("monotono", True)),
        )
        res = kal.filtrar(obs)
        medias, var = kal.predecir(res, self.anticipacion)
        z = float(self.cfg["evaluacion"]["z"])
        desv = np.sqrt(np.maximum(var, 0.0))
        salida["laps_pred"] = [laps[-1] + i + 1 for i in range(self.anticipacion)]
        salida["media"] = [round(float(v), 4) for v in medias]
        salida["banda_inf"] = [round(float(v - z * d), 4) for v, d in zip(medias, desv)]
        salida["banda_sup"] = [round(float(v + z * d), 4) for v, d in zip(medias, desv)]
        return salida


class LoggerVivo:
    """Escribe el CSV **crudo** con el esquema del proyecto y los extras de A5.

    El logger se suscribe a la fuente **antes** del acondicionador
    (``Fuente.suscribir_crudo``): reprocesar datos ya filtrados aplicaría un
    segundo filtro y una segunda detección de outliers (D7).
    """

    COLUMNAS_EXTRA = ("packetId", "grip_fl", "grip_fr", "grip_rl", "grip_rr", "degradacion")

    def __init__(self, dir_salida: str | Path, nombre: str):
        self.dir = Path(dir_salida)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.nombre = nombre
        self.ruta = self.dir / f"{nombre}.csv"
        self.columnas = columnas_esquema() + list(self.COLUMNAS_EXTRA)
        self._lock = threading.Lock()
        # Apertura perezosa: una fuente que nunca arranca no deja CSV vacío.
        self._fh = None
        self._w = None
        self._cerrado = False
        self.n = 0

    def registrar(self, m: dict) -> None:
        with self._lock:
            if self._cerrado or not all(c in m for c in columnas_esquema()):
                return
            if self._fh is None:
                self._fh = open(self.ruta, "w", newline="", encoding="utf-8")
                self._w = csv.writer(self._fh)
                self._w.writerow(self.columnas)
            self._w.writerow([_csv(m.get(c)) for c in self.columnas])
            self.n += 1
            if self.n % 100 == 0:
                self._fh.flush()

    def cerrar(self) -> None:
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True
            if self._fh is not None:
                try:
                    self._fh.flush()
                    self._fh.close()
                except Exception:  # noqa: BLE001
                    pass
                self._fh = None


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, 4)


def _csv(v):
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return "" if not np.isfinite(f) else f
