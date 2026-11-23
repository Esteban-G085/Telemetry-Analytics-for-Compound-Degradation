"""Ventana principal de la aplicacion de escritorio.

QMainWindow con:
  * barra de estado que indica si el backend esta vivo,
  * pestañas (una por vista: sesiones, telemetria, espectro, prediccion,
    laboratorio, robustez, replay, vivo),
  * un panel superior de control de telemetria en vivo (conectar/desconectar WS),
  * estilos QSS para una apariencia pulida y profesional.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.paleta import (
    ACENTO,
    ACENTO_HOVER,
    ACENTO_PRESIONADO,
    BORDE,
    BORDE_SUAVE,
    ERROR,
    EXITO,
    FONDO,
    PAPEL,
    SELECCION_FONDO,
    SELECCION_TEXTO,
    TEXTO,
    TEXTO_DESACTIVADO,
    TEXTO_SUAVE,
    aplicar_paleta_clara,
)
from telemetria.gui.vistas import (
    VistaEspectro,
    VistaLaboratorio,
    VistaPrediccion,
    VistaRobustez,
    VistaReplay,
    VistaSesiones,
    VistaTelemetria,
    VistaVivo,
)

# --------------------------------------------------------------------------- Estilo QSS
# Una sola paleta clara (telemetria.gui.paleta) para Qt y pyqtgraph. No se
# hereda nada del tema del sistema: asi evitamos texto blanco sobre fondo claro.
ESTILO_APP = f"""
QMainWindow {{
    background-color: {FONDO};
}}
QTabWidget::pane {{
    border: 1px solid {BORDE};
    background: {PAPEL};
    border-top: none;
}}
QTabBar::tab {{
    background: {SELECCION_FONDO};
    color: {TEXTO};
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 12px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {PAPEL};
    color: {ACENTO};
    border-bottom: 2px solid {ACENTO};
    margin-bottom: -1px;
}}
QTabBar::tab:hover:!selected {{
    background: {BORDE_SUAVE};
}}
QGroupBox {{
    font-weight: 600;
    font-size: 12px;
    color: {TEXTO};
    border: 1px solid {BORDE};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 10px;
    background: {PAPEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px 0 6px;
    color: {TEXTO};
}}
QPushButton {{
    background-color: {ACENTO};
    color: {SELECCION_TEXTO};
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
    min-width: 90px;
}}
QPushButton:hover {{
    background-color: {ACENTO_HOVER};
}}
QPushButton:pressed {{
    background-color: {ACENTO_PRESIONADO};
}}
QPushButton:disabled {{
    background-color: {BORDE};
    color: {TEXTO_DESACTIVADO};
}}
QLabel {{
    color: {TEXTO};
    font-size: 12px;
}}
QTextEdit {{
    border: 1px solid {BORDE};
    border-radius: 6px;
    background: {PAPEL};
    color: {TEXTO};
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    padding: 6px;
}}
QSpinBox, QDoubleSpinBox, QComboBox {{
    border: 1px solid {BORDE};
    border-radius: 4px;
    padding: 4px 8px;
    background: {PAPEL};
    color: {TEXTO};
    min-height: 24px;
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACENTO};
}}
QComboBox QAbstractItemView {{
    background: {PAPEL};
    color: {TEXTO};
    border: 1px solid {BORDE};
    selection-background-color: {ACENTO};
    selection-color: {SELECCION_TEXTO};
}}
QMenu, QToolTip {{
    background: {PAPEL};
    color: {TEXTO};
    border: 1px solid {BORDE};
}}
QTableWidget {{
    border: 1px solid {BORDE};
    border-radius: 6px;
    background: {PAPEL};
    gridline-color: {BORDE_SUAVE};
}}
QHeaderView::section {{
    background: {SELECCION_FONDO};
    color: {TEXTO};
    padding: 6px;
    border: none;
    font-weight: 600;
    font-size: 11px;
}}
QScrollArea {{
    background: {FONDO};
    border: none;
}}
QStatusBar {{
    background: {SELECCION_FONDO};
    color: {TEXTO};
    border-top: 1px solid {BORDE};
    font-size: 11px;
}}
"""


class VentanaPrincipal(QMainWindow):
    """Ventana principal de Telemetry Analytics (escritorio nativo, PySide6)."""

    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()

        self.api = api or ApiClient()
        # Fijar la paleta antes de crear cualquier vista: cubre QPalette de Qt
        # (popups, tooltips) y el fondo/ejes de todos los graficos pyqtgraph.
        aplicar_paleta_clara(QApplication.instance())
        self.setWindowTitle("Telemetry Analytics - Escritorio (PySide6)")
        self.resize(1250, 850)
        self.setStyleSheet(ESTILO_APP)

        # Barra de estado
        self.lbl_estado = QLabel("Backend: consultando...")
        self.statusBar().addWidget(self.lbl_estado)

        # Temporizador para consultar salud periodicamente
        self._temporizador_salud = QTimer(self)
        self._temporizador_salud.timeout.connect(self.api.salud)
        self._temporizador_salud.start(5000)

        # ------------------------------------------------------------------ Central
        central = QWidget()
        lay_central = QVBoxLayout(central)
        lay_central.setContentsMargins(16, 12, 16, 12)
        lay_central.setSpacing(12)

        # Panel superior de control de telemetria en vivo
        panel_vivo = QHBoxLayout()
        panel_vivo.setContentsMargins(0, 0, 0, 8)

        self.btn_conectar = QPushButton("Conectar telemetria (WS)")
        self.btn_conectar.setToolTip(
            "Abre el WebSocket /ws/telemetria para recibir datos de control "
            "y tramas binarias en tiempo real."
        )
        self.btn_desconectar = QPushButton("Desconectar")
        self.btn_desconectar.setEnabled(False)
        self.btn_desconectar.setToolTip("Cierra el WebSocket de telemetria.")
        self.lbl_ws = QLabel("WebSocket: desconectado")
        self.lbl_ws.setStyleSheet(f"color: {ERROR}; font-weight: bold;")
        panel_vivo.addWidget(self.btn_conectar)
        panel_vivo.addWidget(self.btn_desconectar)
        panel_vivo.addWidget(self.lbl_ws)
        panel_vivo.addStretch()
        lay_central.addLayout(panel_vivo)

        # Barra de instrucciones para el usuario
        self.lbl_instrucciones = QLabel(
            "Tip: carga una sesion en la pestaña 'Sesiones', luego explora "
            "Espectro, Prediccion, Replay, etc. Usa 'Conectar telemetria (WS)' "
            "para recibir datos en tiempo real."
        )
        self.lbl_instrucciones.setWordWrap(True)
        self.lbl_instrucciones.setStyleSheet(f"color: {TEXTO_SUAVE}; font-style: italic; padding: 4px 0;")
        lay_central.addWidget(self.lbl_instrucciones)

        # Pestañas
        self.pestanas = QTabWidget()
        self.pestanas.setDocumentMode(True)
        self.pestanas.addTab(VistaSesiones(self.api), "Sesiones")
        self.pestanas.addTab(VistaTelemetria(self.api), "Telemetria")
        self.pestanas.addTab(VistaEspectro(self.api), "Espectro")
        self.pestanas.addTab(VistaPrediccion(self.api), "Prediccion")
        self.pestanas.addTab(VistaLaboratorio(self.api), "Laboratorio")
        self.pestanas.addTab(VistaRobustez(self.api), "Robustez")
        self.pestanas.addTab(VistaReplay(self.api), "Replay")
        self.pestanas.addTab(VistaVivo(self.api), "En vivo")
        lay_central.addWidget(self.pestanas)

        self.setCentralWidget(central)

        # ------------------------------------------------------------------ Senales
        self.btn_conectar.clicked.connect(self.api.conectar_telemetria)
        self.btn_desconectar.clicked.connect(self.api.desconectar_telemetria)

        self.api.salud_recibida.connect(self._on_salud)
        self.api.error_salud.connect(self._on_error_salud)
        self.api.estado_telemetria.connect(self._on_estado_ws)

        # Primeras consultas: salud y estado de sesion. El resto de vistas no
        # piden datos dependientes de la sesion hasta recibir sesion_activa.
        self.api.salud()
        self.api.sesion_activa()

    # ------------------------------------------------------------------ Slots
    def _on_salud(self, datos: dict) -> None:
        version = datos.get("version", "?")
        self.lbl_estado.setText(f"Backend: online (v{version})")
        self.lbl_estado.setStyleSheet(f"color: {EXITO}; font-weight: bold;")

    def _on_error_salud(self, mensaje: str) -> None:
        self.lbl_estado.setText(f"Backend: no responde ({mensaje})")
        self.lbl_estado.setStyleSheet(f"color: {ERROR}; font-weight: bold;")

    def _on_estado_ws(self, estado: str) -> None:
        self.lbl_ws.setText(f"WebSocket: {estado}")
        conectado = estado == "conectado"
        self.btn_conectar.setEnabled(not conectado)
        self.btn_desconectar.setEnabled(conectado)
        if conectado:
            self.lbl_ws.setStyleSheet(f"color: {EXITO}; font-weight: bold;")
        else:
            self.lbl_ws.setStyleSheet(f"color: {ERROR}; font-weight: bold;")

    def closeEvent(self, evento) -> None:  # noqa: N802
        self.api.cerrar()
        super().closeEvent(evento)
