"""Ventana principal de la aplicacion de escritorio.

QMainWindow con:
  * barra de estado que indica si el backend esta vivo,
  * pestañas (sesiones, espectro, predicción, taller, robustez, replay, vivo),
  * un panel superior de control de telemetria en vivo (conectar/desconectar WS),
  * estilos QSS para una apariencia pulida y profesional.

🐴: se quitó la pestaña «Telemetria»: «En vivo» y `/health` cubren el estado
visible sin duplicar el visor de canales.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.dialogo_ayuda import DialogoGuia
from telemetria.gui.glosario import tooltip
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
QToolButton#herramienta_grafico {{
    background: {SELECCION_FONDO};
    color: {TEXTO};
    border: 1px solid {BORDE};
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
    min-height: 20px;
}}
QToolButton#herramienta_grafico:checked {{
    background: {ACENTO};
    color: {SELECCION_TEXTO};
    border-color: {ACENTO_HOVER};
}}
QToolButton#herramienta_grafico:hover {{
    border-color: {ACENTO};
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
        self._dialogo_guia: DialogoGuia | None = None
        # La separación de modos es solo de interfaz: no cambia endpoints ni
        # claves del backend. 'archivo' es el estado inicial porque la app
        # arranca ofreciendo un CSV; 'vivo' se activa con el botón o al capturar.
        self._modo = "archivo"
        self._ws_conectado = False
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

        # Aviso permanente del modo. Así nadie intenta usar el WebSocket con
        # un archivo cargado (ni analizar un CSV mientras captura en vivo).
        frame_modo = QFrame()
        frame_modo.setStyleSheet(
            f"QFrame {{ background: {SELECCION_FONDO}; "
            f"border: 1px solid {BORDE_SUAVE}; border-radius: 6px; }}"
        )
        lay_modo = QHBoxLayout(frame_modo)
        lay_modo.setContentsMargins(10, 6, 10, 6)
        self.lbl_modo = QLabel()
        self.lbl_modo.setWordWrap(True)
        self.lbl_modo.setToolTip(tooltip("modo_archivo"))
        lay_modo.addWidget(self.lbl_modo, stretch=1)
        self.btn_cambiar_modo = QPushButton("Cambiar a modo vivo")
        self.btn_cambiar_modo.setToolTip(tooltip("modo_vivo"))
        lay_modo.addWidget(self.btn_cambiar_modo)
        lay_central.addWidget(frame_modo)

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
        self.btn_guia = QPushButton("Guía rápida")
        self.btn_guia.setToolTip(
            "Abre el paso a paso y el significado de MAE, RMSE, SNR y el resto "
            "de métricas. Puedes dejarlo abierto mientras exploras las pestañas."
        )
        panel_vivo.addWidget(self.btn_conectar)
        panel_vivo.addWidget(self.btn_desconectar)
        panel_vivo.addWidget(self.lbl_ws)
        panel_vivo.addWidget(self.btn_guia)
        panel_vivo.addStretch()
        lay_central.addLayout(panel_vivo)

        # Barra de instrucciones para el usuario
        self.lbl_instrucciones = QLabel(
            "Tip: carga una sesión en 'Sesiones' y explora Espectro, Predicción "
            "o Replay. El aviso de arriba dice en qué modo estás: para capturar "
            "en tiempo real, pulsa 'Cambiar a modo vivo'. La guía rápida "
            "explica las métricas."
        )
        self.lbl_instrucciones.setWordWrap(True)
        self.lbl_instrucciones.setStyleSheet(f"color: {TEXTO_SUAVE}; font-style: italic; padding: 4px 0;")
        lay_central.addWidget(self.lbl_instrucciones)

        # Pestañas
        self.pestanas = QTabWidget()
        self.pestanas.setDocumentMode(True)
        self.pestanas.addTab(VistaSesiones(self.api), "Sesiones")
        self.pestanas.addTab(VistaEspectro(self.api), "Espectro")
        self.pestanas.addTab(VistaPrediccion(self.api), "Prediccion")
        self.pestanas.addTab(VistaLaboratorio(self.api), "Taller de modelos")
        self.pestanas.addTab(VistaRobustez(self.api), "Robustez")
        self.pestanas.addTab(VistaReplay(self.api), "Replay")
        self.pestanas.addTab(VistaVivo(self.api), "En vivo")
        lay_central.addWidget(self.pestanas)

        self.setCentralWidget(central)

        # El Taller concentra los parámetros; Predicción solo recalcula y
        # muestra resultados con lo que recibe de él.
        self.pestanas.widget(3).parametros_cambiados.connect(
            self.pestanas.widget(2).aplicar_parametros
        )

        # ------------------------------------------------------------------ Senales
        self.btn_conectar.clicked.connect(self.api.conectar_telemetria)
        self.btn_desconectar.clicked.connect(self.api.desconectar_telemetria)
        self.btn_guia.clicked.connect(self._abrir_guia)
        self.btn_cambiar_modo.clicked.connect(self._alternar_modo)

        self.api.salud_recibida.connect(self._on_salud)
        self.api.error_salud.connect(self._on_error_salud)
        self.api.estado_telemetria.connect(self._on_estado_ws)
        self.api.sesion_activa_recibida.connect(
            lambda _sesion: self._cambiar_modo("archivo")
        )
        self.api.vivo_iniciado.connect(lambda _datos: self._cambiar_modo("vivo"))

        self._aplicar_modo()

        # Primeras consultas: salud y estado de sesion. El resto de vistas no
        # piden datos dependientes de la sesion hasta recibir sesion_activa.
        self.api.salud()
        self.api.sesion_activa()

    # ------------------------------------------------------------------ Modo
    def _alternar_modo(self) -> None:
        self._cambiar_modo("vivo" if self._modo == "archivo" else "archivo")

    def _cambiar_modo(self, modo: str) -> None:
        if modo not in ("archivo", "vivo"):
            return
        if modo == "archivo" and self._ws_conectado:
            # No dejar un WebSocket abierto mientras se mira un CSV.
            self.api.desconectar_telemetria()
        self._modo = modo
        self._aplicar_modo()

    def _aplicar_modo(self) -> None:
        """Desactiva lo que no corresponde al modo elegido, sin tocar la API."""
        vivo = self._modo == "vivo"
        self.lbl_modo.setText(
            "Modo vivo: capturando en tiempo real. Las pestañas de archivo "
            "están desactivadas para no mezclar fuentes."
            if vivo
            else "Modo archivo: estás viendo un CSV cargado. El WebSocket y la "
            "pestaña 'En vivo' están desactivados."
        )
        self.lbl_modo.setToolTip(tooltip("modo_vivo" if vivo else "modo_archivo"))
        self.btn_cambiar_modo.setText(
            "Cambiar a modo archivo" if vivo else "Cambiar a modo vivo"
        )
        self.btn_cambiar_modo.setToolTip(
            tooltip("modo_archivo" if vivo else "modo_vivo")
        )

        # En modo vivo solo queda accessible «En vivo»: las pestañas de
        # archivo no mezclan fuentes.
        for indice in range(self.pestanas.count()):
            permitida = indice == 6 if vivo else (indice != 6)
            self.pestanas.setTabEnabled(indice, permitida)
        if not self.pestanas.isTabEnabled(self.pestanas.currentIndex()):
            self.pestanas.setCurrentIndex(6 if vivo else 0)

        self.btn_conectar.setEnabled(vivo and not self._ws_conectado)
        self.btn_desconectar.setEnabled(vivo and self._ws_conectado)

    # ------------------------------------------------------------------ Slots
    def _abrir_guia(self) -> None:
        """Muestra la guía rápida; se reutiliza si ya estaba abierta."""
        if self._dialogo_guia is None:
            self._dialogo_guia = DialogoGuia(self)
        self._dialogo_guia.show()
        self._dialogo_guia.raise_()
        self._dialogo_guia.activateWindow()

    def _on_salud(self, datos: dict) -> None:
        version = datos.get("version", "?")
        self.lbl_estado.setText(f"Backend: online (v{version})")
        self.lbl_estado.setStyleSheet(f"color: {EXITO}; font-weight: bold;")

    def _on_error_salud(self, mensaje: str) -> None:
        self.lbl_estado.setText(f"Backend: no responde ({mensaje})")
        self.lbl_estado.setStyleSheet(f"color: {ERROR}; font-weight: bold;")

    def _on_estado_ws(self, estado: str) -> None:
        self._ws_conectado = estado == "conectado"
        if self._modo == "archivo":
            self.lbl_ws.setText("WebSocket: desactivado en modo archivo")
            self.lbl_ws.setStyleSheet(f"color: {TEXTO_SUAVE}; font-weight: bold;")
            self.btn_conectar.setEnabled(False)
            self.btn_desconectar.setEnabled(False)
            if self._ws_conectado:
                self.api.desconectar_telemetria()
            return
        self.lbl_ws.setText(f"WebSocket: {estado}")
        self.btn_conectar.setEnabled(not self._ws_conectado)
        self.btn_desconectar.setEnabled(self._ws_conectado)
        if self._ws_conectado:
            self.lbl_ws.setStyleSheet(f"color: {EXITO}; font-weight: bold;")
        else:
            self.lbl_ws.setStyleSheet(f"color: {ERROR}; font-weight: bold;")

    def closeEvent(self, evento) -> None:  # noqa: N802
        self.api.cerrar()
        super().closeEvent(evento)
