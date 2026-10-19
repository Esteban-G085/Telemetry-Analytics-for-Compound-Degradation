"""Acondicionamiento causal de la senal en vivo (Etapa 3, D4).

En batch (`telemetria/pipeline/limpieza.py`) el filtro es causal pero se aplica sobre una rejilla
uniforme ya remuestreada con `resample_poly`. En vivo no hay futuro, asi que:

  1. Un detector de outliers **causal** por mediana/MAD en ventana deslizante
     (misma idea que `limpieza.detectar_outliers`, sin futuro): los picos se
     sustituyen por *zero-order hold* para no ensuciar el filtro y se marca la
     salida como no valida (NaN).
  2. Un IIR Butterworth pasa-bajos (SOS) aplicado **muestra a muestra** con
     recurrencia directa (forma II traspuesta), conservando el estado entre
     llamadas. Es lo bastante rapido para 333 Hz x 21 canales.
  3. Una **decimacion** a la frecuencia objetivo (por defecto 100 Hz) con un
     acumulador temporal.

Cobertura: se detectan outliers en `canales_fisicos()` (incluye `speed_kmh`) y
se filtra `canales_filtrables()`, igual que el batch. El objetivo (D14) es que la
senal decimada se parezca a la del pipeline batch; el test de coherencia lo fija.
"""

from __future__ import annotations

from collections import deque

import numpy as np
from scipy.signal import butter, sosfilt_zi

from telemetria.pipeline.config import canales_filtrables, canales_fisicos


