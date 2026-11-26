"""Ayudas visuales compartidas por las gráficas de la GUI.

El minimapa responde a una queja concreta: al hacer zoom en una señal es fácil
perder la referencia de dónde estás dentro de la vuelta. Muestra la vuelta
completa y una región resaltada con el trozo que se está viendo. La etiqueta de
rango lo dice también con palabras y números, para no depender solo del color.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from telemetria.gui.glosario import tooltip
from telemetria.gui.paleta import PAPEL, TEXTO, TEXTO_SUAVE, color_serie


class ContextoZoom(QWidget):
    """Minimapa, etiqueta de rango y botón para volver a verlo todo.

    No pide datos nuevos: reutiliza las mismas arrays que ya tiene la vista y
    solo sincroniza la región con el rango visible del gráfico principal.
    """

    def __init__(
        self,
        grafico: pg.PlotWidget,
        *,
        rotulo: str = "Viendo",
        on_ver_todo=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._grafico = grafico
        self._rotulo = rotulo
        self._sincronizando = False
        self._x: list[float] = []
        self._y: list[float] = []
        self._unidad = ""

        self._construir_ui()
        if on_ver_todo is None:
            on_ver_todo = self._encuadrar
        self.btn_ver_todo.clicked.connect(on_ver_todo)

        self._region.sigRegionChanged.connect(self._region_a_vista)
        self._region.sigRegionChangeFinished.connect(self._region_a_vista)
        self._grafico.plotItem.vb.sigRangeChanged.connect(self._vista_a_region)

    def _construir_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.lbl_rango = QLabel(f"{self._rotulo}: toda la vuelta")
        self.lbl_rango.setToolTip(tooltip("rango"))
        lay.addWidget(self.lbl_rango, stretch=1)

        self.btn_ver_todo = QPushButton("Ver toda la vuelta")
        self.btn_ver_todo.setToolTip(tooltip("encuadrar"))
        lay.addWidget(self.btn_ver_todo)

        self.minimapa = pg.PlotWidget()
        self.minimapa.setObjectName("minimapa")
        self.minimapa.setMaximumHeight(70)
        self.minimapa.setMouseEnabled(x=False, y=False)
        self.minimapa.setMenuEnabled(False)
        self.minimapa.hideAxis("left")
        self.minimapa.hideAxis("bottom")
        self.minimapa.setToolTip(tooltip("minimapa"))
        self._curva = self.minimapa.plot(pen=pg.mkPen(color_serie(0), width=1))
        self._region = pg.LinearRegionItem(
            values=(0.0, 1.0),
            movable=True,
            brush=pg.mkBrush("#b3d4f0"),
            pen=pg.mkPen(TEXTO_SUAVE, width=1),
        )
        self._region.setToolTip(tooltip("rango"))
        self.minimapa.addItem(self._region)

        exterior = QVBoxLayout()
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.addLayout(lay)
        exterior.addWidget(self.minimapa)
        self.setLayout(exterior)

    def establecer_datos(
        self, x: list[float], y: list[float], *, unidad: str = ""
    ) -> None:
        """Dibuja la huella de toda la vuelta sin tocar el rango visible."""
        self._x = list(x)
        self._y = list(y)
        self._unidad = unidad
        if not self._x:
            self._curva.clear()
            self.lbl_rango.setText(f"{self._rotulo}: sin datos")
            return

        self._curva.setData(self._x, self._y)
        self.minimapa.setXRange(
            min(self._x), max(self._x), padding=0.01
        )
        if self._y:
            self.minimapa.setYRange(
                min(self._y), max(self._y), padding=0.05
            )
        self.actualizar_etiqueta()

    def actualizar_etiqueta(self) -> None:
        """Escribe el rango visible con números y su unidad."""
        if not self._x:
            self.lbl_rango.setText(f"{self._rotulo}: sin datos")
            return
        minimo = min(self._x)
        maximo = max(self._x)
        inicio, fin = self._grafico.plotItem.vb.viewRange()[0]
        inicio = max(minimo, min(inicio, maximo))
        fin = max(minimo, min(fin, maximo))
        if inicio > fin:
            inicio, fin = minimo, maximo
        porcentaje = 100.0 * (fin - inicio) / (maximo - minimo or 1.0)

        sufijo = f" {self._unidad}" if self._unidad else ""
        self.lbl_rango.setText(
            f"{self._rotulo}: {inicio:.1f}–{fin:.1f}{sufijo} "
            f"de {minimo:.1f}–{maximo:.1f}{sufijo} ({porcentaje:.0f} %)"
        )

    def _encuadrar(self) -> None:
        if not self._x:
            return
        self._sincronizando = True
        try:
            self._region.setRegion((min(self._x), max(self._x)))
            self._grafico.setXRange(min(self._x), max(self._x), padding=0.02)
            self.actualizar_etiqueta()
        finally:
            self._sincronizando = False

    def _vista_a_region(self, *_args) -> None:
        if self._sincronizando:
            return
        inicio, fin = self._grafico.plotItem.vb.viewRange()[0]
        self.actualizar_etiqueta()
        if not self._x:
            return
        minimo, maximo = min(self._x), max(self._x)
        inicio = max(minimo, min(inicio, maximo))
        fin = max(minimo, min(fin, maximo))
        if self._region.getRegion() != (inicio, fin):
            self._sincronizando = True
            try:
                self._region.setRegion((inicio, fin))
            finally:
                self._sincronizando = False

    def _region_a_vista(self, *_args) -> None:
        """Mover el minimapa también mueve la vista del gráfico principal."""
        if self._sincronizando or not self._x:
            return
        inicio, fin = self._region.getRegion()
        if not fin > inicio:
            return
        self._sincronizando = True
        try:
            self._grafico.setXRange(inicio, fin, padding=0)
            self.actualizar_etiqueta()
        finally:
            self._sincronizando = False
