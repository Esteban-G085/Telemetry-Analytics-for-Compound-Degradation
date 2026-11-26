"""Vista de telemetria: canales disponibles, grafico y datos en tiempo real por WebSocket.

Endpoints REST:
    GET /api/telemetria/canales

WebSocket:
    /ws/telemetria  (mensajes JSON de control + tramas binarias Float32)

Usa pyqtgraph para el grafico (rápido para miles de puntos).
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaTelemetria(VistaBase):
    """Panel de telemetria con canales, grafico y area de mensajes WS."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._construir_ui()
        self._conectar_senales()
        # No pedir canales hasta que haya una sesion activa: la API responde
        # 409 y la pestaña se llenaria de errores antes de empezar.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Aquí ves las señales disponibles y los mensajes del WebSocket. "
            "El gráfico sigue una señal en vivo. Para ver varias señales de "
            "una vuelta grabada, usa la pestaña <b>Replay</b>."
        )

        # --- Grupo: canales ---
        grp_canales = QGroupBox("Canales disponibles")
        grp_canales.setObjectName("grupo_canales")
        lay_canales = QVBoxLayout()
        self.lbl_canales = QLabel("Cargando canales...")
        self.lbl_canales.setWordWrap(True)
        lay_canales.addWidget(self.lbl_canales)
        self.btn_refrescar_canales = QPushButton("Refrescar canales")
        self.btn_refrescar_canales.setToolTip(
            "Consulta GET /api/telemetria/canales para listar los canales "
            "disponibles en la sesion cargada."
        )
        lay_canales.addWidget(self.btn_refrescar_canales)
        grp_canales.setLayout(lay_canales)
        layout.addWidget(grp_canales)

        # --- Grupo: grafico ---
        self.grafico = pg.PlotWidget()
        self.grafico.setLabel("left", "Valor")
        self.grafico.setLabel("bottom", "Tiempo (muestra)")
        self.grafico.showGrid(x=True, y=True)
        self.grafico.setTitle("Telemetria (sin datos)")
        self.curva = self.grafico.plot(pen=pg.mkPen("c", width=2), name="Señal")
        self.grafico.setMinimumHeight(350)

        grp_grafico = QGroupBox("Grafico en tiempo real")
        grp_grafico.setObjectName("grupo_tiempo_real")
        lay_grafico = QVBoxLayout()
        lay_grafico.addWidget(self.grafico)
        grp_grafico.setLayout(lay_grafico)
        layout.addWidget(grp_grafico, stretch=1)

        # --- Grupo: mensajes del WebSocket ---
        grp_ws = QGroupBox("Mensajes del WebSocket (/ws/telemetria)")
        grp_ws.setObjectName("grupo_ws")
        lay_ws = QVBoxLayout()
        self.texto_ws = QTextEdit()
        self.texto_ws.setReadOnly(True)
        self.texto_ws.setMaximumHeight(140)
        self.texto_ws.setPlaceholderText("Los mensajes del WS aparecen aqui...")
        lay_ws.addWidget(self.texto_ws)
        grp_ws.setLayout(lay_ws)
        layout.addWidget(grp_ws)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_refrescar_canales.clicked.connect(self.api.canales)

        self.api.canales_recibidos.connect(self._mostrar_canales)
        self.api.error_canales.connect(self._mostrar_error_canales)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

        # WebSocket: estado y mensajes
        self.api.estado_telemetria.connect(self._on_estado_ws)
        self.api.mensaje_telemetria.connect(self._on_mensaje_ws)
        self.api.mensaje_binario_telemetria.connect(self._on_datos_binarios)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        """Una sesion nueva (o la inicial) hace faltar refrescar los canales."""
        self.api.canales()

    def _mostrar_canales(self, canales: dict) -> None:
        lista = canales.get("canales", [])
        if isinstance(lista, list):
            self.lbl_canales.setText("\n".join(lista) if lista else "Sin canales")
        else:
            self.lbl_canales.setText(str(lista))

    def _mostrar_error_canales(self, mensaje: str) -> None:
        self.lbl_canales.setText(error_amigable(mensaje))

    def _on_estado_ws(self, estado: str) -> None:
        self.texto_ws.append(f"[WS] {estado}")

    def _on_mensaje_ws(self, datos: dict) -> None:
        tipo = datos.get("tipo", "?")
        self.texto_ws.append(f"[WS] {tipo}: {datos}")
        # Limitar el texto a las últimas 50 líneas para no consumir memoria
        documento = self.texto_ws.document()
        if documento.blockCount() > 50:
            cursor = self.texto_ws.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deletePreviousChar()

    def _on_datos_binarios(self, datos: dict) -> None:
        """Dibuja la primera canal de una trama binaria recibida por WS."""
        filas = datos.get("filas", [])
        if filas:
            valores = filas[0].get("valores", [])
            canal = filas[0].get("canal", "?")
            if valores:
                self.curva.setData(valores)
                self.grafico.setTitle(f"Telemetria en vivo - {canal}")
        self.texto_ws.append(
            f"[WS binario] {datos.get('n_muestras', 0)} muestras x "
            f"{len(datos.get('canales', []))} canales"
        )
