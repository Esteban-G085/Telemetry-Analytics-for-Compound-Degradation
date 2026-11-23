"""Paleta clara única para toda la GUI (Qt + pyqtgraph).

Antes cada widget heredaba colores del tema del sistema y las graficas usaban
el fondo oscuro por defecto de pyqtgraph. En equipos con modo nocturno eso
dejaba texto blanco sobre fondos claros (o gris oscuro sobre negro), casi
invisible. Aqui se define una sola paleta y se aplica tanto al QPalette de Qt
como a la configuracion global de pyqtgraph.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Paleta clara: una sola fuente de verdad para QSS, QPalette y pyqtgraph.
FONDO = "#f5f5f7"
PAPEL = "#ffffff"
TEXTO = "#222222"
TEXTO_SUAVE = "#555555"
TEXTO_DESACTIVADO = "#888888"
BORDE = "#d0d0d0"
BORDE_SUAVE = "#e0e0e0"
ACENTO = "#0066cc"
ACENTO_HOVER = "#0052a3"
ACENTO_PRESIONADO = "#003f7a"
EXITO = "#008000"
ERROR = "#b00020"
SELECCION_FONDO = "#e8e8ea"
SELECCION_TEXTO = "#ffffff"

# Colores para varias series en el mismo grafico. Se reparten por indice.
COLORES_SERIE = (
    ACENTO,       # azul
    ERROR,        # rojo
    EXITO,        # verde
    "#b8860b",    # ocre
    "#6a1b9a",    # violeta
    "#00838f",    # turquesa
    "#d84315",    # naranja
    "#455a64",    # pizarra
)

# Bandas de frecuencia del espectro (baja, media, alta).
COLORES_BANDA = ("#90caf9", "#ffe082", "#ef9a9a")


def aplicar_paleta_clara(app: QApplication | None = None) -> None:
    """Fuerza la paleta clara en Qt y en las graficas de pyqtgraph.

    Se llama al construir la ventana principal, antes de crear cualquier
    vista, para que todos los widgets y graficos nacional ya con estos colores.
    """
    app = app or QApplication.instance()
    if app is None:
        return

    paleta = QPalette()
    paleta.setColor(QPalette.ColorRole.Window, QColor(FONDO))
    paleta.setColor(QPalette.ColorRole.WindowText, QColor(TEXTO))
    paleta.setColor(QPalette.ColorRole.Base, QColor(PAPEL))
    paleta.setColor(QPalette.ColorRole.AlternateBase, QColor(FONDO))
    paleta.setColor(QPalette.ColorRole.Text, QColor(TEXTO))
    paleta.setColor(QPalette.ColorRole.ToolTipBase, QColor(PAPEL))
    paleta.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXTO))
    paleta.setColor(QPalette.ColorRole.Button, QColor(FONDO))
    paleta.setColor(QPalette.ColorRole.ButtonText, QColor(TEXTO))
    paleta.setColor(QPalette.ColorRole.Highlight, QColor(ACENTO))
    paleta.setColor(QPalette.ColorRole.HighlightedText, QColor(SELECCION_TEXTO))

    paleta.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(TEXTO_DESACTIVADO)
    )
    paleta.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXTO_DESACTIVADO)
    )
    paleta.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXTO_DESACTIVADO)
    )
    app.setPalette(paleta)

    # Fondo blanco y ejes oscuros para TODAS las graficas nuevas.
    pg.setConfigOption("background", PAPEL)
    pg.setConfigOption("foreground", TEXTO)
    pg.setConfigOption("antialias", True)


def color_serie(indice: int) -> str:
    """Color estable para la enésima serie de un gráfico compartido."""
    return COLORES_SERIE[indice % len(COLORES_SERIE)]
