"""Vista de predicción: resultados de Ridge y Kalman por vuelta.

Endpoints:
    POST /api/modelos/kalman/estimar
    POST /api/modelos/ridge/ajustar

La vista distingue visualmente el ajuste sobre entrenamiento, la evaluación
sobre prueba, la referencia (verdad simulada o proxy), la banda de incertidumbre
de Kalman y los coeficientes de Ridge. No altera los cálculos del backend.
"""

from __future__ import annotations

import math

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.glosario import tooltip
from telemetria.gui.graficas import (
    ContextoZoom,
    CursorGrafico,
    limites_visualizacion,
)
from telemetria.gui.paleta import ACENTO, ERROR, EXITO
from telemetria.gui.parametros import PARAMETROS_POR_DEFECTO, descripcion_feature
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaPrediccion(VistaBase):
    """Panel de resultados de la predicción de degradación."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self.parametros: dict = dict(PARAMETROS_POR_DEFECTO)
        self._pred_laps: list[int] = []
        self._pred_series: dict[str, dict[int, float]] = {}
        self._particiones: dict[str, tuple[int, int]] = {}
        self._importancias: list[dict] = []
        self._banda_kalman: pg.FillBetweenItem | None = None
        self._barras_importancias: list[pg.BarGraphItem] | None = None
        self._construir_ui()
        self._cursor = CursorGrafico(self.grafico)
        self._conectar_senales()
        self._mostrar_parametros()
        # Kalman/Ridge necesitan una sesion activa; se piden al cargarla.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Aquí solo se ven <b>resultados</b>. La curva discontinua de Ridge "
            "es un ajuste sobre datos de entrenamiento: no mide generalización. "
            "Los puntos marcados son la evaluación sobre vueltas de prueba, que "
            "es donde se calculan las métricas. Kalman muestra su banda de "
            "incertidumbre. La referencia puede ser degradación simulada o un "
            "proxy; no es una medición directa del desgaste."
        )

        grp_resumen = QGroupBox("Parámetros usados (ajustables en Taller de modelos)")
        lay_r = QHBoxLayout()
        self.lbl_parametros = QLabel()
        self.lbl_parametros.setWordWrap(True)
        self.lbl_parametros.setToolTip(tooltip("alpha"))
        lay_r.addWidget(self.lbl_parametros, stretch=1)
        self.btn_actualizar = QPushButton("Actualizar resultados")
        self.btn_actualizar.setToolTip(
            "Vuelve a pedir Ridge y Kalman con los parámetros vigentes."
        )
        lay_r.addWidget(self.btn_actualizar)
        # Alias conservado por código y pruebas antiguas.
        self.btn_calcular = self.btn_actualizar
        grp_resumen.setLayout(lay_r)
        layout.addWidget(grp_resumen)

        self.lbl_referencia = QLabel(
            "Referencia pendiente: se indicará si es simulada o un proxy."
        )
        self.lbl_referencia.setWordWrap(True)
        self.lbl_referencia.setToolTip(tooltip("verdad"))
        layout.addWidget(self.lbl_referencia)

        self.grafico = pg.PlotWidget()
        self.grafico.setLabel("left", "Degradación")
        self.grafico.setLabel("bottom", "Vuelta")
        self.grafico.showGrid(x=True, y=True)
        self.grafico.setTitle("Predicción de degradación (sin datos)")
        self.grafico.setToolTip(tooltip("cursor"))
        self.grafico.addLegend(offset=(8, 8))

        self.curva_verdad = self.grafico.plot(
            pen=pg.mkPen("k", width=2), name="Verdad simulada"
        )
        self.curva_proxy = self.grafico.plot(
            pen=pg.mkPen("#b8860b", width=1, style=Qt.PenStyle.DashLine),
            name="Proxy (tiempo y combustible)",
        )
        self.curva_ridge_train = self.grafico.plot(
            pen=pg.mkPen(ACENTO, width=1, style=Qt.PenStyle.DashLine),
            symbol="o",
            symbolSize=5,
            name="Ridge · entrenamiento (ajuste)",
        )
        self.curva_ridge_test = self.grafico.plot(
            pen=pg.mkPen(ACENTO, width=3),
            symbol="o",
            symbolSize=9,
            name="Ridge · prueba (evaluación)",
        )
        # Alias conservado: apunta a la curva que antes se dibujaba completa.
        self.curva_ridge = self.curva_ridge_train
        self.curva_banda_inf = self.grafico.plot(
            pen=pg.mkPen(EXITO, width=1, style=Qt.PenStyle.DotLine),
            name="Kalman · límite inferior",
        )
        self.curva_banda_sup = self.grafico.plot(
            pen=pg.mkPen(EXITO, width=1, style=Qt.PenStyle.DotLine),
            name="Kalman · límite superior",
        )
        self.curva_kalman = self.grafico.plot(
            pen=pg.mkPen(EXITO, width=2), name="Kalman"
        )
        self.grafico.setMinimumHeight(350)
        self.contexto = ContextoZoom(
            self.grafico, rotulo="Vuelta", on_ver_todo=self._encuadrar_prediccion
        )

        grp_grafico = QGroupBox("Curvas por vuelta")
        lay_g = QVBoxLayout()
        lay_g.addWidget(self.grafico)
        lay_g.addWidget(self.contexto)
        grp_grafico.setLayout(lay_g)
        layout.addWidget(grp_grafico, stretch=1)

        leyenda = QLabel(
            "<b>Negro:</b> verdad simulada · <b>Ocre:</b> proxy · "
            "<b>Azul discontinuo:</b> Ridge ajustado en entrenamiento · "
            "<b>Azul con puntos grandes:</b> prueba usada en las métricas · "
            "<b>Verde con franja:</b> Kalman y su banda."
        )
        leyenda.setWordWrap(True)
        layout.addWidget(leyenda)

        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(
            [
                "Modelo",
                "Error medio (MAE)",
                "Error grande (RMSE)",
                "R²",
                "Cobertura de bandas",
                "Error en la caída",
            ]
        )
        for columna, clave in ((1, "mae"), (2, "rmse"), (3, "r2"),
                               (4, "cobertura"), (5, "error_caida")):
            self.tabla.horizontalHeaderItem(columna).setToolTip(tooltip(clave))
        self.tabla.horizontalHeader().setStretchLastSection(True)

        self.lbl_evaluacion = QLabel(
            "Las métricas se calculan solo con las vueltas de prueba."
        )
        self.lbl_evaluacion.setWordWrap(True)
        nota_metricas = QLabel(
            "Menor MAE/RMSE es mejor. R² = 1 es perfecto; 0 equivale a predecir "
            "la media; un R² negativo es peor que esa media. La cobertura indica "
            "cuántas vueltas reales caen dentro de la banda de Kalman. Un valor "
            "«No disponible» significa que el backend no pudo calcularlo, no que "
            "sea bueno."
        )
        nota_metricas.setWordWrap(True)
        nota_metricas.setToolTip(
            f"{tooltip('mae')}\n{tooltip('rmse')}\n{tooltip('r2')}\n"
            f"{tooltip('cobertura')}\n{tooltip('error_caida')}"
        )

        grp_metricas = QGroupBox("Métricas de evaluación")
        lay_m = QVBoxLayout()
        lay_m.addWidget(self.tabla)
        lay_m.addWidget(self.lbl_evaluacion)
        lay_m.addWidget(nota_metricas)
        grp_metricas.setLayout(lay_m)
        layout.addWidget(grp_metricas)

        grp_importancias = QGroupBox("¿Qué factores influyen en la predicción?")
        lay_i = QVBoxLayout()
        lay_orden = QHBoxLayout()
        self.combo_orden_importancias = QComboBox()
        self.combo_orden_importancias.addItem("Mayor magnitud", "magnitud")
        self.combo_orden_importancias.addItem("Coeficientes positivos", "positivos")
        self.combo_orden_importancias.addItem("Coeficientes negativos", "negativos")
        self.combo_orden_importancias.setToolTip(
            "Cambia solo el orden de la tabla y la gráfica; no altera el modelo."
        )
        lay_orden.addWidget(QLabel("Ordenar por:"))
        lay_orden.addWidget(self.combo_orden_importancias)
        lay_orden.addStretch()
        lay_i.addLayout(lay_orden)

        self.grafico_importancias = pg.PlotWidget()
        self.grafico_importancias.setLabel("bottom", "Coeficiente estandarizado")
        self.grafico_importancias.setLabel("left", "Característica")
        self.grafico_importancias.showGrid(x=True, y=False)
        self.grafico_importancias.setMinimumHeight(180)
        lay_i.addWidget(self.grafico_importancias)

        self.tabla_importancias = QTableWidget(0, 3)
        self.tabla_importancias.setHorizontalHeaderLabels(
            ["Característica", "Coeficiente", "Dirección"]
        )
        self.tabla_importancias.horizontalHeaderItem(1).setToolTip(
            "Coeficiente del modelo sobre la feature ya estandarizada."
        )
        self.tabla_importancias.horizontalHeader().setStretchLastSection(True)
        lay_i.addWidget(self.tabla_importancias)

        advertencia = QLabel(
            "Los coeficientes dependen de la escala de cada característica y "
            "las variables correlacionadas pueden repartir o cambiar su peso. "
            "Un coeficiente no demuestra causalidad, y que una feature sea "
            "importante para el modelo no garantiza que represente desgaste "
            "físico real. Pasa el ratón por una característica para ver su "
            "descripción."
        )
        advertencia.setWordWrap(True)
        advertencia.setStyleSheet("color: #555555; font-size: 11px;")
        lay_i.addWidget(advertencia)
        grp_importancias.setLayout(lay_i)
        layout.addWidget(grp_importancias)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_actualizar.clicked.connect(self._solicitar_predicciones)
        self.combo_orden_importancias.currentIndexChanged.connect(
            self._actualizar_importancias
        )

        self.api.kalman_recibido.connect(self._mostrar_kalman)
        self.api.error_kalman.connect(self._mostrar_error_kalman)
        self.api.ridge_recibido.connect(self._mostrar_ridge)
        self.api.error_ridge.connect(self._mostrar_error_ridge)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        """Recalcular modelos cuando cambia la sesion activa."""
        self._solicitar_predicciones()

    def aplicar_parametros(self, parametros: dict) -> None:
        """El Taller envia aqui los valores; esta vista solo recalcula."""
        self.parametros.update(dict(parametros or {}))
        self._mostrar_parametros()
        self._solicitar_predicciones()

    def _mostrar_parametros(self) -> None:
        p = self.parametros
        self.lbl_parametros.setText(
            f"Kalman: Q nivel {p['q_nivel']:g}, Q pendiente "
            f"{p['q_pendiente']:g}, R {p['r']:g}, monótono "
            f"{'sí' if p['monotono'] else 'no'} · Ridge: alpha {p['alpha']:g}. "
            "Alpha se aplica al recalcular; no se guarda en config.yaml. "
            "Cámbialos en el Taller de modelos."
        )

    def _solicitar_predicciones(self) -> None:
        p = self.parametros
        self.api.kalman(
            q_nivel=p["q_nivel"],
            q_pendiente=p["q_pendiente"],
            r=p["r"],
            monotono=p["monotono"],
        )
        self.api.ridge(alpha=p["alpha"])

    def _mostrar_kalman(self, datos: dict) -> None:
        self._dibujar_kalman(datos)
        self._dibujar_referencia(datos)
        self._llenar_metricas(
            datos,
            "Kalman",
            cobertura=datos.get("cobertura"),
            error_caida=datos.get("error_caida"),
        )
        self._actualizar_referencia(datos)
        self.grafico.setTitle("Predicción de degradación (Ridge + Kalman)")

    def _mostrar_ridge(self, datos: dict) -> None:
        self._dibujar_ridge(datos)
        self._dibujar_referencia(datos)
        self._llenar_metricas(
            datos,
            "Ridge",
            cobertura=None,
            error_caida=datos.get("error_caida"),
        )
        self._actualizar_referencia(datos)
        self._importancias = list(datos.get("importancias") or [])
        self._actualizar_importancias()
        self.grafico.setTitle("Predicción de degradación (Ridge + Kalman)")

    # --------------------------------------------------------------- Dibujo
    def _dibujar_ridge(self, datos: dict) -> None:
        vueltas_train = datos.get("laps_train") or []
        valores_train = datos.get("pred_train") or []
        vueltas_test = datos.get("laps_test") or []
        valores_test = datos.get("pred_test") or []

        # Compatibilidad con respuestas antiguas sin claves de partición: se
        # divide la serie dibujada, nunca se inventan valores nuevos.
        if not vueltas_train:
            vueltas_all = datos.get("laps_all") or []
            valores_all = datos.get("pred_all") or []
            conj_test = {int(v) for v in vueltas_test}
            pares = [
                (int(v), float(p))
                for v, p in zip(vueltas_all, valores_all)
                if int(v) not in conj_test
            ]
            vueltas_train = [v for v, _ in pares]
            valores_train = [p for _, p in pares]
        if not vueltas_test:
            # Sin partición explícita, todo lo dibujado es un ajuste. No se
            # presenta como predicción futura ni como resultado de prueba.
            vueltas_train = datos.get("laps_all") or vueltas_train
            valores_train = datos.get("pred_all") or valores_train

        self.curva_ridge_train.setData(vueltas_train, valores_train)
        self.curva_ridge_test.setData(vueltas_test, valores_test)
        self._registrar_serie("Ridge (ajuste)", vueltas_train, valores_train)
        self._registrar_serie("Ridge (prueba)", vueltas_test, valores_test)
        self._particiones["Ridge"] = (
            int(datos.get("n_laps_train", len(vueltas_train))),
            int(datos.get("n_laps_test", len(vueltas_test))),
        )
        self._actualizar_evaluacion()

    def _dibujar_kalman(self, datos: dict) -> None:
        vueltas = datos.get("laps_test", datos.get("laps_train", [])) or []
        valores = datos.get("pred", datos.get("nivel", [])) or []
        self.curva_kalman.setData(vueltas, valores)
        self._registrar_serie("Kalman", vueltas, valores)

        if self._banda_kalman is not None:
            self.grafico.removeItem(self._banda_kalman)
            self._banda_kalman = None
        banda_inf = datos.get("banda_inf") or []
        banda_sup = datos.get("banda_sup") or []
        self.curva_banda_inf.setData(vueltas, banda_inf)
        self.curva_banda_sup.setData(vueltas, banda_sup)
        if banda_inf and banda_sup and len(banda_inf) == len(vueltas):
            color = QColor(EXITO)
            color.setAlpha(45)
            self._banda_kalman = pg.FillBetweenItem(
                self.curva_banda_inf,
                self.curva_banda_sup,
                brush=pg.mkBrush(color),
            )
            self._banda_kalman.setZValue(-5)
            self.grafico.addItem(self._banda_kalman)
            self._registrar_serie("Kalman · banda baja", vueltas, banda_inf)
            self._registrar_serie("Kalman · banda alta", vueltas, banda_sup)
        else:
            self._registrar_serie("Kalman · banda baja", [], [])
            self._registrar_serie("Kalman · banda alta", [], [])
        self._particiones["Kalman"] = (
            int(datos.get("n_laps_train", len(datos.get("laps_train") or []))),
            int(datos.get("n_laps_test", len(vueltas))),
        )
        self._actualizar_evaluacion()

    def _dibujar_referencia(self, datos: dict) -> None:
        tipo = datos.get("referencia_usada")
        if tipo == "proxy":
            vueltas = datos.get("proxy_laps") or datos.get("verdad_laps") or []
            valores = datos.get("proxy") or datos.get("verdad") or []
            self.curva_verdad.clear()
            self.curva_proxy.setData(vueltas, valores)
            self._registrar_serie("Proxy", vueltas, valores)
            self._registrar_serie("Verdad simulada", [], [])
            return

        vueltas = datos.get("verdad_laps") or []
        valores = datos.get("verdad") or []
        if vueltas and valores:
            self.curva_verdad.setData(vueltas, valores)
            self._registrar_serie("Verdad simulada", vueltas, valores)
        else:
            self.curva_verdad.clear()
            self._registrar_serie("Verdad simulada", [], [])

        vueltas_proxy = datos.get("proxy_laps") or []
        valores_proxy = datos.get("proxy") or []
        if vueltas_proxy and valores_proxy:
            self.curva_proxy.setData(vueltas_proxy, valores_proxy)
            self._registrar_serie("Proxy", vueltas_proxy, valores_proxy)
        else:
            self.curva_proxy.clear()
            self._registrar_serie("Proxy", [], [])

    def _actualizar_referencia(self, datos: dict) -> None:
        tipo = datos.get("referencia_usada")
        if tipo == "proxy":
            self.lbl_referencia.setText(
                "Referencia: proxy calculado a partir del tiempo de vuelta y "
                "el combustible. Es una aproximación, no una medición directa "
                "del desgaste."
            )
        elif tipo == "verdad_simulada":
            self.lbl_referencia.setText(
                "Referencia: degradación conocida por construcción del "
                "generador (simulada). El proxy se muestra solo como comparación; "
                "las estimaciones de los modelos son otra cosa distinta."
            )

    def _registrar_serie(self, nombre: str, vueltas: list, valores: list) -> None:
        """Guarda la serie por vuelta para que el cursor pueda leerla."""
        if not vueltas or not valores:
            self._pred_series.pop(nombre, None)
        else:
            self._pred_series[nombre] = {
                int(v): float(val) for v, val in zip(vueltas, valores)
            }
        self._actualizar_cursor()

    def _encuadrar_prediccion(self) -> None:
        self.contexto._encuadrar()

    def _actualizar_cursor(self) -> None:
        if not self._pred_series:
            self._cursor.establecer_datos([], {})
            self.contexto.establecer_datos([], [])
            return
        laps = sorted({v for serie in self._pred_series.values() for v in serie})
        self._pred_laps = laps
        series = {
            nombre: [serie.get(lap) for lap in laps]
            for nombre, serie in self._pred_series.items()
        }
        self._cursor.establecer_datos(
            [float(lap) for lap in laps],
            series,
            formato_x=lambda x, _i: f"Vuelta {int(round(x))}",
        )
        principal = next(iter(series))
        self.contexto.establecer_datos(
            [float(lap) for lap in laps],
            [float(v) if v is not None else 0.0 for v in series[principal]],
            unidad="vueltas",
            series=[
                [float(v) if v is not None else 0.0 for v in valores]
                for valores in series.values()
            ],
            y_limites=limites_visualizacion(*series.values()),
        )

    def _actualizar_evaluacion(self) -> None:
        partes = []
        for modelo, (train, test) in self._particiones.items():
            partes.append(f"{modelo}: {train} entrenamiento / {test} prueba")
        texto = "Métricas calculadas solo sobre las vueltas de prueba."
        if partes:
            texto += " " + " · ".join(partes) + "."
        self.lbl_evaluacion.setText(texto)

    # --------------------------------------------------------------- Métricas
    @staticmethod
    def _texto_metrica(valor) -> str:
        if valor is None:
            return "No disponible"
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            return "No disponible"
        if not math.isfinite(numero):
            return "No disponible"
        return f"{numero:g}"

    def _llenar_metricas(
        self,
        datos: dict,
        modelo: str,
        *,
        cobertura=None,
        error_caida=None,
    ) -> None:
        metricas = datos.get("metricas") or {}
        valores = (
            metricas.get("mae", "?"),
            metricas.get("rmse", "?"),
            self._texto_metrica(metricas.get("r2")),
            self._texto_metrica(cobertura),
            self._texto_metrica(error_caida),
        )
        fila = None
        for i in range(self.tabla.rowCount()):
            if self.tabla.item(i, 0).text() == modelo:
                fila = i
                break
        if fila is None:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(modelo))
        for columna, valor in enumerate(valores, start=1):
            celda = QTableWidgetItem(str(valor))
            if columna == 3:
                try:
                    if float(valor) < 0:
                        celda.setForeground(QColor(ERROR))
                except (TypeError, ValueError):
                    pass
            self.tabla.setItem(fila, columna, celda)

    # ---------------------------------------------------------- Importancias
    def _actualizar_importancias(self) -> None:
        filas = list(self._importancias)
        criterio = str(self.combo_orden_importancias.currentData() or "magnitud")

        def _valor(item: dict) -> float:
            try:
                return float(item.get("coeficiente", 0.0))
            except (TypeError, ValueError):
                return 0.0

        if criterio == "positivos":
            filas.sort(key=_valor, reverse=True)
        elif criterio == "negativos":
            filas.sort(key=_valor)
        else:
            filas.sort(key=lambda item: abs(_valor(item)), reverse=True)

        self.tabla_importancias.setRowCount(0)
        for fila in filas:
            nombre = str(fila.get("feature", "?"))
            coeficiente = _valor(fila)
            fila_tabla = self.tabla_importancias.rowCount()
            self.tabla_importancias.insertRow(fila_tabla)
            celdas = (
                nombre,
                f"{coeficiente:g}",
                "Aumenta la estimación" if coeficiente >= 0 else "La reduce",
            )
            for columna, texto in enumerate(celdas):
                celda = QTableWidgetItem(texto)
                celda.setToolTip(descripcion_feature(nombre))
                self.tabla_importancias.setItem(fila_tabla, columna, celda)

        for barra in self._barras_importancias or []:
            self.grafico_importancias.removeItem(barra)
        self._barras_importancias = None
        if not filas:
            self.grafico_importancias.setTitle("Importancias (sin datos)")
            self.grafico_importancias.getPlotItem().getAxis("left").setTicks([[]])
            return

        coeficientes = [_valor(fila) for fila in filas]
        n = len(filas)
        # pyqtgraph no admite una lista de colores en ``brush``: se crea un
        # grupo de barras por signo, cada uno con un único QBrush válido.
        barras: list[pg.BarGraphItem] = []
        for positivas, color in ((True, QColor(ACENTO)), (False, QColor(ERROR))):
            indices = [
                i for i, c in enumerate(coeficientes) if (c >= 0) == positivas
            ]
            if not indices:
                continue
            if positivas:
                x0 = [0.0] * len(indices)
                anchos = [coeficientes[i] for i in indices]
            else:
                x0 = [coeficientes[i] for i in indices]
                anchos = [-coeficientes[i] for i in indices]
            barra = pg.BarGraphItem(
                x0=x0,
                y=indices,
                width=anchos,
                height=0.6,
                brush=pg.mkBrush(color),
            )
            self.grafico_importancias.addItem(barra)
            barras.append(barra)
        self._barras_importancias = barras or None
        self.grafico_importancias.getPlotItem().getAxis("left").setTicks(
            [
                [
                    (i, str(fila.get("feature", "?"))[:28])
                    for i, fila in enumerate(filas)
                ]
            ]
        )
        self.grafico_importancias.setXRange(
            min(0.0, min(coeficientes)), max(0.0, max(coeficientes)), padding=0.15
        )
        self.grafico_importancias.setYRange(-0.8, n - 0.2, padding=0.02)
        self.grafico_importancias.setTitle(
            f"Coeficientes de Ridge ({criterio})"
        )

    # --------------------------------------------------------------- Errores
    def _mostrar_error_kalman(self, mensaje: str) -> None:
        self.grafico.setTitle(f"Kalman: {error_amigable(mensaje)}")

    def _mostrar_error_ridge(self, mensaje: str) -> None:
        self.grafico.setTitle(f"Ridge: {error_amigable(mensaje)}")
