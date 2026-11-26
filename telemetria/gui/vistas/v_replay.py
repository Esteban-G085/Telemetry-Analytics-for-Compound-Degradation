"""Vista de replay: detalle de una señal y comparador de varias señales.

Endpoint: GET /api/telemetria/vuelta/{lap}

Dos formas de mirar la misma vuelta:
  * Detalle: crudo vs. limpio de una señal, con outliers y KPIs.
  * Comparador: varias señales a la vez sobre el mismo eje temporal.
"""

from __future__ import annotations

from bisect import bisect_left

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.etiquetas_canales import (
    descripcion_canal,
    etiqueta_canal,
    filtrar_canales,
)
from telemetria.gui.glosario import tooltip
from telemetria.gui.paleta import (
    BORDE_SUAVE,
    PAPEL,
    TEXTO,
    TEXTO_SUAVE,
    color_serie,
)
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable

PRESETS: dict[str, tuple[str, ...]] = {
    "Acelerador + freno": ("throttle", "brake"),
    "Velocidad + deslizamiento": ("speed_kmh", "wheel_slip_fl"),
    "Temperaturas por rueda": (
        "temp_core_c_fl",
        "temp_core_c_fr",
        "temp_core_c_rl",
        "temp_core_c_rr",
    ),
}


class VistaReplay(VistaBase):
    """Panel de replay con detalle de señal y comparador multi-señal."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._laps: list[int] = []
        self._canales: list[str] = []
        self._curvas_comparar: dict[str, object] = {}
        self._t_comparar: list[float] = []
        self._x_comparar_visible: list[float] = []
        self._series_comparar: dict[str, list] = {}
        self._y_comparar_visible: dict[str, list] = {}
        self._rangos_comparar: dict[str, tuple[float, float]] = {}
        self._curva_diferencia: object | None = None
        self._linea_cursor: object | None = None
        self._lectura_cursor: object | None = None
        self._construir_ui()
        self._conectar_senales()
        # Vueltas y canales llegan con sesion_activa_recibida.

    @staticmethod
    def _tarjeta(titulo: str, explicacion: str) -> tuple[QFrame, QLabel]:
        """Crea una tarjeta pequeña; devuelve el marco y su etiqueta de valor."""
        caja = QFrame()
        caja.setStyleSheet(
            f"QFrame {{ background: {PAPEL}; border: 1px solid {BORDE_SUAVE}; "
            f"border-radius: 6px; }}"
        )
        caja.setToolTip(explicacion)
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        titulo_label = QLabel(titulo)
        titulo_label.setStyleSheet(f"color: {TEXTO_SUAVE}; font-size: 11px;")
        valor = QLabel("—")
        valor.setStyleSheet(f"color: {TEXTO}; font-size: 16px; font-weight: 600;")
        valor.setToolTip(explicacion)

        lay.addWidget(titulo_label)
        lay.addWidget(valor)
        return caja, valor

    def _limpiar_tarjetas(self) -> None:
        for etiqueta in (
            self.lbl_muestras_validas,
            self.lbl_descartadas,
            self.lbl_calidad,
        ):
            etiqueta.setText("—")

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Mira una vuelta de dos formas. <b>Comparar señales</b> junta "
            "acelerador, freno u otras señales en el mismo eje: mueve el ratón "
            "para leer sus valores, cambia a <b>Progreso de vuelta</b> si "
            "quieres comparar por recorrido, o activa <b>Diferencia A − B</b> "
            "con dos señales. <b>Detalle de una señal</b> muestra la original "
            "frente a la filtrada; el amarillo marca valores descartados."
        )

        grp_controles = QGroupBox("Vuelta y señal")
        lay = QHBoxLayout()

        self.combo_lap = QComboBox()
        self.combo_lap.setMinimumWidth(100)
        lay.addWidget(QLabel("Vuelta:"))
        lay.addWidget(self.combo_lap)

        self.combo_canal = QComboBox()
        self.combo_canal.setMinimumWidth(220)
        lay.addWidget(QLabel("Señal:"))
        lay.addWidget(self.combo_canal)

        self.btn_cargar = QPushButton("Cargar vuelta")
        lay.addWidget(self.btn_cargar)
        lay.addStretch()
        grp_controles.setLayout(lay)
        layout.addWidget(grp_controles)

        # --- Comparador de señales ---
        grp_comparar = QGroupBox("Comparar señales de la vuelta")
        lay_c = QVBoxLayout()

        lay_preset = QHBoxLayout()
        self.combo_preset = QComboBox()
        self.combo_preset.addItem("Elegir combinación...")
        self.combo_preset.addItems(PRESETS)
        self.combo_preset.setCurrentText("Acelerador + freno")
        self.combo_preset.setToolTip(
            "Selecciona varias señales habituales de una vez. También puedes "
            "marcarlas una a una en la lista."
        )
        lay_preset.addWidget(QLabel("Atajo:"))
        lay_preset.addWidget(self.combo_preset)
        lay_preset.addStretch()
        lay_c.addLayout(lay_preset)

        self.lista_comparar = QListWidget()
        self.lista_comparar.setMaximumHeight(120)
        self.lista_comparar.setToolTip(
            "Marca las señales que quieres dibujar juntas."
        )
        lay_c.addWidget(self.lista_comparar)

        self.chk_normalizar = QCheckBox("Normalizar señales (0–1)")
        self.chk_normalizar.setToolTip(
            "Útil cuando las señales tienen unidades distintas: cada curva se "
            "escala entre 0 y 1 para comparar su forma. La leyenda muestra el "
            "rango original de cada señal."
        )

        self.chk_progreso = QCheckBox("Progreso de vuelta (%)")
        self.chk_progreso.setToolTip(tooltip("progreso"))

        self.chk_diferencia = QCheckBox("Diferencia A − B")
        self.chk_diferencia.setToolTip(tooltip("diferencia"))

        self.btn_encuadrar = QPushButton("Ver toda la vuelta")
        self.btn_encuadrar.setToolTip(tooltip("encuadrar"))

        lay_opciones = QHBoxLayout()
        for control in (
            self.chk_normalizar,
            self.chk_progreso,
            self.chk_diferencia,
            self.btn_encuadrar,
        ):
            lay_opciones.addWidget(control)
        lay_opciones.addStretch()
        lay_c.addLayout(lay_opciones)

        self.grafico_comparar = pg.PlotWidget()
        self.grafico_comparar.setLabel("left", "Valor")
        self.grafico_comparar.setLabel("bottom", "Tiempo (s)")
        self.grafico_comparar.showGrid(x=True, y=True)
        self.grafico_comparar.setTitle("Comparador (elige señales)")
        self._leyenda_comparar = self.grafico_comparar.addLegend()
        self.grafico_comparar.setToolTip(tooltip("cursor"))
        self.grafico_comparar.setMinimumHeight(300)
        lay_c.addWidget(self.grafico_comparar)

        grp_comparar.setLayout(lay_c)
        layout.addWidget(grp_comparar, stretch=1)

        # --- Detalle de una señal (comportamiento anterior) ---
        self.grafico = pg.PlotWidget()
        self.grafico.setLabel("left", "Valor")
        self.grafico.setLabel("bottom", "Tiempo (s)")
        self.grafico.showGrid(x=True, y=True)
        self.grafico.setTitle("Detalle (sin datos)")

        self.curva_limpia = self.grafico.plot(
            pen=pg.mkPen("g", width=2), name="Filtrada"
        )
        self.curva_cruda = self.grafico.plot(
            pen=pg.mkPen("r", width=1), name="Original"
        )
        self.puntos_outlier = pg.ScatterPlotItem(
            pen=pg.mkPen("y"), brush=pg.mkBrush("y")
        )
        self.grafico.addItem(self.puntos_outlier)
        self.grafico.addLegend()
        self.grafico.setMinimumHeight(350)

        grp_grafico = QGroupBox("Detalle de una señal")
        lay_g = QVBoxLayout()
        lay_g.addWidget(self.grafico)
        grp_grafico.setLayout(lay_g)
        layout.addWidget(grp_grafico, stretch=1)

        grp_calidad = QGroupBox("Calidad de la vuelta")
        lay_k = QHBoxLayout()
        caja_validas, self.lbl_muestras_validas = self._tarjeta(
            "Muestras válidas", tooltip("vuelta")
        )
        caja_descartadas, self.lbl_descartadas = self._tarjeta(
            "Descartadas", tooltip("outlier")
        )
        caja_calidad, self.lbl_calidad = self._tarjeta(
            "Calidad (%)", tooltip("calidad")
        )
        for caja in (caja_validas, caja_descartadas, caja_calidad):
            lay_k.addWidget(caja)
        grp_calidad.setLayout(lay_k)
        layout.addWidget(grp_calidad)

        self.lbl_kpis = QLabel("Carga una vuelta para ver sus métricas.")
        self.lbl_kpis.setWordWrap(True)
        layout.addWidget(self.lbl_kpis)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_cargar.clicked.connect(self._cargar_vuelta)
        self.combo_lap.currentIndexChanged.connect(self._cargar_vuelta)
        self.combo_lap.currentIndexChanged.connect(self._cargar_comparacion)
        self.combo_canal.currentIndexChanged.connect(self._cargar_vuelta)

        self.combo_preset.currentTextChanged.connect(self._aplicar_preset)
        self.lista_comparar.itemChanged.connect(self._on_comparacion_cambiada)
        self.chk_normalizar.toggled.connect(self._cargar_comparacion)
        self.chk_progreso.toggled.connect(self._actualizar_eje_comparacion)
        self.chk_diferencia.toggled.connect(self._actualizar_diferencia)
        self.btn_encuadrar.clicked.connect(self._encuadrar_comparacion)
        self.grafico_comparar.scene().sigMouseMoved.connect(
            self._mover_cursor_comparacion
        )

        self.api.sesion_activa_recibida.connect(self._actualizar_laps)
        self.api.error_sesion_activa.connect(self._mostrar_error_sesion)
        self.api.canales_recibidos.connect(self._actualizar_canales)
        self.api.error_canales.connect(self._mostrar_error_canales)
        self.api.vuelta_recibida.connect(self._dibujar_vuelta)
        self.api.error_vuelta.connect(self._mostrar_error_vuelta)
        self.api.vuelta_comparar_recibida.connect(self._dibujar_comparacion)
        self.api.error_vuelta_comparar.connect(self._mostrar_error_comparacion)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        """Los laps los actualiza _actualizar_laps; aqui solo canales."""
        self.api.canales()

    def _actualizar_laps(self, sesion: dict) -> None:
        laps = sesion.get("laps", [])
        self._laps = laps if isinstance(laps, list) else []
        self.combo_lap.clear()
        self.combo_lap.addItems([str(l) for l in self._laps])
        if self._laps:
            self._cargar_vuelta()

    def _actualizar_canales(self, datos: dict) -> None:
        brutos = datos.get("canales", [])
        self._canales = filtrar_canales(brutos) if isinstance(brutos, list) else []

        self.combo_canal.blockSignals(True)
        self.combo_canal.clear()
        for canal in self._canales:
            fila = self.combo_canal.count()
            self.combo_canal.addItem(etiqueta_canal(canal), canal)
            self.combo_canal.setItemData(
                fila, descripcion_canal(canal), Qt.ItemDataRole.ToolTipRole
            )
        if "wheel_slip_fl" in self._canales:
            self.combo_canal.setCurrentIndex(
                self.combo_canal.findData("wheel_slip_fl")
            )
        self.combo_canal.blockSignals(False)

        self.lista_comparar.blockSignals(True)
        self.lista_comparar.clear()
        for canal in self._canales:
            item = QListWidgetItem(etiqueta_canal(canal))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, canal)
            item.setToolTip(descripcion_canal(canal))
            self.lista_comparar.addItem(item)
        self.lista_comparar.blockSignals(False)

        self._aplicar_preset(self.combo_preset.currentText())
        if self._laps:
            self._cargar_vuelta()

    # ------------------------------------------------------------ Comparador
    def _aplicar_preset(self, nombre: str) -> None:
        canales = PRESETS.get(nombre)
        if not canales:
            return
        disponibles = [c for c in canales if c in self._canales]
        self.lista_comparar.blockSignals(True)
        for i in range(self.lista_comparar.count()):
            item = self.lista_comparar.item(i)
            marcado = item.data(Qt.ItemDataRole.UserRole) in disponibles
            item.setCheckState(
                Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked
            )
        self.lista_comparar.blockSignals(False)
        self._cargar_comparacion()

    def _on_comparacion_cambiada(self, _item: QListWidgetItem | None = None) -> None:
        self._cargar_comparacion()

    def _seleccion_comparar(self) -> list[str]:
        seleccion: list[str] = []
        for i in range(self.lista_comparar.count()):
            item = self.lista_comparar.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                canal = item.data(Qt.ItemDataRole.UserRole)
                if canal:
                    seleccion.append(canal)
        return seleccion

    def _cargar_comparacion(self) -> None:
        if not self._laps:
            return
        texto = self.combo_lap.currentText()
        if not texto.isdigit():
            return
        canales = self._seleccion_comparar()
        if not canales:
            self._limpiar_comparacion()
            self.grafico_comparar.setTitle("Comparador (elige señales)")
            return
        self.api.vuelta_comparar(lap=int(texto), canales=canales, crudo=False)

    def _limpiar_comparacion(self) -> None:
        for curva in list(self._curvas_comparar.values()):
            if self._leyenda_comparar is not None:
                self._leyenda_comparar.removeItem(curva)
            self.grafico_comparar.removeItem(curva)
        self._curvas_comparar.clear()
        self._series_comparar.clear()
        self._y_comparar_visible.clear()
        self._rangos_comparar.clear()
        self._t_comparar = []
        self._x_comparar_visible = []
        self._actualizar_diferencia()
        self._ocultar_cursor()

    @staticmethod
    def _normalizar(valores: list) -> list[float]:
        numeros = [v for v in valores if v is not None]
        if not numeros:
            return [0.0 for _ in valores]
        minimo, maximo = min(numeros), max(numeros)
        if maximo == minimo:
            return [0.5 for _ in valores]
        return [
            (float(v) - minimo) / (maximo - minimo) if v is not None else 0.0
            for v in valores
        ]

    @staticmethod
    def _fmt(valor) -> str:
        if valor is None:
            return "—"
        try:
            return f"{float(valor):.2f}"
        except (TypeError, ValueError):
            return str(valor)

    def _nombre_serie(self, canal: str, normalizar: bool) -> str:
        nombre = etiqueta_canal(canal)
        if not normalizar:
            return nombre
        rango = self._rangos_comparar.get(canal)
        if rango:
            return f"{nombre} ({rango[0]:.2f}–{rango[1]:.2f})"
        return nombre

    def _x_para_comparar(self, t: list) -> list[float]:
        if not self.chk_progreso.isChecked() or len(t) < 2:
            return [float(x) if x is not None else 0.0 for x in t]
        inicio, fin = float(t[0]), float(t[-1])
        span = fin - inicio
        if span <= 0:
            return [0.0 for _ in t]
        return [100.0 * (float(x) - inicio) / span for x in t]

    def _y_para_comparar(self, canal: str) -> list[float]:
        valores = self._series_comparar.get(canal, [])
        if self.chk_normalizar.isChecked():
            return self._normalizar(valores)
        return [float(v) if v is not None else 0.0 for v in valores]

    def _actualizar_eje_comparacion(self) -> None:
        self.grafico_comparar.setLabel(
            "bottom",
            "Progreso de vuelta (%)" if self.chk_progreso.isChecked() else "Tiempo (s)",
        )
        if not self._series_comparar:
            return
        self._x_comparar_visible = self._x_para_comparar(self._t_comparar)
        for canal, curva in self._curvas_comparar.items():
            curva.setData(
                self._x_comparar_visible, self._y_comparar_visible.get(canal, [])
            )
        self._actualizar_diferencia()
        self._ocultar_cursor()

    def _actualizar_diferencia(self, _marcado=None) -> None:
        if self._curva_diferencia is not None:
            if self._leyenda_comparar is not None:
                self._leyenda_comparar.removeItem(self._curva_diferencia)
            self.grafico_comparar.removeItem(self._curva_diferencia)
            self._curva_diferencia = None
        if not self.chk_diferencia.isChecked():
            return

        canales = list(self._series_comparar)
        if len(canales) != 2 or not self._x_comparar_visible:
            return
        a = self._y_comparar_visible.get(canales[0], [])
        b = self._y_comparar_visible.get(canales[1], [])
        if not a or not b:
            return
        diferencia = [
            (float(x) - float(y)) if x is not None and y is not None else 0.0
            for x, y in zip(a, b)
        ]
        self._curva_diferencia = self.grafico_comparar.plot(
            self._x_comparar_visible,
            diferencia,
            pen=pg.mkPen(TEXTO_SUAVE, width=1, style=Qt.PenStyle.DashLine),
            name="Diferencia A − B",
        )

    def _encuadrar_comparacion(self) -> None:
        if not self._x_comparar_visible:
            return
        self.grafico_comparar.setXRange(
            min(self._x_comparar_visible),
            max(self._x_comparar_visible),
            padding=0.02,
        )
        self.grafico_comparar.enableAutoRange(axis="y")
        self._ocultar_cursor()

    def _ocultar_cursor(self) -> None:
        if self._linea_cursor is not None:
            self._linea_cursor.hide()
        if self._lectura_cursor is not None:
            self._lectura_cursor.hide()

    def _mover_cursor_comparacion(self, pos) -> None:
        if not self._x_comparar_visible or not self._series_comparar:
            return
        grafico = self.grafico_comparar
        if not grafico.plotItem.sceneBoundingRect().contains(pos):
            return
        x = grafico.plotItem.vb.mapSceneToView(pos).x()
        x_min, x_max = grafico.plotItem.vb.viewRange()[0]
        if x < x_min or x > x_max:
            return

        idx = bisect_left(self._x_comparar_visible, x)
        candidatos = [
            i for i in (idx - 1, idx) if 0 <= i < len(self._x_comparar_visible)
        ]
        if not candidatos:
            return
        mejor = min(
            candidatos,
            key=lambda i: abs(self._x_comparar_visible[i] - x),
        )

        if self._linea_cursor is None:
            self._linea_cursor = pg.InfiniteLine(
                angle=90,
                movable=False,
                pen=pg.mkPen(TEXTO_SUAVE, width=1, style=Qt.PenStyle.DotLine),
            )
            grafico.addItem(self._linea_cursor, ignoreBounds=True)
        if self._lectura_cursor is None:
            self._lectura_cursor = pg.TextItem(color=TEXTO, anchor=(0.02, 0.98))
            grafico.addItem(self._lectura_cursor, ignoreBounds=True)

        x_visible = self._x_comparar_visible[mejor]
        self._linea_cursor.setPos(x_visible)
        self._linea_cursor.show()

        if self.chk_progreso.isChecked():
            cabecera = f"{x_visible:.1f} % de vuelta"
        else:
            cabecera = f"t = {self._fmt(self._t_comparar[mejor])} s"
        lineas = [cabecera]
        for canal, valores in self._series_comparar.items():
            nombre = etiqueta_canal(canal)
            original = self._fmt(valores[mejor])
            if self.chk_normalizar.isChecked():
                visible = self._fmt(self._y_comparar_visible[canal][mejor])
                lineas.append(f"{nombre}: {original} · {visible} (0–1)")
            else:
                lineas.append(f"{nombre}: {original}")
        self._lectura_cursor.setText("\n".join(lineas))

        y_min, y_max = grafico.plotItem.vb.viewRange()[1]
        self._lectura_cursor.setPos(x_visible, y_max - 0.05 * (y_max - y_min))
        self._lectura_cursor.show()

    def _dibujar_comparacion(self, datos: dict) -> None:
        t = list(datos.get("t") or [])
        series = datos.get("series") or {}
        normalizar = self.chk_normalizar.isChecked()
        canales = [c for c in self._seleccion_comparar() if c in series]
        self._limpiar_comparacion()
        if not canales:
            self.grafico_comparar.setTitle("Comparador (elige señales)")
            return

        longitud = min([len(t)] + [len(series[c]) for c in canales])
        t = t[:longitud]
        self._t_comparar = t
        self._x_comparar_visible = self._x_para_comparar(t)

        for indice, canal in enumerate(canales):
            valores = list(series[canal])[:longitud]
            self._series_comparar[canal] = valores
            numeros = [float(v) for v in valores if v is not None]
            if numeros:
                self._rangos_comparar[canal] = (min(numeros), max(numeros))
            self._y_comparar_visible[canal] = self._y_para_comparar(canal)
            curva = self.grafico_comparar.plot(
                self._x_comparar_visible,
                self._y_comparar_visible[canal],
                pen=pg.mkPen(color_serie(indice), width=2),
                name=self._nombre_serie(canal, normalizar),
            )
            self._curvas_comparar[canal] = curva

        self.grafico_comparar.setLabel(
            "left", "Valor (0–1)" if normalizar else "Valor"
        )
        self.grafico_comparar.setLabel(
            "bottom",
            "Progreso de vuelta (%)" if self.chk_progreso.isChecked() else "Tiempo (s)",
        )
        self.grafico_comparar.setTitle(
            f"Vuelta {datos.get('lap', '?')} · {len(canales)} señales"
        )
        self._actualizar_diferencia()

    def _mostrar_error_comparacion(self, mensaje: str) -> None:
        self.grafico_comparar.setTitle(error_amigable(mensaje))

    # ------------------------------------------------------------ Detalle
    def _cargar_vuelta(self) -> None:
        if not self._laps:
            return
        texto = self.combo_lap.currentText()
        if not texto.isdigit():
            return
        lap = int(texto)
        canal = self.combo_canal.currentData()
        # Nunca mandar texto de error como parametro de la URL (httpx lo
        # rechaza con 'Invalid non-printable ASCII character in URL').
        canales_str = canal if canal in self._canales else None
        self.api.vuelta(lap=lap, canales=canales_str, crudo=True)

    def _dibujar_vuelta(self, datos: dict) -> None:
        t = datos.get("t", [])
        series = datos.get("series", {})
        crudo = datos.get("crudo")
        outliers = datos.get("outliers", {})
        kpis = datos.get("kpis", {})

        if series:
            nombre_canal = next(iter(series))
            valores = series[nombre_canal]
            self.curva_limpia.setData(t, valores)

            if crudo and nombre_canal in crudo:
                self.curva_cruda.setData(t, crudo[nombre_canal])
            else:
                self.curva_cruda.clear()

            idx_outliers = outliers.get(nombre_canal, [])
            if idx_outliers:
                xs = [t[i] for i in idx_outliers if i < len(t)]
                ys = [valores[i] for i in idx_outliers if i < len(valores)]
                self.puntos_outlier.setData(xs, ys)
            else:
                self.puntos_outlier.clear()

            self.grafico.setTitle(
                f"Vuelta {datos.get('lap', '?')} · "
                f"{etiqueta_canal(nombre_canal)} · {datos.get('sesion', '?')}"
            )

        n_total = datos.get("n_total", 0)
        n_invalidos = kpis.get("n_invalidos", 0)
        outliers_total = kpis.get("outliers_total", 0)
        valido = datos.get("valido") or []
        if valido:
            total = len(valido)
            validas = sum(1 for v in valido if v)
        else:
            total = n_total
            validas = max(total - n_invalidos, 0)
        calidad = (100.0 * validas / total) if total else 0.0

        self.lbl_muestras_validas.setText(str(validas))
        self.lbl_descartadas.setText(str(outliers_total))
        self.lbl_calidad.setText(f"{calidad:.1f} %")
        self.lbl_kpis.setText("Métricas de la vuelta cargadas.")

    def _mostrar_error_sesion(self, mensaje: str) -> None:
        self._limpiar_tarjetas()
        self.lbl_kpis.setText(error_amigable(mensaje))

    def _mostrar_error_canales(self, mensaje: str) -> None:
        self._canales = []
        self.combo_canal.blockSignals(True)
        self.combo_canal.clear()
        self.combo_canal.blockSignals(False)
        self.lista_comparar.clear()
        self._limpiar_tarjetas()
        self.lbl_kpis.setText(error_amigable(mensaje))

    def _mostrar_error_vuelta(self, mensaje: str) -> None:
        self.grafico.setTitle(error_amigable(mensaje))
        self.curva_limpia.clear()
        self.curva_cruda.clear()
        self._limpiar_tarjetas()
        self.lbl_kpis.setText(error_amigable(mensaje))
