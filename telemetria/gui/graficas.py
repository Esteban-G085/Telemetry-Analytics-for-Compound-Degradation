"""Ayudas visuales compartidas por las gráficas de la GUI.

Aquí se resuelven una vez los problemas que antes se repetían en cada pestaña:

* ``CursorGrafico``: crosshair, punto seleccionado y caja de valores pegada al
  cursor (con vuelta automática cerca de los bordes). La caja muestra los
  valores **reales** de la muestra más cercana, no los de una posición
  arbitraria del viewport.
* ``ContextoZoom``: minimapa sincronizado, límites al rango real de los datos,
  zoom con rueda centrado en el cursor y una barra de herramientas compacta
  (acercar, alejar, mover, seleccionar región, restablecer, ajustar y auto Y).
*``limites_visualizacion`` / ``limites_psd``: escalas útiles sin tocar los
  datos. Los valores originales siguen disponibles en el cursor y en la API.
"""

from __future__ import annotations

import math
from bisect import bisect_left

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.glosario import tooltip
from telemetria.gui.paleta import (
    ACENTO,
    BORDE_SUAVE,
    PAPEL,
    TEXTO,
    TEXTO_SUAVE,
    color_serie,
)


# --------------------------------------------------------------------------- Escalas
def valores_finitos(*series) -> list[float]:
    """Aplana las series y devuelve solo números finitos."""
    finitos: list[float] = []
    for serie in series:
        for valor in serie or []:
            try:
                numero = float(valor)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numero):
                finitos.append(numero)
    return finitos


def limites_visualizacion(*series, margen: float = 0.06) -> tuple[float, float] | None:
    """Devuelve min–max finitos con margen, o ``None`` si no hay datos.

    Es solo la escala del eje: las curvas conservan sus valores originales.
    """
    finitos = valores_finitos(*series)
    if not finitos:
        return None
    bajo, alto = min(finitos), max(finitos)
    if alto <= bajo:
        escala = abs(bajo) * margen or 0.5
        return bajo - escala, alto + escala
    holgura = margen * (alto - bajo)
    return bajo - holgura, alto + holgura


def limites_psd(valores, *, rango_dB: float = 80.0, margen: float = 0.05):
    """Escala vertical para una PSD en dB.

    El backend protege los logaritmos con un suelo de ``1e-20`` (-200 dB). Ese
    suelo es un artefacto numérico: si se deja entrar en el autoscale, una
    señal de -10…-40 dB queda plana contra el borde. Mostramos como máximo un
    rango dinámico de ``rango_dB``; los valores por debajo siguen existiendo y
    se pueden leer en el cursor. No se cambia ningún dato.
    """
    finitos = valores_finitos(valores)
    if not finitos:
        return None
    bajo, alto = min(finitos), max(finitos)
    suelo = max(bajo, alto - rango_dB)
    if suelo >= alto:
        suelo, alto = bajo - 0.5, alto + 0.5
    holgura = margen * (alto - suelo)
    return suelo - holgura, alto + holgura


