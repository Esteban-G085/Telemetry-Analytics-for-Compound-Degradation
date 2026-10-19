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

:class:`LoggerVivo` escribe el CSV **crudo** (antes del acondicionador, para
reprocesarlo en batch segun D7) con el esquema del proyecto mas las columnas
extra ``packetId``, ``grip_*`` y ``degradacion`` (A1/A5) y, si hay verdad, un
``<nombre>_verdad.csv`` companero que el pipeline detecta automaticamente.
"""

from __future__ import annotations

import csv
import threading
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch

from telemetria.pipeline import features
from telemetria.pipeline.config import RUEDAS, columnas_esquema
from telemetria.pipeline.modelo import KalmanDegradacion

from telemetria.adquisicion.fuentes import BusTiempoReal, columnas_de


class _FiltroKalmanVivo:
    """Kalman nivel+tendencia que se actualiza vuelta a vuelta (B5).

    Mantiene el estado filtrado y cuantas observaciones lleva asimiladas, para
    que ``estado()`` no vuelva a filtrar toda la historia en cada trama
    (~10 Hz). La vuelta en curso se evalua sobre una **copia** del estado, de
    modo que no contamina el filtro persistente (B4).
    """

    def __init__(self, cfg: dict):
        kc = cfg["modelo"]["kalman"]
        self.kal = KalmanDegradacion(
            float(kc["q_nivel"]),
            float(kc["q_pendiente"]),
            float(kc["r"]),
            monotono=bool(kc.get("monotono", True)),
        )
        self.reiniciar()

    def reiniciar(self) -> None:
        self._x = None
        self._P = None
        self._nivel_prev: float | None = None
        self._n = 0

    @property
    def n(self) -> int:
        return self._n

    def agregar(self, obs: float) -> None:
        obs = float(obs)
        if self._x is None:
            self._x = np.array([obs, 0.0])
            self._P = np.diag([1.0, 1e-4])
        self._x, self._P = self.kal.paso(self._x, self._P, obs, nivel_prev=self._nivel_prev)
        self._nivel_prev = float(self._x[0])
        self._n += 1

    def estado_actual(self):
        if self._x is None:
            return None
        return self._x.copy(), self._P.copy(), self._nivel_prev


def _rellenar_huecos(x: np.ndarray) -> np.ndarray | None:
    """Recorta extremos NaN e interpola los huecos internos (B9).

    El Welch en vivo descartaba los NaN y concatenaba el resto, uniendo
    muestras separadas en el tiempo y metiendo discontinuidades artificiales en
    la PSD. Aqui se recorta lo no valido del borde y se interpola el interior.
    """
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
    #: Vueltas completas usadas para calibrar el pico de grip (B1).
    VUELTAS_CALIB_PICO = 5
    #: Percentil del grip de las primeras vueltas que fija el pico (B1).
    PICO_PERCENTIL = 95.0
    #: Salto absoluto de grip sobre el minimo reciente que delata un cambio de
    #: neumaticos (el grip vuelve al nivel de set nuevo) (B1).
    UMBRAL_SALTO_GRIP = 0.05
    #: Muestras recientes (a fs de salida, ~5 s) que definen el minimo contra el
    #: que se detecta el salto.
    VENTANA_RECIENTE_GRIP = 500
    #: Tope del factor de R para la vuelta en curso (media parcial ruidosa, B4).
    R_PARCIAL_MAX = 25.0

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
        # Historia por rueda y prediccion incremental (B4/B5).
        self._por_vuelta_rueda: dict[str, dict[int, float]] = {w: {} for w in RUEDAS}
        self._n_lap: list[int] = []
        self._n_lap_r: dict[str, list[int]] = {w: [] for w in RUEDAS}
        self._filtro = _FiltroKalmanVivo(cfg)
        self._filtros_r = {w: _FiltroKalmanVivo(cfg) for w in RUEDAS}
        # Calibracion robusta del pico (B1).
        self._calibrando_pico = True
        self._muestras_pico: dict[str, list[float]] = {w: [] for w in RUEDAS}
        self._vueltas_calib: set[int] = set()
        # Grip reciente por rueda para detectar cambio de neumaticos (B1).
        self._grip_reciente: dict[str, deque[float]] = {
            w: deque(maxlen=self.VENTANA_RECIENTE_GRIP) for w in RUEDAS
        }
        # Logger opcional para volcar la verdad derivada del grip (A5, solo AC).
        self.logger = None
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
                    # La vuelta retrocede: nueva sesion/stint (B10). No se
                    # sobrescribe la historia: se reinicia (neumaticos nuevos).
                    self._reiniciar_stint()
                else:
                    self._cerrar_vuelta(self.lap)
            self.lap = lap
            self._actualizar_degradacion(m)
            for w in RUEDAS:
                d = self.deg_actual[w]
                if d == d:  # no NaN
                    self._suma[w] += d
                    self._cuenta[w] += 1

    def _actualizar_degradacion(self, m: dict) -> None:
        # ``grip = 0.0`` es el centinela de "sin senal" (modo seco y tests):
        # solo habilita la rama de grip un valor finito y positivo. Un NaN
        # tampoco la habilita, de modo que se cae a la columna ``degradacion``
        # inyectada (o a modo "none") de forma consistente.
        tiene_grip = any(
            isinstance(g, (int, float, np.floating)) and np.isfinite(g) and g > 0
            for g in (m.get(f"grip_{w}") for w in RUEDAS)
        )
        if tiene_grip:
            self._modo = "verdad"
            for w in RUEDAS:
                g = m.get(f"grip_{w}")
                if g is None or not np.isfinite(g) or g <= 0:
                    self.deg_actual[w] = float("nan")
                    continue
                g = float(g)
                self._grip_reciente[w].append(g)
                if self._calibrando_pico:
                    self._muestras_pico[w].append(g)
                    self.pico[w] = max(self.pico[w], g)
                elif (
                    len(self._grip_reciente[w]) >= 10
                    and g - min(self._grip_reciente[w]) > self.UMBRAL_SALTO_GRIP
                ):
                    # El grip vuelve al nivel de un set nuevo: cambio de
                    # neumaticos detectado (B1). Se recalibra el pico.
                    self._reiniciar_calibracion_pico()
                    self._muestras_pico[w].append(g)
                    self.pico[w] = max(self.pico[w], g)
                if self.pico[w] > 0:
                    self.deg_actual[w] = float(
                        np.clip((self.pico[w] - g) / self.pico[w], 0.0, 1.0)
                    )
                else:
                    self.deg_actual[w] = float("nan")
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

    def _reiniciar_calibracion_pico(self) -> None:
        """Vuelve a la fase de calibracion (pico provisional = maximo)."""
        self._calibrando_pico = True
        self._muestras_pico = {w: [] for w in RUEDAS}
        self._vueltas_calib = set()
        self.pico = {w: 0.0 for w in RUEDAS}
        self._grip_reciente = {w: deque(maxlen=self.VENTANA_RECIENTE_GRIP) for w in RUEDAS}

    def _finalizar_calibracion_pico(self) -> None:
        """Fija el pico como el percentil P95 de las primeras vueltas (B1)."""
        for w in RUEDAS:
            muestras = self._muestras_pico[w]
            if len(muestras) >= 10:
                self.pico[w] = float(
                    np.percentile(np.asarray(muestras, dtype=float), self.PICO_PERCENTIL)
                )
            # si no hay muestras suficientes se queda el maximo provisional
        self._muestras_pico = {w: [] for w in RUEDAS}
        self._vueltas_calib = set()
        self._calibrando_pico = False

    def _cerrar_vuelta(self, lap: int) -> None:
        lap = int(lap)
        por_rueda: dict[str, float] = {}
        for w in RUEDAS:
            if self._cuenta[w] > 0:
                valor = self._suma[w] / self._cuenta[w]
                por_rueda[w] = valor
                self._por_vuelta_rueda[w][lap] = valor
                self._n_lap_r[w].append(int(self._cuenta[w]))
                self._filtros_r[w].agregar(valor)
        if por_rueda:
            valores = list(por_rueda.values())
            agg = float(np.mean(valores))
            self._por_vuelta[lap] = agg
            self._n_lap.append(int(np.mean([self._cuenta[w] for w in por_rueda])))
            self._filtro.agregar(agg)
            self._registrar_verdad(lap, agg)
        self._suma = {w: 0.0 for w in RUEDAS}
        self._cuenta = {w: 0 for w in RUEDAS}
        if self._calibrando_pico:
            self._vueltas_calib.add(lap)
            if len(self._vueltas_calib) >= self.VUELTAS_CALIB_PICO:
                self._finalizar_calibracion_pico()

    def _reiniciar_stint(self) -> None:
        """Nueva sesion/stint (la vuelta retrocede, B10): se limpia la historia.

        Se descarta la degradacion acumulada y se vuelve a calibrar el pico,
        porque un reinicio de sesion implica neumaticos nuevos.
        """
        self._por_vuelta = {}
        self._por_vuelta_rueda = {w: {} for w in RUEDAS}
        self._suma = {w: 0.0 for w in RUEDAS}
        self._cuenta = {w: 0 for w in RUEDAS}
        self._n_lap = []
        self._n_lap_r = {w: [] for w in RUEDAS}
        self._filtro.reiniciar()
        for w in RUEDAS:
            self._filtros_r[w].reiniciar()
        self._reiniciar_calibracion_pico()

    def _registrar_verdad(self, lap: int, deg: float) -> None:
        """Volcan la verdad derivada del grip al logger (A5, capturas AC)."""
        if self.logger is None or self._modo != "verdad":
            return
        ts = self.ultimo.get("timestamp_s") if self.ultimo else None
        try:
            self.logger.registrar_degradacion(ts, lap, deg)
        except Exception:  # noqa: BLE001 - el logger no debe frenar el motor
            pass

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

        prediccion = self._predecir()
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
        x = _rellenar_huecos(x)
        if x is None or x.size < 16:
            return None
        nps = int(min(self.nperseg, x.size))
        freqs, psd = welch(x, fs=float(self.cfg["fs"]), nperseg=nps, noverlap=nps // 2)
        return {
            "canal": canal,
            "freqs": [round(float(f), 4) for f in freqs],
            "psd_db": [round(float(10.0 * np.log10(max(v, 1e-20))), 3) for v in psd],
        }

    def _pred_serie(self, filtro, serie, parcial, n_actual, n_ref) -> dict:
        """Prediccion de una serie (agregada o por rueda) con Kalman incremental.

        ``parcial`` es ``(lap, valor)`` de la vuelta en curso, que entra como
        ultima observacion con un ``R`` mayor (media incompleta y ruidosa, B4).
        """
        laps_obs = sorted(serie)
        obs = [serie[l] for l in laps_obs]
        if parcial is not None:
            laps_obs = laps_obs + [int(parcial[0])]
            obs = obs + [float(parcial[1])]
        salida = {
            "laps_obs": [int(l) for l in laps_obs],
            "obs": [round(float(v), 4) for v in obs],
            "media": [],
            "banda_inf": [],
            "banda_sup": [],
            "laps_pred": [],
        }
        if len(obs) < 3:
            return salida
        snap = filtro.estado_actual()
        if snap is None:
            return salida
        x, P, nivel_prev = snap
        if parcial is not None:
            x, P = filtro.kal.paso(
                x,
                P,
                float(parcial[1]),
                r=self._r_parcial(filtro, n_actual, n_ref),
                nivel_prev=nivel_prev,
            )
        medias, var = filtro.kal.predecir({"x": x, "P": P}, self.anticipacion)
        z = float(self.cfg["evaluacion"]["z"])
        desv = np.sqrt(np.maximum(var, 0.0))
        salida["laps_pred"] = [int(laps_obs[-1] + i + 1) for i in range(self.anticipacion)]
        salida["media"] = [round(float(v), 4) for v in medias]
        salida["banda_inf"] = [round(float(v - z * d), 4) for v, d in zip(medias, desv)]
        salida["banda_sup"] = [round(float(v + z * d), 4) for v, d in zip(medias, desv)]
        return salida

    def _r_parcial(self, filtro, n_actual, n_ref) -> float:
        """R de la vuelta en curso: crece cuando hay pocas muestras (B4).

        La varianza de una media parcial escala con ``1/n``; escalar ``R`` con
        ``n_ref / n_actual`` evita que una vuelta recien empezada mueva el filtro
        tanto como una vuelta completa.
        """
        base = float(filtro.kal.R[0, 0])
        try:
            n_actual = float(n_actual)
            n_ref = float(n_ref) if n_ref else 0.0
        except (TypeError, ValueError):
            return base * self.R_PARCIAL_MAX
        if n_actual <= 0 or n_ref <= 0:
            return base * self.R_PARCIAL_MAX
        return base * min(self.R_PARCIAL_MAX, n_ref / n_actual)

    def _predecir(self) -> dict:
        # Todo el calculo se hace bajo el lock: las series y el estado del
        # Kalman deben corresponder al mismo instante. Copiar las series y
        # leer ``estado_actual()`` fuera del lock dejaba una carrera (una
        # vuelta cerrada entre ambas lecturas desfasaba las etiquetas).
        with self._lock:
            lap = self.lap
            por_vuelta = dict(self._por_vuelta)
            por_vuelta_rueda = {w: dict(self._por_vuelta_rueda[w]) for w in RUEDAS}
            actual = {
                w: self._suma[w] / self._cuenta[w] for w in RUEDAS if self._cuenta[w] > 0
            }
            n_ref = float(np.median(self._n_lap)) if self._n_lap else None
            n_ref_r = {
                w: (float(np.median(self._n_lap_r[w])) if self._n_lap_r[w] else None)
                for w in RUEDAS
            }
            cuentas = dict(self._cuenta)

            lap_actual = int(lap) if lap is not None else None
            hay_parcial = (
                bool(actual) and lap_actual is not None and lap_actual not in por_vuelta
            )

            parcial = None
            if hay_parcial and self._filtro.n > 0:
                parcial = (lap_actual, float(np.mean(list(actual.values()))))
            n_actual_agg = float(np.mean(list(cuentas.values()))) if cuentas else 0.0
            salida = self._pred_serie(
                self._filtro, por_vuelta, parcial, n_actual_agg, n_ref
            )

            por_rueda: dict[str, dict] = {}
            for w in RUEDAS:
                serie = por_vuelta_rueda[w]
                if not serie:
                    continue
                part = None
                if w in actual and lap_actual is not None and lap_actual not in serie:
                    part = (lap_actual, float(actual[w]))
                por_rueda[w] = self._pred_serie(
                    self._filtros_r[w], serie, part, cuentas.get(w, 0), n_ref_r[w]
                )
            salida["por_rueda"] = por_rueda
            return salida


class LoggerVivo:
    """Escribe el CSV **crudo** (esquema + extras) y su ``_verdad.csv`` si hay etiqueta.

    El logger debe suscribirse a la fuente **antes** del acondicionador
    (``Fuente.suscribir_crudo``), no al bus: si recibe la señal ya filtrada y
    decimada, reprocesarla en batch aplica un segundo filtro y una segunda
    detección de outliers (A1, D7).
    """

    #: Columnas extra del esquema (A5): identificador de paquete y la verdad
    #: derivada del grip, para que las capturas de AC queden etiquetadas.
    COLUMNAS_EXTRA = ("packetId", "grip_fl", "grip_fr", "grip_rl", "grip_rr", "degradacion")

    def __init__(self, dir_salida: str | Path, nombre: str, registrar_verdad: bool = True):
        self.dir = Path(dir_salida)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.nombre = nombre
        self.ruta = self.dir / f"{nombre}.csv"
        self.ruta_verdad = self.dir / f"{nombre}_verdad.csv"
        self.registrar_verdad = bool(registrar_verdad)
        self.columnas = columnas_esquema() + list(self.COLUMNAS_EXTRA)
        self._lock = threading.Lock()
        # Apertura perezosa (B6): el archivo se crea en el primer registro, no
        # al construir. Asi una fuente que nunca arranca no deja un CSV vacio.
        self._fh = None
        self._w = None
        self._fh_verdad = None
        self._w_verdad = None
        self._cerrado = False
        self.n = 0
        self.n_verdad = 0

    def _abrir_principal(self) -> None:
        if self._fh is not None:
            return
        self._fh = open(self.ruta, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._fh)
        self._w.writerow(self.columnas)

    def _abrir_verdad(self) -> None:
        if self._fh_verdad is not None:
            return
        self._fh_verdad = open(self.ruta_verdad, "w", newline="", encoding="utf-8")
        self._w_verdad = csv.writer(self._fh_verdad)
        self._w_verdad.writerow(["timestamp_s", "lap", "degradacion"])

    def registrar(self, m: dict) -> None:
        with self._lock:
            if self._cerrado:
                return  # escritura tardia tras cerrar: se ignora (B11)
            if not all(c in m for c in columnas_esquema()):
                return
            self._abrir_principal()
            self._w.writerow([_csv(m.get(c)) for c in self.columnas])
            self.n += 1
            if self.registrar_verdad and "degradacion" in m and m["degradacion"] is not None:
                self._abrir_verdad()
                self._w_verdad.writerow(
                    [_csv(m.get("timestamp_s")), _csv(m.get("lap")), _csv(m.get("degradacion"))]
                )
                self.n_verdad += 1
            self._flushear()

    def registrar_degradacion(self, timestamp_s, lap, degradacion) -> None:
        """Volcan por vuelta de la verdad derivada del grip (A5)."""
        with self._lock:
            if self._cerrado or not self.registrar_verdad or degradacion is None:
                return
            self._abrir_verdad()
            self._w_verdad.writerow([_csv(timestamp_s), _csv(lap), _csv(degradacion)])
            self.n_verdad += 1
            self._flushear()

    def _flushear(self) -> None:
        if self.n % 100 == 0:
            if self._fh is not None:
                self._fh.flush()
            if self._fh_verdad is not None:
                self._fh_verdad.flush()

    def cerrar(self) -> None:
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True
            for fh in (self._fh, self._fh_verdad):
                if fh is not None:
                    try:
                        fh.flush()
                        fh.close()
                    except Exception:  # noqa: BLE001
                        pass
            self._fh = None
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
