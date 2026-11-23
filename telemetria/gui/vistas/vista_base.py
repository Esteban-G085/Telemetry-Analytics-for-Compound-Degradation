"""Clase base para todas las vistas (pestañas) de la GUI de escritorio.

Cada vista recibe el cliente de API y se encarga de conectar sus senales a
los slots de actualizacion de su propia interfaz.

Todas las vistas van envueltas en un QScrollArea para permitir scroll
vertical cuando el contenido es mas alto que la ventana.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.paleta import BORDE_SUAVE, FONDO, TEXTO_SUAVE


def error_amigable(mensaje: str) -> str:
    """Traduce errores HTTP de 'sin sesion' a un texto util para el usuario.

    Los endpoints que dependen de una sesion responden 404 (no hay activa) o
    409 (sesion sin procesar). Pintar el texto crudo del error en una pestaña
    confunde mas que ayuda: lo importante es decir que hay que cargar un CSV.
    """
    texto = str(mensaje)
    if "404" in texto or "409" in texto:
        return "Sin sesion activa. Carga un CSV en la pestaña 'Sesiones'."
    return f"Error: {texto}"


class VistaBase(QWidget):
    """Base para pantallas. Provee acceso al cliente API y scroll automatico."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api = api

        # Scroll area para que la pestaña sea navegable verticalmente
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        # Widget interno que contiene todo el contenido de la vista
        self._contenido = QWidget()
        self._layout = QVBoxLayout(self._contenido)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(12)

        # Layout principal de la vista (solo contiene el scroll)
        lay_principal = QVBoxLayout(self)
        lay_principal.setContentsMargins(0, 0, 0, 0)
        lay_principal.addWidget(self._scroll)

        self._scroll.setWidget(self._contenido)

    def agregar_ayuda(self, texto: str, titulo: str = "Qué estás viendo") -> QFrame:
        """Coloca arriba de la pestaña una explicación breve y siempre visible.

        Se usa en todas las vistas para que alguien que no conoce el proyecto
        sepa qué mira y qué puede hacer, sin leer documentación ni código.
        """
        caja = QFrame()
        caja.setStyleSheet(
            f"QFrame {{ background: {FONDO}; border: 1px solid {BORDE_SUAVE}; "
            f"border-radius: 6px; }}"
        )
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        titulo_label = QLabel(f"<b>{titulo}</b>")
        titulo_label.setStyleSheet(f"color: {TEXTO_SUAVE}; font-size: 12px;")
        texto_label = QLabel(texto)
        texto_label.setWordWrap(True)
        texto_label.setStyleSheet(f"color: {TEXTO_SUAVE}; font-size: 11px;")

        lay.addWidget(titulo_label)
        lay.addWidget(texto_label)
        self._layout.insertWidget(0, caja)
        self._ayuda = texto_label
        return caja

    def add_stretch(self) -> None:
        """Añade un estirador al final del layout de contenido."""
        self._layout.addStretch()
