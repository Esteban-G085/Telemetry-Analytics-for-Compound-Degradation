"""Vista de captura en vivo (Etapa 3).

Endpoints REST:
    POST /api/vivo/iniciar
    POST /api/vivo/detener
    GET  /api/vivo/estado
    GET  /api/vivo/ventana
    GET  /api/vivo/sesiones
    GET  /api/vivo/layout

WebSocket:
    /api/vivo/stream  (empuja JSON tipo "vivo" cada ~100 ms con estado + ventana)

Permite iniciar/detener la captura (modo seco o AC), ver el estado del motor
y el osciloscopio en tiempo real con los datos del WebSocket.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaVivo(VistaBase):
    """Panel de captura en vivo."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._construir_ui()
        self._conectar_senales()

        self._timer_estado = QTimer(self)
        self._timer_estado.timeout.connect(self.api.vivo_estado)

        self.api.vivo_sesiones()
        self.api.vivo_layout()

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Muestra lo que ocurre ahora mismo. Puedes capturar desde un CSV "
            "(modo seco) o desde Assetto Corsa si está en pista. Al iniciar, "
            "el osciloscopio se llena con los datos del WebSocket."
        )

        grp_control = QGroupBox("Control de captura en vivo")
        lay = QHBoxLayout()

        self.combo_fuente = QComboBox()
        self.combo_fuente.addItems(["seco (CSV)", "ac (Assetto Corsa)"])
        lay.addWidget(QLabel("Fuente:"))
        lay.addWidget(self.combo_fuente)

        self.combo_archivo = QComboBox()
        self.combo_archivo.setMinimumWidth(220)
        lay.addWidget(QLabel("Archivo (modo seco):"))
        lay.addWidget(self.combo_archivo)

        self.btn_iniciar = QPushButton("Iniciar captura")
        self.btn_detener = QPushButton("Detener captura")
        self.btn_detener.setEnabled(False)
        lay.addWidget(self.btn_iniciar)
        lay.addWidget(self.btn_detener)
        lay.addStretch()
        grp_control.setLayout(lay)
        layout.addWidget(grp_control)

        grp_estado = QGroupBox("Estado del motor vivo")
        lay_e = QVBoxLayout()

        self.lbl_estado = QLabel("Esperando datos...")
        self.lbl_estado.setWordWrap(True)
        lay_e.addWidget(self.lbl_estado)

        self.lbl_diagnostico = QLabel("")
        self.lbl_diagnostico.setWordWrap(True)
        lay_e.addWidget(self.lbl_diagnostico)

        self.lbl_layout = QLabel("AC: consultando memoria compartida...")
        self.lbl_layout.setWordWrap(True)
        lay_e.addWidget(self.lbl_layout)
        grp_estado.setLayout(lay_e)
        layout.addWidget(grp_estado)

        grp_osc = QGroupBox(
            "Osciloscopio en tiempo real (WebSocket /api/vivo/stream)"
        )
        lay_o = QVBoxLayout()
        self.grafico = pg.PlotWidget()
        self.grafico.setLabel("left", "Valor")
        self.grafico.setLabel("bottom", "Muestra")
        self.grafico.showGrid(x=True, y=True)
        self.grafico.setTitle("Esperando datos del WebSocket...")
        self.curva = self.grafico.plot(pen=pg.mkPen("#00bfa5", width=2))
        self.grafico.setMinimumHeight(300)
        lay_o.addWidget(self.grafico)
        grp_osc.setLayout(lay_o)
        layout.addWidget(grp_osc, stretch=1)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_iniciar.clicked.connect(self._iniciar_captura)
        self.btn_detener.clicked.connect(self._detener_captura)
        self.combo_fuente.currentTextChanged.connect(self._on_cambio_fuente)

        self.api.vivo_iniciado.connect(self._on_iniciado)
        self.api.error_vivo_iniciar.connect(self._on_error_iniciar)
        self.api.vivo_detenido.connect(self._on_detenido)
        self.api.error_vivo_detener.connect(self._on_error_detener)
        self.api.vivo_estado_recibido.connect(self._mostrar_estado)
        self.api.error_vivo_estado.connect(self._on_error_estado)

        self.api.estado_vivo.connect(self._on_estado_ws_vivo)
        self.api.mensaje_vivo.connect(self._on_mensaje_vivo)

        # Estas dos senales existian en el cliente pero nadie las conectaba:
        # por eso el combo de archivos y el diagnostico de AC quedaban vacios.
        self.api.vivo_sesiones_recibidas.connect(self._llenar_archivos)
        self.api.error_vivo_sesiones.connect(self._mostrar_error_archivos)
        self.api.vivo_layout_recibido.connect(self._mostrar_layout)
        self.api.error_vivo_layout.connect(self._mostrar_error_layout)

    # ------------------------------------------------------------------ Slots - control de captura
    def _on_cambio_fuente(self, texto: str) -> None:
        es_seco = texto.startswith("seco")
        self.combo_archivo.setEnabled(es_seco)

    def _iniciar_captura(self) -> None:
        fuente = (
            "seco" if self.combo_fuente.currentText().startswith("seco") else "ac"
        )
        archivo = self.combo_archivo.currentText() or None
        if archivo == "(sin capturas)":
            archivo = None
        # Conectar antes de arrancar para no perder las primeras tramas.
        self.api.conectar_vivo()
        self.api.vivo_iniciar(fuente=fuente, archivo=archivo)

    def _detener_captura(self) -> None:
        self.api.vivo_detener()
        self.api.desconectar_vivo()
        self._timer_estado.stop()

    def _on_iniciado(self, datos: dict) -> None:
        self.btn_iniciar.setEnabled(False)
        self.btn_detener.setEnabled(True)
        self.lbl_estado.setText("Captura iniciada.")
        self._timer_estado.start(1000)

    def _on_error_iniciar(self, mensaje: str) -> None:
        self.api.desconectar_vivo()
        self.lbl_estado.setText(f"Error al iniciar: {error_amigable(mensaje)}")

    def _on_detenido(self, datos: dict) -> None:
        self.btn_iniciar.setEnabled(True)
        self.btn_detener.setEnabled(False)
        self.lbl_estado.setText("Captura detenida.")
        self._timer_estado.stop()

    def _on_error_detener(self, mensaje: str) -> None:
        self.lbl_estado.setText(f"Error al detener: {mensaje}")

    # ------------------------------------------------------------------ Slots - estado REST
    def _mostrar_estado(self, datos: dict) -> None:
        muestras = datos.get("muestras", 0)
        vuelta = datos.get("vuelta", "-")
        degradacion = datos.get("degradacion", "-")
        prediccion = datos.get("prediccion", "-")
        self.lbl_estado.setText(
            f"Muestras: {muestras} | Vuelta: {vuelta} | "
            f"Degradacion: {degradacion} | Prediccion: {prediccion}"
        )
        paquetes = datos.get("paquetes_perdidos", 0)
        fs = datos.get("fs_medida", 0)
        errores = datos.get("errores_subs", 0)
        self.lbl_diagnostico.setText(
            f"Paquetes perdidos: {paquetes} | fs medida: {fs} Hz | Errores: {errores}"
        )

    def _on_error_estado(self, mensaje: str) -> None:
        self.lbl_estado.setText(f"Error estado: {mensaje}")

    # ------------------------------------------------------------------ Slots - WebSocket de vivo
    def _on_estado_ws_vivo(self, estado: str) -> None:
        if estado == "conectado":
            self.grafico.setTitle("Osciloscopio en vivo - recibiendo datos...")
            self.api.vivo_ventana(
                n=500,
                canales=["speed_kmh", "throttle", "brake"],
            )
        elif estado == "desconectado":
            self.grafico.setTitle("WebSocket de vivo: desconectado")

    def _on_mensaje_vivo(self, datos: dict) -> None:
        if datos.get("tipo") != "vivo":
            return

        ventana = datos.get("ventana", {})
        series = ventana.get("series", {})
        if series:
            nombre = next(iter(series))
            valores = series[nombre]
            if valores:
                self.curva.setData(valores)
                self.grafico.setTitle(f"Osciloscopio en vivo - {nombre}")

    def _llenar_archivos(self, sesiones: list) -> None:
        # GET /api/vivo/sesiones devuelve [{"nombre": ..., "kb": ..., ...}],
        # no una lista de strings.
        nombres = []
        for entrada in sesiones if isinstance(sesiones, list) else []:
            nombre = entrada.get("nombre") if isinstance(entrada, dict) else str(entrada)
            if nombre and nombre not in nombres:
                nombres.append(nombre)
        self.combo_archivo.blockSignals(True)
        self.combo_archivo.clear()
        self.combo_archivo.addItems(nombres or ["(sin capturas)"])
        if "sim_test_99.csv" in nombres:
            self.combo_archivo.setCurrentText("sim_test_99.csv")
        self.combo_archivo.blockSignals(False)

    def _mostrar_error_archivos(self, mensaje: str) -> None:
        self.lbl_layout.setText(f"Archivos: {error_amigable(mensaje)}")

    def _mostrar_layout(self, datos: dict) -> None:
        disponible = bool(datos.get("disponible", False))
        layout_ok = bool(datos.get("layout_ok", False))
        estado = "si" if disponible else "no"
        detalle = "" if not datos.get("error") else f" | {datos['error']}"
        self.lbl_layout.setText(
            f"AC publicando: {estado} | layout valido: {'si' if layout_ok else 'no'}"
            f"{detalle}"
        )

    def _mostrar_error_layout(self, mensaje: str) -> None:
        self.lbl_layout.setText(f"AC: {error_amigable(mensaje)}")
