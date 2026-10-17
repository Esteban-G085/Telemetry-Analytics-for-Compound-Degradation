"""Motor de analisis en vivo y logger CSV (Etapa 3).

:class:`MotorVivo` consume el :class:`~sim.fuentes.BusTiempoReal` y calcula, sin
mirar al futuro:

  - la **degradacion** por rueda a partir del ``grip`` de AC (``tyreWear``,
    auto-calibrado contra su pico: ``(pico - grip) / pico``), o de la columna
    ``degradacion`` inyectada por :class:`~sim.fuentes.FuenteCSV` en modo seco;
  - las **features** de la ultima ventana (reutiliza `src.features`);
  - la **prediccion** de las proximas vueltas con el mismo Kalman de la Etapa 1
    (`src.modelo.KalmanDegradacion`);
  - el **espectro** de Welch de la ventana reciente.

:class:`LoggerVivo` escribe el CSV crudo con el esquema del proyecto (para
reprocesarlo en batch) y, si hay verdad, un ``<nombre>_verdad.csv`` companero
que el pipeline detecta automaticamente.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch

from src import features
from src.config import RUEDAS, columnas_esquema
from src.modelo import KalmanDegradacion

from sim.fuentes import BusTiempoReal, columnas_de


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
        self.pico: dict[str, float] = {w: 0.0 for w in RUEDAS}
        self.deg_actual: dict[str, float] = {w: float("nan") for w in RUEDAS}
        self._modo = "none"
        self.lap: int | None = None
        self._por_vuelta: dict[int, float] = {}
        self._suma = {w: 0.0 for w in RUEDAS}
        self._cuenta = {w: 0 for w in RUEDAS}
        bus.suscribir(self._on_muestra)

    # --- consumo ---
    def _on_muestra(self, m: dict) -> None:
        with self._lock:
            self.n += 1
            self.ultimo = m
            lap = m.get("lap")
            lap = int(lap) if lap is not None else None
            if lap is not None and self.lap is not None and lap != self.lap:
                self._cerrar_vuelta(self.lap)
            self.lap = lap
            self._actualizar_degradacion(m)
            for w in RUEDAS:
                d = self.deg_actual[w]
                if d == d:  # no NaN
                    self._suma[w] += d
                    self._cuenta[w] += 1

    def _actualizar_degradacion(self, m: dict) -> None:
        tiene_grip = any(m.get(f"grip_{w}") for w in RUEDAS)
        if tiene_grip:
            self._modo = "verdad"
            for w in RUEDAS:
                g = m.get(f"grip_{w}")
                if g is None or not np.isfinite(g) or g <= 0:
                    self.deg_actual[w] = float("nan")
                    continue
                self.pico[w] = max(self.pico[w], float(g))
                self.deg_actual[w] = float(
                    np.clip((self.pico[w] - float(g)) / self.pico[w], 0.0, 1.0)
                )
            return
        d = m.get("degradacion")
        if d is not None and np.isfinite(d):
            self._modo = "verdad"
            for w in RUEDAS:
                self.deg_actual[w] = float(d)
            return
        self._modo = "none"
        for w in RUEDAS:
            self.deg_actual[w] = float("nan")

    def _cerrar_vuelta(self, lap: int) -> None:
        valores = [
            self._suma[w] / self._cuenta[w] for w in RUEDAS if self._cuenta[w] > 0
        ]
        if valores:
            self._por_vuelta[int(lap)] = float(np.mean(valores))
        self._suma = {w: 0.0 for w in RUEDAS}
        self._cuenta = {w: 0 for w in RUEDAS}

    # --- estado ---
    def estado(self) -> dict:
        with self._lock:
            ultimo = dict(self.ultimo) if self.ultimo else None
            deg = dict(self.deg_actual)
            modo = self._modo
            lap = self.lap
            por_vuelta = dict(self._por_vuelta)
            n = self.n

        degradacion = {w: _num(deg[w]) for w in RUEDAS}
        validos = [v for v in degradacion.values() if v is not None]
        media = float(np.mean(validos)) if validos else None

        prediccion = self._predecir(por_vuelta, lap)
        ventana = self.bus.ultimas(self.W)
        feats = self._features(ventana)
        espectro = self._espectro(ventana)

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
            "prediccion": prediccion,
            "features": feats,
            "espectro": espectro,
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

    # --- calculos ---
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
        laps = df["lap"].to_numpy()
        if len(np.unique(laps)) != 1:
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
        x = np.array([m.get(canal, np.nan) for m in ventana], dtype=float)
        x = x[np.isfinite(x)]
        if x.size < 16:
            return None
        nps = int(min(self.nperseg, x.size))
        freqs, psd = welch(x, fs=float(self.cfg["fs"]), nperseg=nps, noverlap=nps // 2)
        return {
            "canal": canal,
            "freqs": [round(float(f), 4) for f in freqs],
            "psd_db": [round(float(10.0 * np.log10(max(v, 1e-20))), 3) for v in psd],
        }

    def _predecir(self, por_vuelta: dict[int, float], lap: int | None) -> dict | None:
        serie = dict(por_vuelta)
        # vuelta en curso (media parcial) como ultima observacion provisional
        with self._lock:
            actual = [
                self._suma[w] / self._cuenta[w] for w in RUEDAS if self._cuenta[w] > 0
            ]
        if actual and lap is not None:
            serie[int(lap)] = float(np.mean(actual))
        if len(serie) < 3:
            return {"laps_obs": sorted(serie), "media": [], "banda_inf": [], "banda_sup": [], "laps_pred": []}

        laps_obs = sorted(serie)
        obs = np.array([serie[l] for l in laps_obs], dtype=float)
        kc = self.cfg["modelo"]["kalman"]
        kal = KalmanDegradacion(
            float(kc["q_nivel"]),
            float(kc["q_pendiente"]),
            float(kc["r"]),
            monotono=bool(kc.get("monotono", True)),
        )
        res = kal.filtrar(obs)
        medias, var = kal.predecir(res, self.anticipacion)
        z = float(self.cfg["evaluacion"]["z"])
        desv = np.sqrt(np.maximum(var, 0.0))
        return {
            "laps_obs": [int(l) for l in laps_obs],
            "obs": [round(float(v), 4) for v in obs],
            "laps_pred": [int(laps_obs[-1] + i + 1) for i in range(self.anticipacion)],
            "media": [round(float(v), 4) for v in medias],
            "banda_inf": [round(float(v - z * d), 4) for v, d in zip(medias, desv)],
            "banda_sup": [round(float(v + z * d), 4) for v, d in zip(medias, desv)],
        }


class LoggerVivo:
    """Escribe el CSV crudo (esquema) y su ``_verdad.csv`` si hay etiqueta."""

    def __init__(self, dir_salida: str | Path, nombre: str, registrar_verdad: bool = True):
        self.dir = Path(dir_salida)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.nombre = nombre
        self.ruta = self.dir / f"{nombre}.csv"
        self.ruta_verdad = self.dir / f"{nombre}_verdad.csv"
        self.registrar_verdad = bool(registrar_verdad)
        self.columnas = columnas_esquema()
        self._fh = open(self.ruta, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._fh)
        self._w.writerow(self.columnas)
        self._fh_verdad = None
        self._w_verdad = None
        self.n = 0
        self.n_verdad = 0

    def _abrir_verdad(self) -> None:
        if self._fh_verdad is not None:
            return
        self._fh_verdad = open(self.ruta_verdad, "w", newline="", encoding="utf-8")
        self._w_verdad = csv.writer(self._fh_verdad)
        self._w_verdad.writerow(["timestamp_s", "lap", "degradacion"])

    def registrar(self, m: dict) -> None:
        if not all(c in m for c in self.columnas):
            return
        self._w.writerow([_csv(m.get(c)) for c in self.columnas])
        self.n += 1
        if self.registrar_verdad and "degradacion" in m and m["degradacion"] is not None:
            self._abrir_verdad()
            self._w_verdad.writerow([_csv(m.get("timestamp_s")), _csv(m.get("lap")), _csv(m.get("degradacion"))])
            self.n_verdad += 1
        if self.n % 100 == 0:
            self._fh.flush()
            if self._fh_verdad is not None:
                self._fh_verdad.flush()

    def cerrar(self) -> None:
        for fh in (self._fh, self._fh_verdad):
            if fh is not None:
                try:
                    fh.flush()
                    fh.close()
                except Exception:  # noqa: BLE001
                    pass
        self._fh_verdad = None
        # si no hubo verdad, no dejes un archivo con solo la cabecera
        if self.registrar_verdad and self.n_verdad == 0 and self.ruta_verdad.exists():
            self.ruta_verdad.unlink(missing_ok=True)


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
