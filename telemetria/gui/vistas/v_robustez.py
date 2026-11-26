"""Vista de robustez: MAE vs ruido inyectado y simulador de fallo de sensores.

Endpoints:
    POST /api/modelos/robustez   (MAE de Ridge vs SNR)
    POST /api/modelos/sensores   (MAE al desconectar canales)

El simulador usa las familias de canal que entiende el backend
(``analisis.MAPA_SENSOR``), no nombres de columna inventados por la GUI.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.glosario import tooltip
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


class VistaRobustez(VistaBase):
    """Panel de robustez: MAE vs SNR y fallo de sensores."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._construir_ui()
        self._conectar_senales()
        # Robustez y sensores necesitan una sesion activa.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Comprueba qué pasa cuando llega ruido o falla un sensor. SNR bajo "
            "significa más ruido; un MAE alto significa peor predicción. La "
            "columna <b>Subida del error</b> cuenta cuánto empeora al apagar "
            "ese canal."
        )

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
        lay.addWidget(self.btn_snr)
        lay.addStretch()
        grp_snr.setLayout(lay)
        layout.addWidget(grp_snr)

        self.grafico_snr = pg.PlotWidget()
        self.grafico_snr.setLabel("left", "Error medio (MAE)")
        self.grafico_snr.setLabel("bottom", "Ruido añadido (SNR dB)")
        self.grafico_snr.showGrid(x=True, y=True)
        self.grafico_snr.setTitle("Error del modelo frente al ruido (sin datos)")
        self.curva_snr = self.grafico_snr.plot(
            pen=pg.mkPen("b", width=2), symbol="o"
        )
        self.grafico_snr.setMinimumHeight(300)

        grp_grafico = QGroupBox("Gráfico de error frente al ruido")
        lay_g = QVBoxLayout()
        lay_g.addWidget(self.grafico_snr)
        grp_grafico.setLayout(lay_g)
        layout.addWidget(grp_grafico, stretch=1)

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

        self.btn_sensores = QPushButton("Calcular error por sensor")
        lay_s.addWidget(self.btn_sensores)
        grp_sensores.setLayout(lay_s)
        layout.addWidget(grp_sensores)

        layout.addStretch()

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
        self.api.robustez(snr_db=[-10.0, 0.0, 10.0, 20.0, 30.0, 40.0])
        self.api.sensores()

    def _calcular_snr(self) -> None:
        self.api.robustez(snr_db=[self.spin_snr.value()])

    def _dibujar_snr(self, datos: dict) -> None:
        snr_db = datos.get("snr_db", [])
        mae = datos.get("mae", [])
        self.curva_snr.setData(snr_db, mae)
        self.grafico_snr.setTitle("Error del modelo frente al ruido (SNR)")

    def _mostrar_error_snr(self, mensaje: str) -> None:
        self.grafico_snr.setTitle(error_amigable(mensaje))

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
        if caidos:
            self.api.sensores(caidos=caidos)
        else:
            self.api.sensores()

    def _tabla_sensores(self, datos: dict) -> None:
        caidos = datos.get("caidos", [])
        if not caidos:
            base = datos.get("mae_base", datos.get("mae", "?"))
            self.lbl_sensores.setText(f"Error sin fallos: {base}")
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

    def _mostrar_error_sensores(self, mensaje: str) -> None:
        self.lbl_sensores.setText(error_amigable(mensaje))