class BarraHerramientas(QWidget):
    """Controles de navegación compactos y con tooltip para un PlotWidget."""

    def __init__(self, callbacks: dict, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("barra_herramientas")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        def boton(nombre: str, texto: str, clave: str, *, checkable: bool = False):
            control = QToolButton(self)
            control.setObjectName("herramienta_grafico")
            control.setText(texto)
            control.setToolTip(tooltip(clave))
            control.setCheckable(checkable)
            control.clicked.connect(callbacks[nombre])
            lay.addWidget(control)
            setattr(self, nombre, control)
            return control

        boton("btn_acercar", "+", "zoom_in")
        boton("btn_alejar", "−", "zoom_out")
        self.btn_mover = boton(
            "btn_mover", "Mover", "pan", checkable=True
        )
        self.btn_region = boton(
            "btn_region", "Región", "region", checkable=True
        )
        self.btn_mover.setAutoExclusive(True)
        self.btn_region.setAutoExclusive(True)
        self.btn_mover.setChecked(True)
        boton("btn_restablecer", "Inicio", "restablecer")
        boton("btn_ajustar", "Ajustar", "ajustar")
        self.btn_auto = boton("btn_auto", "Auto Y", "auto_y", checkable=True)
        self.btn_auto.setChecked(True)
        lay.addStretch()


class ContextoZoom(QWidget):
    """Minimapa, etiqueta de rango, barra de herramientas y botón de inicio.

    No pide datos nuevos: reutiliza las mismas arrays que ya tiene la vista.
    Además de reflejar el rango visible, impide que la vista se salga de los
    límites de la vuelta cargada y fija márgenes inferiores y superiores de
    zoom para que siempre queden datos en pantalla.
    """

    def __init__(
        self,
        grafico: pg.PlotWidget,
        *,
        rotulo: str = "Viendo",
        on_ver_todo=None,
        parent=None,
        con_minimapa: bool = True,
    ) -> None:
        super().__init__(parent)
        self._grafico = grafico
        self._rotulo = rotulo
        self._on_ver_todo = on_ver_todo
        self._con_minimapa = con_minimapa
        self._sincronizando = False
        self._x: list[float] = []
        self._y: list[float] = []
        self._unidad = ""
        self._y_min: float | None = None
        self._y_max: float | None = None
        self._rango_inicial: tuple[tuple[float, float], tuple[float, float]] | None = None

        self._construir_ui()
        if on_ver_todo is None:
            on_ver_todo = self._encuadrar
        self.btn_ver_todo.clicked.connect(on_ver_todo)

        self._region.sigRegionChanged.connect(self._region_a_vista)
        self._region.sigRegionChangeFinished.connect(self._region_a_vista)
        self._grafico.plotItem.vb.sigRangeChanged.connect(self._vista_a_region)
        self._grafico.plotItem.vb.setMouseMode(pg.ViewBox.PanMode)

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.setSpacing(2)

        lay = QHBoxLayout()
        self.lbl_rango = QLabel(f"{self._rotulo}: sin datos")
        self.lbl_rango.setToolTip(tooltip("rango"))
        lay.addWidget(self.lbl_rango, stretch=1)

        self.btn_ver_todo = QPushButton("Ver toda la vuelta")
        self.btn_ver_todo.setToolTip(tooltip("encuadrar"))
        lay.addWidget(self.btn_ver_todo)
        exterior.addLayout(lay)

        self.barra = BarraHerramientas(
            {
                "btn_acercar": self._acercar,
                "btn_alejar": self._alejar,
                "btn_mover": self._modo_mover,
                "btn_region": self._modo_region,
                "btn_restablecer": self._restablecer,
                "btn_ajustar": self._ajustar,
                "btn_auto": self._auto_y,
            }
        )
        exterior.addWidget(self.barra)

        if self._con_minimapa:
            self.minimapa = pg.PlotWidget()
            self.minimapa.setObjectName("minimapa")
            self.minimapa.setMaximumHeight(60)
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
            exterior.addWidget(self.minimapa)
        else:
            # La API pública se mantiene aunque el navegador esté oculto: así
            # las vistas en vivo pueden usar la barra sin una huella de señal.
            self.minimapa = None
            self._region = pg.LinearRegionItem(values=(0.0, 1.0), movable=False)
            self._region.hide()

    # ------------------------------------------------------------------ Datos
    def establecer_datos(
        self,
        x: list[float],
        y: list[float],
        *,
        unidad: str = "",
        series: list[list[float]] | None = None,
        y_limites: tuple[float, float] | None = None,
    ) -> None:
        """Dibuja la huella completa y fija los límites de navegación.

        ``series`` permite acotar Y con todas las curvas visibles, no solo con
        la primera. ``y_limites`` permite usar una escala de visualización
        concreta (por ejemplo el rango dinámico de una PSD) sin alterar datos.
        """
        self._x = list(x)
        self._y = list(y)
        self._unidad = unidad
        if not self._x:
            if self.minimapa is not None:
                self._curva.clear()
            self._y_min = self._y_max = None
            self._grafico.plotItem.vb.setLimits(
                xMin=None, xMax=None, yMin=None, yMax=None,
                minXRange=None, maxXRange=None, minYRange=None, maxYRange=None,
            )
            self.lbl_rango.setText(f"{self._rotulo}: sin datos")
            return

        minimo, maximo = min(self._x), max(self._x)
        if self.minimapa is not None:
            self._curva.setData(self._x, self._y)

        if y_limites is not None:
            self._y_min, self._y_max = float(y_limites[0]), float(y_limites[1])
        else:
            finitos = valores_finitos(self._y, *(series or []))
            if not finitos:
                self._y_min = self._y_max = None
            else:
                self._y_min, self._y_max = min(finitos), max(finitos)
        if self._y_min is not None and self._y_max <= self._y_min:
            self._y_min -= 0.5
            self._y_max += 0.5

        if maximo > minimo and self.minimapa is not None:
            self.minimapa.setXRange(minimo, maximo, padding=0)
        if self._y_min is not None and self.minimapa is not None:
            self.minimapa.setYRange(self._y_min, self._y_max, padding=0)

        self._rango_inicial = ((minimo, maximo), (self._y_min, self._y_max))
        self._aplicar_limites()
        self.actualizar_etiqueta(self._limitar_vista())
        if self.barra.btn_auto.isChecked():
            self._grafico.plotItem.vb.enableAutoRange(axis="y", enable=True)

    def _aplicar_limites(self) -> None:
        """El arrastre y la rueda nunca pueden salirse de los datos."""
        if not self._x:
            return
        minimo, maximo = min(self._x), max(self._x)
        ancho = max(maximo - minimo, 1e-9)
        if self._y_min is None or self._y_max is None:
            y_min = y_max = None
            min_y = max_y = None
        else:
            y_min, y_max = self._y_min, self._y_max
            alto = max(y_max - y_min, 1e-9)
            min_y, max_y = alto / 1000.0, alto
        self._grafico.plotItem.vb.setLimits(
            xMin=minimo,
            xMax=maximo,
            yMin=y_min,
            yMax=y_max,
            minXRange=ancho / 1000.0,
            maxXRange=ancho,
            minYRange=min_y,
            maxYRange=max_y,
        )

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

    @staticmethod
    def _recortar(
        inicio: float, fin: float, minimo: float, maximo: float, minimo_ancho: float
    ) -> tuple[float, float]:
        """Mantiene el ancho mínimo sin salirse del rango real de datos."""
        inicio = max(minimo, min(inicio, maximo))
        fin = max(minimo, min(fin, maximo))
        if inicio > fin:
            inicio, fin = minimo, maximo
        if fin - inicio >= minimo_ancho:
            return inicio, fin
        centro = (inicio + fin) / 2.0
        inicio, fin = centro - minimo_ancho / 2.0, centro + minimo_ancho / 2.0
        if inicio < minimo:
            inicio, fin = minimo, min(maximo, minimo + minimo_ancho)
        if fin > maximo:
            fin, inicio = maximo, max(minimo, maximo - minimo_ancho)
        return inicio, fin

    def _limitar_vista(self) -> tuple[float, float] | None:
        """Devuelve el rango X visible, dentro de los datos, y acota también Y."""
        if not self._x:
            return None
        minimo, maximo = min(self._x), max(self._x)
        vista = self._grafico.plotItem.vb.viewRange()
        ancho = max(maximo - minimo, 1e-9)
        corregido = self._recortar(*vista[0], minimo, maximo, ancho / 1000.0)

        abajo, arriba = vista[1]
        if self._y_min is not None and self._y_max is not None:
            alto = max(self._y_max - self._y_min, 1e-9)
            y_corregido = self._recortar(
                abajo, arriba, self._y_min, self._y_max, alto / 1000.0
            )
        else:
            y_corregido = (abajo, arriba)

        if corregido != tuple(vista[0]) or y_corregido != tuple(vista[1]):
            self._sincronizando = True
            try:
                self._grafico.setXRange(*corregido, padding=0)
                if self._y_min is not None:
                    self._grafico.setYRange(*y_corregido, padding=0)
            finally:
                self._sincronizando = False
        return corregido

    # ------------------------------------------------------------------ Navegación
    def _rango_objetivo(self):
        if self._rango_inicial is not None:
            return self._rango_inicial
        vista = self._grafico.plotItem.vb.viewRange()
        return (vista[0], vista[1])

    def _encuadrar(self, *_args) -> None:
        """Vuelve a los límites originales de la señal (X e Y)."""
        if not self._x:
            return
        (x0, x1), (y0, y1) = self._rango_objetivo()
        self._sincronizando = True
        try:
            if self.minimapa is not None:
                self._region.setRegion((x0, x1))
            self._grafico.setXRange(x0, x1, padding=0)
            if y0 is not None and y1 is not None:
                self._grafico.setYRange(y0, y1, padding=0)
        finally:
            self._sincronizando = False
        self.actualizar_etiqueta((x0, x1))

    def _restablecer(self) -> None:
        (self._on_ver_todo or self._encuadrar)()

    def _ajustar(self) -> None:
        """Ajusta ambos ejes al conjunto completo de datos."""
        if not self._x:
            return
        self._encuadrar()

    def _acercar(self) -> None:
        if self._x:
            self._grafico.plotItem.vb.scaleBy((0.65, 0.65))

    def _alejar(self) -> None:
        if self._x:
            self._grafico.plotItem.vb.scaleBy((1.5, 1.5))

    def _modo_mover(self) -> None:
        self._grafico.plotItem.vb.setMouseMode(pg.ViewBox.PanMode)
        self.btn_region.setChecked(False)

    def _modo_region(self) -> None:
        self._grafico.plotItem.vb.setMouseMode(pg.ViewBox.RectMode)
        self.btn_mover.setChecked(False)

    def _auto_y(self, activado: bool) -> None:
        self._grafico.plotItem.vb.enableAutoRange(axis="y", enable=activado)
        if activado:
            self._grafico.plotItem.vb.autoRange()

    def _vista_a_region(self, *_args) -> None:
        if self._sincronizando:
            return
        rango = self._limitar_vista()
        if rango is None:
            return
        self.actualizar_etiqueta(rango)
        if self.minimapa is None:
            return
        if self._region.getRegion() != rango:
            self._sincronizando = True
            try:
                self._region.setRegion(rango)
            finally:
                self._sincronizando = False

    def _region_a_vista(self, *_args) -> None:
        """Mover el minimapa también mueve la vista del gráfico principal."""
        if self._sincronizando or not self._x or self.minimapa is None:
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

    La información se actualiza con ``establecer_datos``. El cursor sigue al
    ratón, marca la muestra real más cercana con un punto, dibuja las dos guías
    en esa muestra y coloca la caja de valores a 14 px del puntero. La caja se
    desplaza al otro lado cuando se acerca a un borde del contenedor, así que
    nunca queda cortada.
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
        self._punto: object | None = None
        self.punto_actual: tuple[float, float] | None = None
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
        """Conecta el cursor a unas arrays nuevas y lo oculta."""
        longitud = min([len(x)] + [len(v) for v in series.values()]) if series else len(x)
        self._x = [float(v) if v is not None else 0.0 for v in x[:longitud]]
        self._series = {nombre: list(v[:longitud]) for nombre, v in series.items()}
        self._unidades = dict(unidades or {})
        self._detalles = dict(detalles or {})
        self._formato_x = formato_x
        self.punto_actual = None
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
            pen = pg.mkPen(TEXTO_SUAVE, width=1, style=Qt.PenStyle.DotLine)
            self._linea_v = pg.InfiniteLine(angle=90, movable=False, pen=pen)
            self._linea_h = pg.InfiniteLine(angle=0, movable=False, pen=pen)
            self._texto = pg.TextItem(
                color=TEXTO,
                anchor=(0.0, 0.0),
                fill=pg.mkBrush(PAPEL),
                border=pg.mkPen(BORDE_SUAVE, width=1),
            )
            self._punto = pg.ScatterPlotItem(
                size=9,
                symbol="o",
                pen=pg.mkPen(PAPEL, width=1.5),
                brush=pg.mkBrush(ACENTO),
            )
            for item in (self._linea_v, self._linea_h, self._punto, self._texto):
                self._grafico.addItem(item, ignoreBounds=True)

    def ocultar(self) -> None:
        for item in (self._linea_v, self._linea_h, self._texto, self._punto):
            if item is not None:
                item.hide()

    def mover(self, pos) -> None:
        """Muestra el crosshair si el ratón está dentro del área de la gráfica."""
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

        nombre_principal = next(iter(self._series))
        valor_y = self._series[nombre_principal][mejor]
        try:
            y_linea = float(valor_y)
        except (TypeError, ValueError):
            y_linea = float(vista.y())
        if not math.isfinite(y_linea):
            y_linea = float(vista.y())

        self._crear_items()
        self._linea_v.setPos(self._x[mejor])
        self._linea_h.setPos(y_linea)
        self._punto.setData([self._x[mejor]], [y_linea])
        for item in (self._linea_v, self._linea_h, self._punto):
            item.show()
        self.punto_actual = (self._x[mejor], y_linea)

        if self._formato_x is not None:
            cabecera = self._formato_x(self._x[mejor], mejor)
        else:
            cabecera = f"x = {self._fmt(self._x[mejor])}"
        cabecera += f" · y = {self._fmt(y_linea)}"
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
        self._texto.show()
        self._colocar_caja(pos)

    def _colocar_caja(self, pos) -> None:
        """Coloca la caja junto al cursor y la devuelve si toca algún borde."""
        vb = self._grafico.plotItem.vb
        destino = vb.mapSceneToView(pos + QPointF(14.0, -14.0))
        self._texto.setPos(destino.x(), destino.y())

        contenedor = self._grafico.plotItem.sceneBoundingRect()
        caja = self._texto.sceneBoundingRect()
        margen = 6.0
        dx = dy = 0.0
        if caja.right() > contenedor.right() - margen:
            dx = contenedor.right() - margen - caja.right()
        if caja.left() + dx < contenedor.left() + margen:
            dx = contenedor.left() + margen - caja.left()
        if caja.bottom() > contenedor.bottom() - margen:
            dy = contenedor.bottom() - margen - caja.bottom()
        if caja.top() + dy < contenedor.top() + margen:
            dy = contenedor.top() + margen - caja.top()
        if dx or dy:
            actual = vb.mapViewToScene(self._texto.pos())
            corregido = vb.mapSceneToView(actual + QPointF(dx, dy))
            self._texto.setPos(corregido.x(), corregido.y())
