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
    "<b>Fallo de sensores</b><br>"
    "Objetivo: comprobar qué pasa si un canal deja de medir. Entrada: la "
    "misma sesión y las features derivadas del sensor elegido. Se vuelve a "
    "entrenar y evaluar Ridge sin esas columnas. Resultado: MAE base, MAE con "
    "el fallo y su diferencia. Interpretación: una subida del error indica "
    "que ese canal aporta información al modelo; una subida nula significa "
    "que sus features no influyen."
)


class VistaRobustez(VistaBase):
    """Panel de robustez: MAE vs SNR y fallo de sensores."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._snr_puntos: dict[float, float] = {}
        self._snr_solicitado: float | None = None
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

        grp_sensores = QGroupBox(
            "Simulador de fallo de sensores (error al desconectar cada canal)"
        )
        lay_s = QVBoxLayout()

        lay_sel = QHBoxLayout()
        self.combo_sensor = QComboBox()
        self.combo_sensor.addItems(SENSORES)
        self.combo_rueda = QComboBox()
        self.combo_rueda.addItems(RUEDAS)
        self.btn_anadir = QPushButton("Anyadir sensor")
        self.btn_quitar = QPushButton("Quitar seleccionado")
        lay_sel.addWidget(QLabel("Canal:"))
        lay_sel.addWidget(self.combo_sensor)
        lay_sel.addWidget(QLabel("Rueda:"))
        lay_sel.addWidget(self.combo_rueda)
        lay_sel.addWidget(self.btn_anadir)
        lay_sel.addWidget(self.btn_quitar)
        lay_sel.addStretch()
        lay_s.addLayout(lay_sel)

        self.tabla_sensores = QTableWidget(0, 4)
        self.tabla_sensores.setHorizontalHeaderLabels(
            ["Canal", "Rueda", "Error (MAE)", "Subida del error ↑"]
        )
        self.tabla_sensores.horizontalHeaderItem(2).setToolTip(tooltip("mae"))
        self.tabla_sensores.horizontalHeaderItem(3).setToolTip(tooltip("delta"))
        self.tabla_sensores.horizontalHeader().setStretchLastSection(True)
        lay_s.addWidget(self.tabla_sensores)

        nota_delta = QLabel(
            "La flecha ↑ significa que el error sube al apagar ese sensor."
        )
        nota_delta.setWordWrap(True)
        nota_delta.setToolTip(tooltip("delta"))
        lay_s.addWidget(nota_delta)

        self.lbl_sensores = QLabel(
            "Añade sensores a la tabla y pulsa «Calcular error por sensor»."
        )
        self.lbl_sensores.setWordWrap(True)
        lay_s.addWidget(self.lbl_sensores)

        self.lbl_estado_sensores, self.progreso_sensores = self._estado_y_progreso(
            "Estado: esperando una sesión activa."
        )
        lay_s.addWidget(self.lbl_estado_sensores)
        lay_s.addWidget(self.progreso_sensores)

        self.lbl_resultado_sensores = QLabel("Sin cálculo de sensores todavía.")
        self.lbl_resultado_sensores.setWordWrap(True)
        lay_s.addWidget(self.lbl_resultado_sensores)

        self.btn_sensores = QPushButton("Calcular error por sensor")
        self.btn_sensores.setToolTip(
            "Recalcula el MAE sin las features de los sensores marcados. "
            "La tabla y los resultados anteriores se mantienen."
        )
        lay_s.addWidget(self.btn_sensores)
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
        self.api.sensores()

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
        for i in range(self.tabla_sensores.rowCount()):
            if (self.tabla_sensores.item(i, 0).text() == canal
                    and self.tabla_sensores.item(i, 1).text() == rueda):
                return
        fila = self.tabla_sensores.rowCount()
        self.tabla_sensores.insertRow(fila)
        self.tabla_sensores.setItem(fila, 0, QTableWidgetItem(canal))
        self.tabla_sensores.setItem(fila, 1, QTableWidgetItem(rueda))
        self.tabla_sensores.setItem(fila, 2, QTableWidgetItem("?"))
        self.tabla_sensores.setItem(fila, 3, QTableWidgetItem("?"))

    def _quitar_sensor(self) -> None:
        fila = self.tabla_sensores.currentRow()
        if fila >= 0:
            self.tabla_sensores.removeRow(fila)

    def _sensores_seleccionados(self) -> list[dict]:
        caidos: list[dict] = []
        for i in range(self.tabla_sensores.rowCount()):
            canal = self.tabla_sensores.item(i, 0).text()
            rueda = self.tabla_sensores.item(i, 1).text() or None
            caidos.append({"canal": canal, "rueda": rueda})
        return caidos

    def _calcular_sensores(self) -> None:
        caidos = self._sensores_seleccionados()
        self._estado("sensores", "Calculando error por sensor…")
        if caidos:
            self.api.sensores(caidos=caidos)
        else:
            self.api.sensores()

    def _tabla_sensores(self, datos: dict) -> None:
        caidos = datos.get("caidos", [])
        if not caidos:
            base = datos.get("mae_base", datos.get("mae", "?"))
            self.lbl_sensores.setText(f"Error sin fallos: {base}")
            self._estado(
                "sensores", "Completado: error base disponible para comparar."
            )
            return

        # El backend devuelve un unico MAE para el conjunto de sensores caidos;
        # se refleja en todas las filas seleccionadas y se anade el delta.
        mae = datos.get("mae", "?")
        delta = datos.get("delta", "?")
        for entrada in caidos:
            canal = entrada.get("canal", "?")
            rueda = entrada.get("rueda") or ""
            for i in range(self.tabla_sensores.rowCount()):
                if (self.tabla_sensores.item(i, 0).text() == canal
                        and self.tabla_sensores.item(i, 1).text() == rueda):
                    self.tabla_sensores.setItem(i, 2, QTableWidgetItem(str(mae)))
                    self.tabla_sensores.setItem(i, 3, QTableWidgetItem(str(delta)))
        base = datos.get("mae_base", "?")
        self.lbl_sensores.setText(
            f"Error sin fallos: {base} | Error con fallo: {mae} | "
            f"Subida: ↑ {delta}"
        )
        self._mostrar_resultado_sensores(datos)
        self._estado(
            "sensores",
            "Completado: compara la subida del error de cada sensor.",
        )

    def _mostrar_resultado_sensores(self, datos: dict) -> None:
        """Presenta solo claves que el backend ya devuelve."""
        lineas = [
            f"MAE sin fallos: {datos.get('mae_base', '?')} · "
            f"MAE con fallo: {datos.get('mae', '?')}",
            f"Subida del error: {datos.get('delta', '?')}",
        ]
        if datos.get("delta_rel") is not None:
            lineas.append(
                f"Subida relativa: {float(datos['delta_rel']) * 100:.1f} %"
            )
        if datos.get("mae_kalman_base") is not None:
            lineas.append(
                f"MAE tras Kalman: {datos.get('mae_kalman_base')} → "
                f"{datos.get('mae_kalman', '?')}"
            )
        if datos.get("n_features_base") is not None:
            lineas.append(
                f"Features: {datos.get('n_features_base')} → "
                f"{datos.get('n_features', '?')} después del fallo"
            )
        quitadas = datos.get("columnas_quitadas") or []
        if quitadas:
            nombres = ", ".join(str(c) for c in quitadas[:6])
            if len(quitadas) > 6:
                nombres += f" … (+{len(quitadas) - 6})"
            lineas.append(f"Features eliminadas: {nombres}")
        self.lbl_resultado_sensores.setText("\n".join(lineas))

    def _mostrar_error_sensores(self, mensaje: str) -> None:
        self.lbl_sensores.setText(error_amigable(mensaje))
        self._estado(
            "sensores",
            f"Error al calcular: {error_amigable(mensaje)}. "
            "La tabla anterior se conserva. Revisa la sesión y los sensores.",
            error=True,
        )