class AcondicionadorCausal:
    def __init__(
        self,
        fs_entrada: float,
        fs_salida: float,
        corte_hz: float,
        orden: int = 4,
        *,
        canales: tuple[str, ...] | None = None,
        canales_filtro: tuple[str, ...] | None = None,
        canales_outlier: tuple[str, ...] | None = None,
        ventana_outlier_s: float = 0.5,
        mad_umbral: float = 12.0,
        piso_sigma: float = 0.0,
        ventana_global_s: float = 30.0,
        cada_outlier: int = 8,
        filtro: bool = True,
    ):
        if corte_hz >= fs_entrada / 2.0:
            raise ValueError(f"corte {corte_hz} Hz >= Nyquist de entrada {fs_entrada / 2.0} Hz")
        if corte_hz >= fs_salida / 2.0:
            raise ValueError(f"corte {corte_hz} Hz >= Nyquist de salida {fs_salida / 2.0} Hz")

        self.fs_entrada = float(fs_entrada)
        self.fs_salida = float(fs_salida)
        self.corte_hz = float(corte_hz)
        self.filtro = bool(filtro)

        if canales is not None:
            self.canales = tuple(canales)
            self.canales_filtro = tuple(canales_filtro if canales_filtro is not None else canales)
            self.canales_outlier = tuple(canales_outlier if canales_outlier is not None else canales)
        else:
            self.canales_filtro = tuple(canales_filtrables())
            self.canales_outlier = tuple(canales_fisicos())
            self.canales = tuple(dict.fromkeys([*self.canales_filtro, *self.canales_outlier]))

        if self.filtro:
            self.sos = butter(
                int(orden), self.corte_hz / (self.fs_entrada / 2.0), btype="low", output="sos"
            )
            self.sos = np.asarray(self.sos, dtype=float)
            self._zi_base = sosfilt_zi(self.sos)
            # Estado por canal: se inicializa con la primera muestra (evita el
            # transitorio desde cero; B7).
            self._z: dict[str, np.ndarray | None] = {c: None for c in self.canales_filtro}
        else:
            self.sos = None
            self._zi_base = None
            self._z = {}

        # Estado del detector de outliers y de la decimacion.
        self._ventana_out = max(5, int(round(ventana_outlier_s * self.fs_entrada)))
        self._mad_umbral = float(mad_umbral)
        self._cada_outlier = max(1, int(cada_outlier))
        self._hist = {c: deque(maxlen=self._ventana_out) for c in self.canales_outlier}
        self._out_med = {c: float("nan") for c in self.canales_outlier}
        self._out_esc = {c: float("nan") for c in self.canales_outlier}
        self._min_out = max(5, self._ventana_out // 4)
        self._contador = 0
        self._ultimo = {c: 0.0 for c in self.canales}  # zero-order hold
        self._t_acum = 0.0
        self._t_prev: float | None = None  # ultimo timestamp_s crudo visto
        self.dt = 1.0 / self.fs_entrada
        self.periodo_salida = 1.0 / self.fs_salida

        # Piso del umbral: una fraccion de la dispersion robusta **global** del
        # canal, igual que `limpieza.detectar_outliers` (D14). Sin el, en tramos de
        # senal casi constante el MAD local tiende a 0, el umbral se colapsa y todo
        # el tramo se marca como outlier -> rachas de NaN -> huecos en el
        # osciloscopio. La ventana global es larga (~30 s) para que el piso sea
        # estable aunque el tramo actual sea plano.
        self._piso_sigma = float(piso_sigma)
        self._ventana_global = max(5, int(round(float(ventana_global_s) * self.fs_entrada)))
        self._min_global = max(10, min(self._ventana_global, int(round(0.5 * self.fs_entrada))))
        self._cada_global = max(self._cada_outlier, int(round(0.25 * self.fs_entrada)))
        self._hist_global = {c: deque(maxlen=self._ventana_global) for c in self.canales_outlier}
        self._sigma_global = {c: float("nan") for c in self.canales_outlier}

    # --- filtrado (IIR directo, forma II traspuesta) ---
    def _filtrar(self, canal: str, x: float) -> float:
        if not self.filtro or self.sos is None:
            return x
        z = self._z[canal]
        if z is None:
            # Arranque sin transitorio: estado inicial sosteniendo la primera
            # muestra (B7).
            z = self._zi_base * float(x)
            self._z[canal] = z
        for i in range(self.sos.shape[0]):
            b0, b1, b2, _a0, a1, a2 = self.sos[i]
            y = b0 * x + z[i, 0]
            z[i, 0] = b1 * x - a1 * y + z[i, 1]
            z[i, 1] = b2 * x - a2 * y
            x = y
        return x

    # --- outliers ---
    def _actualizar_stats(self, canal: str, recalcular_global: bool = False) -> None:
        h = self._hist[canal]
        if len(h) >= self._min_out:
            arr = np.fromiter(h, dtype=float, count=len(h))
            med = float(np.median(arr))
            mad = float(np.median(np.abs(arr - med)))
            self._out_med[canal] = med
            self._out_esc[canal] = 1.4826 * mad
        if recalcular_global and self._piso_sigma > 0.0:
            g = self._hist_global[canal]
            if len(g) >= self._min_global:
                arr = np.fromiter(g, dtype=float, count=len(g))
                centro = float(np.median(arr))
                self._sigma_global[canal] = 1.4826 * float(np.median(np.abs(arr - centro)))

    def _es_outlier(self, canal: str) -> bool:
        med = self._out_med.get(canal, float("nan"))
        esc = self._out_esc.get(canal, float("nan"))
        if not np.isfinite(med) or not np.isfinite(esc) or esc <= 0.0:
            return False
        escala = esc
        if self._piso_sigma > 0.0:
            sigma = self._sigma_global.get(canal, float("nan"))
            # Sin referencia global todavia: no marcar (evita falsos positivos al
            # arrancar, cuando solo hay un tramo corto y el MAD local es fragil).
            if not np.isfinite(sigma) or sigma <= 0.0:
                return False
            escala = max(esc, self._piso_sigma * sigma)
        x = self._hist[canal][-1]
        return abs(x - med) > self._mad_umbral * escala

    def procesar(self, fila: dict) -> dict | None:
        """Filtra y decima una muestra cruda. ``None`` si aun no toca emitir."""
        self._contador += 1
        recalcular = (self._contador % self._cada_outlier) == 0
        recalcular_global = (self._contador % self._cada_global) == 0

        salida: dict = {}
        for c in self.canales:
            x = fila.get(c)
            if x is None or not np.isfinite(x):
                salida[c] = float("nan")
                continue
            x = float(x)

            if c in self._hist:
                self._hist[c].append(x)
                if self._piso_sigma > 0.0:
                    self._hist_global[c].append(x)
                if recalcular or not np.isfinite(self._out_med[c]):
                    self._actualizar_stats(c, recalcular_global)
                if self._es_outlier(c):
                    x = self._ultimo[c]  # hold: no contamina el filtro
                    salida[c] = float("nan")
                else:
                    salida[c] = None  # se rellena tras filtrar
            else:
                salida[c] = None

            self._ultimo[c] = x
            if c in self._z:
                filtrado = self._filtrar(c, x)
            else:
                filtrado = x
            if salida[c] is None:
                salida[c] = filtrado

        # columnas no procesadas: paso directo
        for clave, valor in fila.items():
            if clave not in salida:
                salida[clave] = valor

        # decimacion por acumulador temporal con timestamps reales (A2): se
        # acumula el dt observado (respetando el jitter), con el dt nominal como
        # respaldo si la fila no trae timestamp valido.
        t = fila.get("timestamp_s")
        dt = self.dt
        if t is not None:
            try:
                t = float(t)
            except (TypeError, ValueError):
                t = None
        if t is not None and np.isfinite(t):
            if self._t_prev is not None and t > self._t_prev:
                dt = t - self._t_prev
            self._t_prev = t
        self._t_acum += dt
        if self._t_acum + 1e-9 < self.periodo_salida:
            return None
        self._t_acum -= self.periodo_salida
        salida["timestamp_s"] = fila.get("timestamp_s")
        return salida
