"""Vista de predicción: solo resultados de Ridge y Kalman por vuelta.

Endpoints:
    POST /api/modelos/kalman/estimar
    POST /api/modelos/ridge/ajustar

Muestra las curvas de degradación estimada junto a la verdad/proxy y una tabla
de métricas (MAE, RMSE). Los parámetros se ajustan en el Taller de modelos;
aquí solo se leen y se muestran los resultados.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import (
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
from telemetria.gui.paleta import ACENTO, EXITO, TEXTO
from telemetria.gui.parametros import PARAMETROS_POR_DEFECTO
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaPrediccion(VistaBase):
    """Panel de resultados de la predicción de degradación."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self.parametros: dict = dict(PARAMETROS_POR_DEFECTO)
        self._pred_laps: list[int] = []
        self._pred_series: dict[str, dict[int, float]] = {}
        self._construir_ui()
        self._cursor = CursorGrafico(self.grafico)
        self._conectar_senales()
        self._mostrar_parametros()
        # Kalman/Ridge necesitan una sesion activa; se piden al cargarla.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Aquí solo se ven <b>resultados</b>: la referencia (verdad o proxy), "
            "la tendencia de Ridge y el suavizado de Kalman. Pasa el ratón por "
            "la gráfica para leer cada vuelta. Para cambiar Q/R o alpha, ve al "
            "<b>Taller de modelos</b>; al aplicarlos, estas curvas se recalculan."
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

        self.grafico = pg.PlotWidget()
        self.grafico.setLabel("left", "Degradacion")
        self.grafico.setLabel("bottom", "Vuelta")
        self.grafico.showGrid(x=True, y=True)
        self.grafico.setTitle("Predicción de degradación (sin datos)")
        self.grafico.setToolTip(tooltip("cursor"))

        self.curva_verdad = self.grafico.plot(
            pen=pg.mkPen("k", width=2), name="Verdad / proxy"
        )
        self.curva_ridge = self.grafico.plot(
            pen=pg.mkPen("b", width=2), name="Ridge"
        )
        self.curva_kalman = self.grafico.plot(
            pen=pg.mkPen("g", width=2), name="Kalman"
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
            f'<span style="color:{TEXTO}">■</span> Referencia &nbsp; '
            f'<span style="color:{ACENTO}">■</span> Ridge (tendencia) &nbsp; '
            f'<span style="color:{EXITO}">■</span> Kalman (suavizado)'
        )
        leyenda.setWordWrap(True)
        layout.addWidget(leyenda)

        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(
            ["Modelo", "Error medio (MAE)", "Error grande (RMSE)"]
        )
        self.tabla.horizontalHeaderItem(1).setToolTip(tooltip("mae"))
        self.tabla.horizontalHeaderItem(2).setToolTip(tooltip("rmse"))
        self.tabla.horizontalHeader().setStretchLastSection(True)

        nota_metricas = QLabel(
            "Menor es mejor. El MAE es el error típico; el RMSE castiga más "
            "los fallos grandes."
        )
        nota_metricas.setWordWrap(True)
        nota_metricas.setToolTip(f"{tooltip('mae')}\n{tooltip('rmse')}")

        grp_metricas = QGroupBox("Métricas")
        lay_m = QVBoxLayout()
        lay_m.addWidget(self.tabla)
        lay_m.addWidget(nota_metricas)
        grp_metricas.setLayout(lay_m)
        layout.addWidget(grp_metricas)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_actualizar.clicked.connect(self._solicitar_predicciones)

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
        self._dibujar_curva("kalman", datos, self.curva_kalman)
        self._dibujar_referencia(datos)
        self._llenar_metricas(datos, "Kalman")

    def _mostrar_ridge(self, datos: dict) -> None:
        self._dibujar_curva("ridge", datos, self.curva_ridge)
        self._dibujar_referencia(datos)
        self._llenar_metricas(datos, "Ridge")

    def _dibujar_curva(self, clave: str, datos: dict, curva) -> None:
        # Formato real de analisis.kalman_por_vuelta / ridge_por_vuelta.
        if clave == "ridge":
            vueltas = datos.get("laps_all", [])
            valores = datos.get("pred_all", [])
        else:
            vueltas = datos.get("laps_test", datos.get("laps_train", []))
            valores = datos.get("pred", datos.get("nivel", []))
        if vueltas and valores:
            curva.setData(vueltas, valores)
        else:
            curva.clear()
        nombre = "Ridge" if clave == "ridge" else "Kalman"
        self._registrar_serie(nombre, vueltas, valores)
        self.grafico.setTitle("Predicción de degradación (Ridge + Kalman)")

    def _dibujar_referencia(self, datos: dict) -> None:
        vueltas = datos.get("verdad_laps", datos.get("proxy_laps", []))
        valores = datos.get("verdad", datos.get("proxy", []))
        if vueltas and valores:
            self.curva_verdad.setData(vueltas, valores)
            self._registrar_serie("Verdad / proxy", vueltas, valores)

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

    def _llenar_metricas(self, datos: dict, modelo: str) -> None:
        metricas = datos.get("metricas", {})
        mae = metricas.get("mae", "?")
        rmse = metricas.get("rmse", "?")
        filas = self.tabla.rowCount()
        encontrado = False
        for i in range(filas):
            if self.tabla.item(i, 0).text() == modelo:
                self.tabla.setItem(i, 1, QTableWidgetItem(str(mae)))
                self.tabla.setItem(i, 2, QTableWidgetItem(str(rmse)))
                encontrado = True
                break
        if not encontrado:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(modelo))
            self.tabla.setItem(fila, 1, QTableWidgetItem(str(mae)))
            self.tabla.setItem(fila, 2, QTableWidgetItem(str(rmse)))

    def _mostrar_error_kalman(self, mensaje: str) -> None:
        self.grafico.setTitle(f"Kalman: {error_amigable(mensaje)}")

    def _mostrar_error_ridge(self, mensaje: str) -> None:
        self.grafico.setTitle(f"Ridge: {error_amigable(mensaje)}")
