"""Ayudas visuales compartidas por las gráficas de la GUI.

Dos problemas concretos viven aquí:

* El minimapa evita perder la referencia al hacer zoom y, además, **limita**
  la navegación al rango real de la vuelta: no puedes arrastrar la gráfica
  hasta un sitio donde ya no hay datos.
* El cursor común muestra la posición del ratón y los valores de todas las
  series con sus unidades, sin cortarse cerca de los bordes.
"""

from __future__ import annotations

from bisect import bisect_left

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from telemetria.gui.glosario import tooltip
from telemetria.gui.paleta import (
    BORDE_SUAVE,
    PAPEL,
    TEXTO,
    TEXTO_SUAVE,
    color_serie,
)


class ContextoZoom(QWidget):
    """Minimapa, etiqueta de rango y botón para volver a verlo todo.

    No pide datos nuevos: reutiliza las mismas arrays que ya tiene la vista.
    Además de reflejar el rango visible, impide que la vista se salga de los
    límites de la vuelta cargada.
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
        """Dibuja la huella de toda la vuelta y fija los límites de navegación."""
        self._x = list(x)
        self._y = list(y)
        self._unidad = unidad
        if not self._x:
            self._curva.clear()
            self._grafico.plotItem.vb.setLimits(xMin=None, xMax=None)
            self.lbl_rango.setText(f"{self._rotulo}: sin datos")
            return

        minimo, maximo = min(self._x), max(self._x)
        self._curva.setData(self._x, self._y)
        self.minimapa.setXRange(minimo, maximo, padding=0.01)
        if self._y:
            self.minimapa.setYRange(min(self._y), max(self._y), padding=0.05)
        # setLimits evita el arrastre libre; el clamp de _limitar_vista cubre
        # los casos en que pyqtgraph aplica padding después del límite.
        self._grafico.plotItem.vb.setLimits(xMin=minimo, xMax=maximo)
        self.actualizar_etiqueta(self._limitar_vista())

    def actualizar_etiqueta(self, rango: tuple[float, float] | None = None) -> None:
        """Escribe el rango visible con números y su unidad."""
        if not self._x:
            self.lbl_rango.setText(f"{self._rotulo}: sin datos")
            return
        minimo, maximo = min(self._x), max(self._x)
        if rango is None:
            rango = self._grafico.plotItem.vb.viewRange()[0]
        inicio, fin = rango
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

    def _limitar_vista(self) -> tuple[float, float] | None:
        """Devuelve el rango X realmente visible, dentro de los datos."""
        if not self._x:
            return None
        minimo, maximo = min(self._x), max(self._x)
        inicio, fin = self._grafico.plotItem.vb.viewRange()[0]
        corregido = (max(minimo, min(inicio, maximo)), max(minimo, min(fin, maximo)))
        if corregido[0] > corregido[1]:
            corregido = (minimo, maximo)
        if corregido != (inicio, fin):
            self._sincronizando = True
            try:
                self._grafico.setXRange(*corregido, padding=0)
            finally:
                self._sincronizando = False
        return corregido

    def _encuadrar(self) -> None:
        if not self._x:
            return
        minimo, maximo = min(self._x), max(self._x)
        self._sincronizando = True
        try:
            self._region.setRegion((minimo, maximo))
            self._grafico.setXRange(minimo, maximo, padding=0)
        finally:
            self._sincronizando = False
        self.actualizar_etiqueta((minimo, maximo))

    def _vista_a_region(self, *_args) -> None:
        if self._sincronizando:
            return
        rango = self._limitar_vista()
        if rango is None:
            return
        self.actualizar_etiqueta(rango)
        if self._region.getRegion() != rango:
            self._sincronizando = True
            try:
                self._region.setRegion(rango)
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
        finally:
            self._sincronizando = False
        self.actualizar_etiqueta((inicio, fin))


class CursorGrafico:
    """Crosshair con lectura de valores para cualquier PlotWidget.

    La información se actualiza con ``establecer_datos``. El cursor muestra la
    posición exacta del ratón con dos líneas punteadas y, al lado, los valores
    del punto muestreado más cercano. La caja cambia de lado cerca del borde
    derecho para que el texto nunca quede cortado.
    """

    def __init__(self, grafico: pg.PlotWidget) -> None:
        self._grafico = grafico
        self._x: list[float] = []
        self._series: dict[str, list] = {}
        self._unidades: dict[str, str] = {}
        self._detalles: dict[str, list[str]] = {}
        self._formato_x = None
        self._linea_v: object | None = None
        self._linea_h: object | None = None
        self._texto: object | None = None
        grafico.scene().sigMouseMoved.connect(self.mover)

    def establecer_datos(
        self,
        x: list[float],
        series: dict[str, list],
        *,
        unidades: dict[str, str] | None = None,
        detalles: dict[str, list[str]] | None = None,
        formato_x=None,
    ) -> None:
        """Conecta el cursor a unas arrays nuevas y lo oculta hasta el próximo movimiento."""
        longitud = min([len(x)] + [len(v) for v in series.values()]) if series else len(x)
        self._x = [float(v) if v is not None else 0.0 for v in x[:longitud]]
        self._series = {nombre: list(v[:longitud]) for nombre, v in series.items()}
        self._unidades = dict(unidades or {})
        self._detalles = dict(detalles or {})
        self._formato_x = formato_x
        self.ocultar()

    @property
    def lectura(self) -> str:
        """Texto visible del cursor; útil para tests y para el smoke."""
        return self._texto.toPlainText() if self._texto is not None else ""

    @staticmethod
    def _fmt(valor) -> str:
        if valor is None:
            return "—"
        try:
            return f"{float(valor):.2f}"
        except (TypeError, ValueError):
            return str(valor)

    def _crear_items(self) -> None:
        if self._linea_v is None:
            self._linea_v = pg.InfiniteLine(
                angle=90,
                movable=False,
                pen=pg.mkPen(TEXTO_SUAVE, width=1, style=Qt.PenStyle.DotLine),
            )
            self._linea_h = pg.InfiniteLine(
                angle=0,
                movable=False,
                pen=pg.mkPen(TEXTO_SUAVE, width=1, style=Qt.PenStyle.DotLine),
            )
            self._texto = pg.TextItem(
                color=TEXTO,
                anchor=(0.02, 0.98),
                fill=pg.mkBrush(PAPEL),
                border=pg.mkPen(BORDE_SUAVE, width=1),
            )
            for item in (self._linea_v, self._linea_h, self._texto):
                self._grafico.addItem(item, ignoreBounds=True)

    def ocultar(self) -> None:
        for item in (self._linea_v, self._linea_h, self._texto):
            if item is not None:
                item.hide()

    def mover(self, pos) -> None:
        """Muestra el cursor si el ratón está dentro del área de la gráfica."""
        if not self._x or not self._series:
            return
        grafico = self._grafico
        if not grafico.plotItem.sceneBoundingRect().contains(pos):
            self.ocultar()
            return
        vista = grafico.plotItem.vb.mapSceneToView(pos)
        x_min, x_max = grafico.plotItem.vb.viewRange()[0]
        if vista.x() < x_min or vista.x() > x_max:
            self.ocultar()
            return

        idx = bisect_left(self._x, vista.x())
        candidatos = [i for i in (idx - 1, idx) if 0 <= i < len(self._x)]
        if not candidatos:
            return
        mejor = min(candidatos, key=lambda i: abs(self._x[i] - vista.x()))

        self._crear_items()
        self._linea_v.setPos(vista.x())
        self._linea_h.setPos(vista.y())
        self._linea_v.show()
        self._linea_h.show()

        if self._formato_x is not None:
            cabecera = self._formato_x(self._x[mejor], mejor)
        else:
            cabecera = f"x = {self._fmt(self._x[mejor])}"
        lineas = [cabecera]
        for nombre, valores in self._series.items():
            texto = f"{nombre}: {self._fmt(valores[mejor])}"
            unidad = self._unidades.get(nombre)
            if unidad:
                texto += f" {unidad}"
            extra = self._detalles.get(nombre)
            if extra and mejor < len(extra) and extra[mejor]:
                texto += f" · {extra[mejor]}"
            lineas.append(texto)
        self._texto.setText("\n".join(lineas))

        y_min, y_max = grafico.plotItem.vb.viewRange()[1]
        ancho = max(1e-9, x_max - x_min)
        alto = max(1e-9, y_max - y_min)
        izquierda = vista.x() < x_min + 0.62 * ancho
        self._texto.setAnchor((0.02 if izquierda else 0.98, 0.98))
        self._texto.setPos(
            x_min + (0.02 if izquierda else 0.98) * ancho,
            y_max - 0.03 * alto,
        )
        self._texto.show()
