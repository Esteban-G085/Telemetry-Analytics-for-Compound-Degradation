"""Vista de robustez: MAE vs ruido inyectado y simulador de fallo de sensores.

Endpoints:
    POST /api/modelos/robustez   (MAE de Ridge vs SNR)
    POST /api/modelos/sensores   (MAE al desconectar canales)

El simulador usa las familias de canal que entiende el backend
(``analisis.MAPA_SENSOR``), no nombres de columna inventados por la GUI.

Los cálculos siguen siendo los del backend. Esta vista solo los explica,
mantiene la gráfica anterior mientras llega un resultado nuevo y muestra los
valores devueltos con su interpretación.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.glosario import tooltip
from telemetria.gui.graficas import (
    ContextoZoom,
    CursorGrafico,
    limites_visualizacion,
)
from telemetria.gui.paleta import (
    ACENTO,
    ERROR,
    EXITO,
    PAPEL,
    TEXTO,
    TEXTO_SUAVE,
)
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable

SENSORES = (
    "wheel_slip",
    "temp_core_c",
    "wheel_load_n",
    "pressure_psi",
    "speed_kmh",
    "throttle",
    "brake",
    "steering",
)
RUEDAS = ("todas", "fl", "fr", "rl", "rr")

EXPLICACION_SNR = (
    "<b>MAE frente a ruido (SNR)</b><br>"
    "Objetivo: medir cuánto se degrada la predicción cuando se añade ruido a "
    "las entradas del modelo. Entrada: la sesión activa, sus features y el "
    "conjunto de prueba temporal. Variables: SNR en dB (menos dB = más ruido) "
    "frente al MAE de Ridge. Resultado: un MAE por nivel de ruido. "
    "Interpretación: si el MAE sube al bajar el SNR, el modelo es sensible al "
    "ruido; MAE más bajo significa predicción más precisa."
)
EXPLICACION_SENSORES = (
    "<b>Fallo de sensores: dos experimentos distintos</b><br>"
    "<b>Individual</b>: se desconecta un sensor cada vez y se re-entrena Ridge "
    "con las features restantes. Cada fila compara su propio MAE contra el "
    "mismo error base; la subida indica sensibilidad del modelo a perder esa "
    "información, no importancia física ni causal.<br>"
    "<b>Combinado</b>: se desconectan varios sensores a la vez y se muestra un "
    "único resultado en su propia sección. Ese resultado nunca se reparte "
    "entre las filas individuales."
)


class VistaRobustez(VistaBase):
    """Panel de robustez: MAE vs SNR y fallo de sensores."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._snr_puntos: dict[float, float] = {}
        self._snr_solicitado: float | None = None
        self._modo_sensores_solicitado = "individual"
        self._construir_ui()
        self._cursor = CursorGrafico(self.grafico_snr)
        self._conectar_senales()
        # Robustez y sensores necesitan una sesion activa.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Comprueba qué pasa cuando llega ruido o falla un sensor. SNR bajo "
            "significa más ruido; un MAE alto significa peor predicción. La "
            "columna <b>Subida del error</b> cuenta cuánto empeora al apagar "
            "ese canal. Al calcular, la gráfica anterior se conserva."
        )

        grp_explica = QGroupBox("Qué se está calculando")
        lay_explica = QVBoxLayout()
        self.lbl_explica_snr = QLabel(EXPLICACION_SNR)
        self.lbl_explica_snr.setWordWrap(True)
        self.lbl_explica_sensores = QLabel(EXPLICACION_SENSORES)
        self.lbl_explica_sensores.setWordWrap(True)
        for etiqueta in (self.lbl_explica_snr, self.lbl_explica_sensores):
            etiqueta.setStyleSheet(f"color: {TEXTO_SUAVE}; font-size: 11px;")
            lay_explica.addWidget(etiqueta)
        grp_explica.setLayout(lay_explica)
        layout.addWidget(grp_explica)

        grp_snr = QGroupBox("Error del modelo al añadir ruido (SNR)")
        lay = QHBoxLayout()

        self.spin_snr = QDoubleSpinBox()
        self.spin_snr.setRange(-20.0, 60.0)
        self.spin_snr.setDecimals(1)
        self.spin_snr.setValue(20.0)
        self.spin_snr.setToolTip(tooltip("snr"))
        lay.addWidget(QLabel("Ruido añadido (SNR dB):"))
        lay.addWidget(self.spin_snr)

        self.btn_snr = QPushButton("Calcular error")
        self.btn_snr.setToolTip(
            "Añade el nivel de ruido elegido a la curva existente. No borra "
            "los resultados anteriores."
        )
        lay.addWidget(self.btn_snr)
        lay.addStretch()
        grp_snr.setLayout(lay)
        layout.addWidget(grp_snr)

        self.lbl_estado_snr, self.progreso_snr = self._estado_y_progreso(
            "Estado: esperando una sesión activa."
        )
        layout.addWidget(self.lbl_estado_snr)
        layout.addWidget(self.progreso_snr)

        self.grafico_snr = pg.PlotWidget()
        self.grafico_snr.setLabel("left", "Error medio (MAE)")
        self.grafico_snr.setLabel("bottom", "Ruido añadido (SNR dB)")
        self.grafico_snr.showGrid(x=True, y=True)
        self.grafico_snr.setTitle("Error del modelo frente al ruido (sin datos)")
        self.curva_snr = self.grafico_snr.plot(
            pen=pg.mkPen(ACENTO, width=2), symbol="o", name="MAE"
        )
        self.punto_snr = pg.ScatterPlotItem(
            size=12,
            symbol="o",
            pen=pg.mkPen(PAPEL, width=1.5),
            brush=pg.mkBrush(ERROR),
        )
        self.grafico_snr.addItem(self.punto_snr)
        self.punto_snr.hide()
        self.grafico_snr.addLegend(offset=(8, 8))
        self.grafico_snr.setMinimumHeight(280)
        self.contexto = ContextoZoom(
            self.grafico_snr, rotulo="SNR", on_ver_todo=self._encuadrar_snr
        )

        grp_grafico = QGroupBox("Gráfico de error frente al ruido")
        lay_g = QVBoxLayout()
        lay_g.addWidget(self.grafico_snr)
        lay_g.addWidget(self.contexto)
        grp_grafico.setLayout(lay_g)
        layout.addWidget(grp_grafico, stretch=1)

        self.tabla_snr = QTableWidget(0, 3)
        self.tabla_snr.setHorizontalHeaderLabels(
            ["SNR (dB)", "Error medio (MAE)", "Lectura"]
        )
        self.tabla_snr.horizontalHeaderItem(1).setToolTip(tooltip("mae"))
        self.tabla_snr.horizontalHeaderItem(2).setToolTip(
            "Menor MAE es mejor. Se resalta el mejor y el peor de los calculados."
        )
        self.tabla_snr.horizontalHeader().setStretchLastSection(True)
        grp_tabla = QGroupBox("Resultados del barrido de ruido")
        lay_t = QVBoxLayout()
        lay_t.addWidget(self.tabla_snr)
        grp_tabla.setLayout(lay_t)
        layout.addWidget(grp_tabla)

        grp_sensores = QGroupBox("Simulador de fallo de sensores")
        lay_s = QVBoxLayout()

        lay_sel = QHBoxLayout()
        self.combo_sensor = QComboBox()
        self.combo_sensor.addItems(SENSORES)
        self.combo_rueda = QComboBox()
        self.combo_rueda.addItems(RUEDAS)
        self.btn_anadir = QPushButton("Añadir sensor")
        self.btn_quitar = QPushButton("Quitar seleccionado")
        lay_sel.addWidget(QLabel("Canal:"))
        lay_sel.addWidget(self.combo_sensor)
        lay_sel.addWidget(QLabel("Rueda:"))
        lay_sel.addWidget(self.combo_rueda)
        lay_sel.addWidget(self.btn_anadir)
        lay_sel.addWidget(self.btn_quitar)
        lay_sel.addStretch()
        lay_s.addLayout(lay_sel)

        self.tabla_seleccion = QTableWidget(0, 2)
        self.tabla_seleccion.setHorizontalHeaderLabels(["Canal", "Rueda"])
        self.tabla_seleccion.horizontalHeader().setStretchLastSection(True)
        self.tabla_seleccion.setMaximumHeight(110)
        lay_s.addWidget(self.tabla_seleccion)

        lay_acciones = QHBoxLayout()
        self.combo_modo_sensores = QComboBox()
        self.combo_modo_sensores.addItem(
            "Individual — un sensor cada vez", "individual"
        )
        self.combo_modo_sensores.addItem(
            "Combinado — todos a la vez", "combinado"
        )
        self.combo_modo_sensores.setToolTip(
            "Individual re-entrena el modelo por cada sensor. Combinado "
            "desconecta todos los seleccionados en un solo experimento."
        )
        lay_acciones.addWidget(QLabel("Experimento:"))
        lay_acciones.addWidget(self.combo_modo_sensores)
        self.btn_sensores = QPushButton("Calcular ablación")
        self.btn_sensores.setToolTip(
            "Recalcula Ridge con el modo elegido. Las tablas y la gráfica "
            "anteriores se conservan mientras llega el resultado."
        )
        lay_acciones.addWidget(self.btn_sensores)
        lay_acciones.addStretch()
        lay_s.addLayout(lay_acciones)

        grp_individual = QGroupBox("A. Evaluación individual (un sensor cada vez)")
        lay_ind = QVBoxLayout()
        self.tabla_sensores = QTableWidget(0, 5)
        self.tabla_sensores.setHorizontalHeaderLabels(
            [
                "Canal",
                "Rueda",
                "Error (MAE)",
                "Subida del error ↑",
                "Features eliminadas",
            ]
        )
        self.tabla_sensores.horizontalHeaderItem(2).setToolTip(tooltip("mae"))
        self.tabla_sensores.horizontalHeaderItem(3).setToolTip(tooltip("delta"))
        self.tabla_sensores.horizontalHeaderItem(4).setToolTip(
            "Columnas del modelo que dejan de estar disponibles con ese fallo."
        )
        self.tabla_sensores.horizontalHeader().setStretchLastSection(True)
        lay_ind.addWidget(self.tabla_sensores)

        self.grafico_ablacion = pg.PlotWidget()
        self.grafico_ablacion.setLabel("left", "Subida del error")
        self.grafico_ablacion.setLabel("bottom", "Sensor desconectado")
        self.grafico_ablacion.setTitle("Sensibilidad individual (sin datos)")
        self.grafico_ablacion.showGrid(y=True, x=False)
        self.grafico_ablacion.setMinimumHeight(170)
        self._barras_ablacion: pg.BarGraphItem | None = None
        lay_ind.addWidget(self.grafico_ablacion)

        self.lbl_sensores = QLabel(
            "Añade sensores y pulsa «Calcular ablación» en modo individual."
        )
        self.lbl_sensores.setWordWrap(True)
        lay_ind.addWidget(self.lbl_sensores)

        self.lbl_resultado_sensores = QLabel("Sin cálculo individual todavía.")
        self.lbl_resultado_sensores.setWordWrap(True)
        lay_ind.addWidget(self.lbl_resultado_sensores)
        grp_individual.setLayout(lay_ind)
        lay_s.addWidget(grp_individual, stretch=1)

        self.lbl_estado_sensores, self.progreso_sensores = self._estado_y_progreso(
            "Estado: esperando una sesión activa."
        )
        lay_s.addWidget(self.lbl_estado_sensores)
        lay_s.addWidget(self.progreso_sensores)

        grp_combinado = QGroupBox("B. Evaluación combinada (todos los sensores a la vez)")
        lay_com = QVBoxLayout()
        self.tabla_combinada = QTableWidget(0, 4)
        self.tabla_combinada.setHorizontalHeaderLabels(
            [
                "Sensores desconectados",
                "Error (MAE)",
                "Subida del error ↑",
                "Features eliminadas",
            ]
        )
        self.tabla_combinada.horizontalHeaderItem(1).setToolTip(tooltip("mae"))
        self.tabla_combinada.horizontalHeaderItem(2).setToolTip(tooltip("delta"))
        self.tabla_combinada.horizontalHeader().setStretchLastSection(True)
        self.tabla_combinada.setMaximumHeight(90)
        lay_com.addWidget(self.tabla_combinada)
        self.lbl_resultado_combinado = QLabel(
            "Sin cálculo combinado todavía. Este resultado no se atribuye a cada sensor."
        )
        self.lbl_resultado_combinado.setWordWrap(True)
        self.lbl_resultado_combinado.setStyleSheet(f"color: {TEXTO_SUAVE}; font-size: 11px;")
        lay_com.addWidget(self.lbl_resultado_combinado)
        grp_combinado.setLayout(lay_com)
        lay_s.addWidget(grp_combinado)

        grp_sensores.setLayout(lay_s)
        layout.addWidget(grp_sensores)

        layout.addStretch()

    @staticmethod
    def _estado_y_progreso(texto: str) -> tuple[QLabel, QProgressBar]:
        etiqueta = QLabel(texto)
        etiqueta.setWordWrap(True)
        progreso = QProgressBar()
        progreso.setRange(0, 0)  # indeterminado: el cálculo corre en el backend
        progreso.setMaximumHeight(8)
        progreso.setTextVisible(False)
        progreso.hide()
        return etiqueta, progreso

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_snr.clicked.connect(self._calcular_snr)
        self.btn_anadir.clicked.connect(self._anadir_sensor)
        self.btn_quitar.clicked.connect(self._quitar_sensor)
        self.btn_sensores.clicked.connect(self._calcular_sensores)

        self.api.robustez_recibida.connect(self._dibujar_snr)
        self.api.error_robustez.connect(self._mostrar_error_snr)
        self.api.sensores_recibidos.connect(self._tabla_sensores)
        self.api.error_sensores.connect(self._mostrar_error_sensores)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        # Incluye ruido por encima de la señal (SNR negativo): el backend ya
        # admite cualquier valor y el control permite hasta -20 dB.
        self._estado("snr", "Calculando la referencia (barrido de SNR)…")
        self.api.robustez(snr_db=[-10.0, 0.0, 10.0, 20.0, 30.0, 40.0])
        self._estado("sensores", "Calculando el error base sin fallos…")
        self.api.sensores(modo="individual")

    def _estado(self, cual: str, mensaje: str, *, error: bool = False) -> None:
        etiqueta = self.lbl_estado_snr if cual == "snr" else self.lbl_estado_sensores
        progreso = self.progreso_snr if cual == "snr" else self.progreso_sensores
        boton = self.btn_snr if cual == "snr" else self.btn_sensores
        etiqueta.setText(mensaje)
        color = ERROR if error else (EXITO if "Completado" in mensaje else TEXTO)
        etiqueta.setStyleSheet(f"color: {color};")
        procesando = "Calculando" in mensaje
        progreso.setVisible(procesando)
        boton.setEnabled(not procesando)

    def _calcular_snr(self) -> None:
        valor = float(self.spin_snr.value())
        self._snr_solicitado = valor
        self._estado(
            "snr",
            f"Calculando error con SNR = {valor:g} dB. La gráfica anterior se conserva.",
        )
        self.api.robustez(snr_db=[valor])

    def _dibujar_snr(self, datos: dict) -> None:
        snr_db = datos.get("snr_db", [])
        mae = datos.get("mae", [])
        if snr_db and mae:
            for nivel, error in zip(snr_db, mae):
                try:
                    self._snr_puntos[float(nivel)] = float(error)
                except (TypeError, ValueError):
                    continue

        niveles = sorted(self._snr_puntos)
        errores = [self._snr_puntos[n] for n in niveles]
        self.curva_snr.setData(niveles, errores)
        if self._snr_solicitado in self._snr_puntos:
            self.punto_snr.setData(
                [self._snr_solicitado], [self._snr_puntos[self._snr_solicitado]]
            )
            self.punto_snr.show()
        self._llenar_tabla_snr(niveles, errores)

        if niveles and errores:
            minimo, maximo = min(niveles), max(niveles)
            x_ctx = niveles
            if maximo <= minimo:
                x_ctx = [minimo - 5.0, maximo + 5.0]
            y_ctx = errores if maximo > minimo else [errores[0], errores[0]]
            self._cursor.establecer_datos(
                x_ctx,
                {"MAE": y_ctx},
                formato_x=lambda x, _i: f"SNR = {x:g} dB",
            )
            self.contexto.establecer_datos(
                x_ctx,
                y_ctx,
                unidad="dB",
                y_limites=limites_visualizacion(errores),
            )
            self.grafico_snr.setTitle("Error del modelo frente al ruido (SNR)")
        self._estado(
            "snr",
            f"Completado: {len(niveles)} niveles de ruido evaluados. "
            "Compara el MAE de cada fila; menor es mejor.",
        )

    def _llenar_tabla_snr(self, niveles: list[float], errores: list[float]) -> None:
        self.tabla_snr.setRowCount(0)
        if not errores:
            return
        mejor, peor = min(errores), max(errores)
        for nivel, error in zip(niveles, errores):
            fila = self.tabla_snr.rowCount()
            self.tabla_snr.insertRow(fila)
            self.tabla_snr.setItem(fila, 0, QTableWidgetItem(f"{nivel:g}"))
            self.tabla_snr.setItem(fila, 1, QTableWidgetItem(f"{error:g}"))
            if mejor == peor:
                lectura = "referencia"
            elif error == mejor:
                lectura = "menor error"
            elif error == peor:
                lectura = "mayor error"
            else:
                lectura = "intermedio"
            celda = QTableWidgetItem(lectura)
            if error == mejor and mejor != peor:
                celda.setForeground(QColor(EXITO))
            elif error == peor and mejor != peor:
                celda.setForeground(QColor(ERROR))
            self.tabla_snr.setItem(fila, 2, celda)

    def _encuadrar_snr(self) -> None:
        self.contexto._encuadrar()

    def _mostrar_error_snr(self, mensaje: str) -> None:
        # No se borra la curva: el usuario debe poder seguir consultando los
        # resultados anteriores mientras corrige el nivel de ruido.
        self._estado(
            "snr",
            f"Error al calcular: {error_amigable(mensaje)}. "
            "La gráfica y la tabla anteriores se conservan.",
            error=True,
        )

    def _anadir_sensor(self) -> None:
        canal = self.combo_sensor.currentText()
        rueda = self.combo_rueda.currentText()
        rueda = "" if rueda == "todas" else rueda
        for i in range(self.tabla_seleccion.rowCount()):
            if (self.tabla_seleccion.item(i, 0).text() == canal
                    and self.tabla_seleccion.item(i, 1).text() == rueda):
                return
        fila = self.tabla_seleccion.rowCount()
        self.tabla_seleccion.insertRow(fila)
        self.tabla_seleccion.setItem(fila, 0, QTableWidgetItem(canal))
        self.tabla_seleccion.setItem(fila, 1, QTableWidgetItem(rueda))

    def _quitar_sensor(self) -> None:
        fila = self.tabla_seleccion.currentRow()
        if fila >= 0:
            self.tabla_seleccion.removeRow(fila)

    def _sensores_seleccionados(self) -> list[dict]:
        caidos: list[dict] = []
        for i in range(self.tabla_seleccion.rowCount()):
            canal = self.tabla_seleccion.item(i, 0).text()
            rueda = self.tabla_seleccion.item(i, 1).text() or None
            caidos.append({"canal": canal, "rueda": rueda})
        return caidos

    def _calcular_sensores(self) -> None:
        caidos = self._sensores_seleccionados()
        modo = str(self.combo_modo_sensores.currentData())
        self._modo_sensores_solicitado = modo
        etiqueta = "individual" if modo == "individual" else "combinada"
        self._estado(
            "sensores",
            f"Calculando evaluación {etiqueta} de {len(caidos)} sensor(es)…",
        )
        self.api.sensores(caidos=caidos, modo=modo)

    @staticmethod
    def _numero(valor, defecto: str = "?") -> str:
        try:
            return f"{float(valor):.4g}"
        except (TypeError, ValueError):
            return str(valor if valor is not None else defecto)

    @staticmethod
    def _nombre_corto(entrada: dict) -> str:
        nombres = {
            "wheel_slip": "slip",
            "temp_core_c": "temp",
            "wheel_load_n": "carga",
            "pressure_psi": "presión",
            "speed_kmh": "velocidad",
            "throttle": "acelerador",
            "brake": "freno",
            "steering": "dirección",
        }
        canal = str(entrada.get("canal", "?"))
        rueda = str(entrada.get("rueda") or "").upper()
        return f"{nombres.get(canal, canal)} {rueda}".strip()

    @staticmethod
    def _entradas(fila: dict) -> list[dict]:
        entradas = fila.get("caidos") or []
        return entradas if isinstance(entradas, list) else []

    @staticmethod
    def _resultado_legado(datos: dict) -> dict:
        """Adapta respuestas antiguas sin ``modo``/``resultados``."""
        return {
            "caidos": datos.get("caidos") or [],
            "columnas_quitadas": datos.get("columnas_quitadas") or [],
            "n_features": datos.get("n_features", "?"),
            "mae": datos.get("mae", "?"),
            "delta": datos.get("delta", "?"),
            "delta_rel": datos.get("delta_rel"),
            "mae_kalman": datos.get("mae_kalman"),
            "metricas": datos.get("metricas") or {},
            "error": None,
        }

    def _limpiar_barras(self) -> None:
        if self._barras_ablacion is not None:
            self.grafico_ablacion.removeItem(self._barras_ablacion)
            self._barras_ablacion = None
        self.grafico_ablacion.getPlotItem().getAxis("bottom").setTicks([[]])
        self.grafico_ablacion.setTitle("Sensibilidad individual (sin datos)")

    def _dibujar_barras_ablacion(self, filas: list[dict]) -> None:
        self._limpiar_barras()
        validas: list[tuple[str, float]] = []
        for fila in filas:
            if fila.get("error"):
                continue
            try:
                delta = float(fila["delta"])
            except (KeyError, TypeError, ValueError):
                continue
            entradas = self._entradas(fila)
            nombre = self._nombre_corto(entradas[0]) if entradas else "sensor"
            validas.append((nombre, delta))
        if not validas:
            return
        x = list(range(len(validas)))
        alturas = [delta for _, delta in validas]
        self._barras_ablacion = pg.BarGraphItem(
            x=x, height=alturas, width=0.6, brush=ACENTO
        )
        self.grafico_ablacion.addItem(self._barras_ablacion)
        self.grafico_ablacion.getPlotItem().getAxis("bottom").setTicks(
            [[(i, nombre) for i, (nombre, _) in enumerate(validas)]]
        )
        self.grafico_ablacion.setXRange(-0.7, len(validas) - 0.3, padding=0.02)
        self.grafico_ablacion.setYRange(
            min(0.0, min(alturas)), max(0.0, max(alturas)), padding=0.15
        )
        self.grafico_ablacion.setTitle(
            "Subida del error por sensor (de mayor a menor)"
        )

    def _tabla_sensores(self, datos: dict) -> None:
        modo = datos.get("modo")
        resultados = datos.get("resultados")
        if modo is None and resultados is None:
            modo = "combinado"
            resultados = [self._resultado_legado(datos)]
        if not isinstance(resultados, list):
            resultados = []
        base = self._numero(datos.get("mae_base", datos.get("mae")))

        if not resultados:
            self.tabla_sensores.setRowCount(0)
            self.tabla_combinada.setRowCount(0)
            self._limpiar_barras()
            self.lbl_sensores.setText(f"Error sin fallos: {base}")
            self.lbl_resultado_sensores.setText("Sin cálculo individual todavía.")
            self.lbl_resultado_combinado.setText(
                "Sin cálculo combinado todavía. Este resultado no se atribuye a cada sensor."
            )
            self._estado(
                "sensores", "Completado: error base disponible para comparar."
            )
            return

        if modo == "individual":
            self._mostrar_individual(resultados, base)
        else:
            self._mostrar_combinado(resultados[0], base)

    def _mostrar_individual(self, resultados: list[dict], base: str) -> None:
        filas = [f for f in resultados if self._entradas(f)]

        def _orden(fila: dict):
            try:
                return (0, -float(fila.get("delta")))
            except (TypeError, ValueError):
                return (1, 0.0)

        filas.sort(key=_orden)
        self.tabla_sensores.setRowCount(0)
        for fila in filas:
            entrada = self._entradas(fila)[0]
            fila_tabla = self.tabla_sensores.rowCount()
            self.tabla_sensores.insertRow(fila_tabla)
            quitadas = fila.get("columnas_quitadas") or []
            resumen = ", ".join(str(c) for c in quitadas[:3]) or "ninguna"
            if len(quitadas) > 3:
                resumen += f" … (+{len(quitadas) - 3})"
            celdas = (
                str(entrada.get("canal", "?")),
                str(entrada.get("rueda") or ""),
                "?" if fila.get("error") else self._numero(fila.get("mae")),
                self._numero(fila.get("delta")),
                resumen,
            )
            for columna, texto in enumerate(celdas):
                celda = QTableWidgetItem(texto)
                if fila.get("error") and columna >= 2:
                    celda.setForeground(QColor(ERROR))
                self.tabla_sensores.setItem(fila_tabla, columna, celda)

        self.lbl_sensores.setText(
            f"Error sin fallos: {base} | {len(filas)} sensor(es) evaluados "
            "por separado | Ordenados por subida del error."
        )
        lineas = []
        for fila in filas[:3]:
            entrada = self._entradas(fila)[0]
            if fila.get("error"):
                lineas.append(f"{self._nombre_corto(entrada)}: {fila['error']}")
            else:
                lineas.append(
                    f"{self._nombre_corto(entrada)}: MAE {self._numero(fila.get('mae'))} "
                    f"· Subida: ↑ {self._numero(fila.get('delta'))}"
                )
        lineas.append(
            "La subida mide sensibilidad del modelo a perder esa información; "
            "no demuestra importancia física ni causal del sensor."
        )
        self.lbl_resultado_sensores.setText("\n".join(lineas))
        self._dibujar_barras_ablacion(filas)
        self._estado(
            "sensores",
            "Completado: evaluación individual con un MAE propio por sensor.",
        )

    def _mostrar_combinado(self, fila: dict, base: str) -> None:
        nombres = ", ".join(
            self._nombre_corto(entrada) for entrada in self._entradas(fila)
        ) or "ninguno"
        quitadas = fila.get("columnas_quitadas") or []
        resumen = ", ".join(str(c) for c in quitadas[:4]) or "ninguna"
        if len(quitadas) > 4:
            resumen += f" … (+{len(quitadas) - 4})"
        self.tabla_combinada.setRowCount(0)
        self.tabla_combinada.insertRow(0)
        celdas = (
            nombres,
            self._numero(fila.get("mae")),
            self._numero(fila.get("delta")),
            resumen,
        )
        for columna, texto in enumerate(celdas):
            self.tabla_combinada.setItem(0, columna, QTableWidgetItem(texto))

        lineas = [
            f"MAE sin fallos: {base} · MAE del conjunto: "
            f"{self._numero(fila.get('mae'))}",
            f"Subida del conjunto: ↑ {self._numero(fila.get('delta'))}",
        ]
        if fila.get("delta_rel") is not None:
            try:
                lineas.append(
                    f"Subida relativa: {float(fila['delta_rel']) * 100:.1f} %"
                )
            except (TypeError, ValueError):
                pass
        if fila.get("mae_kalman_base") is not None:
            lineas.append(
                f"MAE tras Kalman: {self._numero(fila.get('mae_kalman_base'))} → "
                f"{self._numero(fila.get('mae_kalman'))}"
            )
        lineas.append(
            "Este resultado corresponde al conjunto de sensores; "
            "no se atribuye a cada fila individual."
        )
        self.lbl_resultado_combinado.setText("\n".join(lineas))
        self.lbl_sensores.setText(
            "El resultado combinado se muestra en la sección B; la tabla "
            "individual conserva su último cálculo."
        )
        self._estado(
            "sensores",
            f"Completado: evaluación combinada de {len(self._entradas(fila))} sensor(es).",
        )

    def _mostrar_error_sensores(self, mensaje: str) -> None:
        self.lbl_sensores.setText(error_amigable(mensaje))
        self._estado(
            "sensores",
            f"Error al calcular: {error_amigable(mensaje)}. "
            "La tabla anterior se conserva. Revisa la sesión y los sensores.",
            error=True,
        )
