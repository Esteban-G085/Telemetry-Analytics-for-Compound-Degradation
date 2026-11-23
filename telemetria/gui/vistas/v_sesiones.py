"""Vista de sesiones: listar CSV disponibles, cargar una y ver la sesion activa.

Reemplaza la barra de sesion del dashboard web por una pestaña de escritorio
clara y autoexplicativa.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaSesiones(VistaBase):
    """Panel de sesiones: lista, carga y estado de la sesion activa."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._construir_ui()
        self._conectar_senales()

        # Carga inicial de datos
        self.api.sesiones()
        self.api.sesion_activa()

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Elige un CSV y pulsa <b>Cargar sesión seleccionada</b>. "
            "Las demás pestañas se llenan solas. Los archivos terminados en "
            "<i>_verdad.csv</i> son etiquetas de referencia, no sesiones."
        )

        # --- Grupo: sesiones disponibles ---
        grp_sesiones = QGroupBox("Sesiones disponibles (CSV en data/raw/)")
        lay_sesiones = QVBoxLayout()

        self.lista_sesiones = QListWidget()
        self.lista_sesiones.setAlternatingRowColors(True)
        self.lista_sesiones.setMinimumHeight(200)
        lay_sesiones.addWidget(self.lista_sesiones)

        lay_botones = QHBoxLayout()
        self.btn_refrescar = QPushButton("Refrescar lista")
        self.btn_cargar = QPushButton("Cargar sesion seleccionada")
        self.btn_cargar.setEnabled(False)
        lay_botones.addWidget(self.btn_refrescar)
        lay_botones.addWidget(self.btn_cargar)
        lay_sesiones.addLayout(lay_botones)
        grp_sesiones.setLayout(lay_sesiones)
        layout.addWidget(grp_sesiones)

        # --- Grupo: sesion activa ---
        grp_activa = QGroupBox("Sesion activa")
        lay_activa = QVBoxLayout()

        self.lbl_activa = QLabel("Ninguna sesion cargada.")
        self.lbl_activa.setWordWrap(True)
        lay_activa.addWidget(self.lbl_activa)

        self.lbl_detalle = QLabel("")
        self.lbl_detalle.setWordWrap(True)
        lay_activa.addWidget(self.lbl_detalle)
        grp_activa.setLayout(lay_activa)
        layout.addWidget(grp_activa)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_refrescar.clicked.connect(self.api.sesiones)
        self.btn_cargar.clicked.connect(self._cargar_seleccion)
        self.lista_sesiones.itemSelectionChanged.connect(
            self._actualizar_boton_cargar
        )

        self.api.sesiones_recibidas.connect(self._llenar_lista)
        self.api.error_sesiones.connect(self._mostrar_error)
        self.api.sesion_activa_recibida.connect(self._mostrar_sesion_activa)
        self.api.error_sesion_activa.connect(self._mostrar_error)

    # ------------------------------------------------------------------ Slots
    def _llenar_lista(self, datos: dict) -> None:
        sesiones = datos.get("sesiones", []) if isinstance(datos, dict) else datos
        self.lista_sesiones.clear()
        for sesion in sesiones:
            nombre = sesion.get("nombre", "sin nombre") if isinstance(sesion, dict) else str(sesion)
            item = QListWidgetItem(nombre)
            item.setData(Qt.ItemDataRole.UserRole, nombre)
            self.lista_sesiones.addItem(item)

    def _actualizar_boton_cargar(self) -> None:
        self.btn_cargar.setEnabled(self.lista_sesiones.currentItem() is not None)

    def _cargar_seleccion(self) -> None:
        item = self.lista_sesiones.currentItem()
        if item is None:
            return
        nombre = item.data(Qt.ItemDataRole.UserRole)
        self.api.cargar_sesion(nombre)

    def _mostrar_sesion_activa(self, sesion: dict) -> None:
        nombre = sesion.get("nombre", "desconocida")
        vueltas = sesion.get("vueltas", "?")
        self.lbl_activa.setText(f"Sesion activa: <b>{nombre}</b>")
        self.lbl_detalle.setText(f"Vueltas: {vueltas}")

    def _mostrar_error(self, mensaje: str) -> None:
        self.lbl_activa.setText(error_amigable(mensaje))
