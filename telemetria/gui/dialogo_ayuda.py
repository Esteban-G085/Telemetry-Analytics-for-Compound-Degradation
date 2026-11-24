"""Guía rápida y glosario para quien abre la aplicación por primera vez.

Es un diálogo no modal: se puede dejar abierto mientras se recorren las
pestañas. No añade una pestaña nueva ni sustituye a los bloques de ayuda que
ya tiene cada vista.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)

from telemetria.gui.glosario import GLOSARIO, TERMINOS


class DialogoGuia(QDialog):
    """Ventana pequeña con el flujo de uso y el significado de las métricas."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dialogo_guia")
        self.setWindowTitle("Guía rápida")
        self.setModal(False)
        self.resize(640, 560)

        lay = QVBoxLayout(self)

        cabecera = QLabel("<b>Telemetry Analytics · guía rápida</b>")
        cabecera.setWordWrap(True)
        lay.addWidget(cabecera)

        self.contenido = QTextBrowser()
        self.contenido.setObjectName("contenido_guia")
        self.contenido.setHtml(self._html())
        lay.addWidget(self.contenido)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.close)
        lay.addWidget(botones)

    @staticmethod
    def _html() -> str:
        filas = "".join(
            f"<tr><td valign='top'><b>{nombre}</b></td>"
            f"<td valign='top'>{GLOSARIO[clave]}</td></tr>"
            for nombre, clave in TERMINOS
        )
        return f"""
        <h3>1. Empieza por Sesiones</h3>
        <p>Elige un CSV de <b>data/raw/</b> y pulsa
        <b>Cargar sesión seleccionada</b>. Las demás pestañas se llenan solas.
        Si ves «Sin sesión activa», faltaba este paso.</p>

        <h3>2. Mira el espectro y las predicciones</h3>
        <p><b>Espectro</b> responde a «¿en qué frecuencias se mueve esta señal?».
        <b>Predicción</b> responde a «¿cuánto se desgasta el neumático vuelta a
        vuelta?». Las curvas llevan leyenda y las métricas se explican abajo.</p>

        <h3>3. Compara señales en Replay</h3>
        <p>En <b>Replay</b> puedes juntar acelerador, freno u otras señales en
        el mismo eje de tiempo. Usa el atajo «Acelerador + freno», marca señales
        a mano y activa <b>Normalizar</b> si quieres comparar su forma aunque
        tengan unidades distintas. La zona inferior muestra el detalle de una
        sola señal.</p>

        <h3>Glosario</h3>
        <table border='0' cellpadding='4'>
        {filas}
        </table>
        """
