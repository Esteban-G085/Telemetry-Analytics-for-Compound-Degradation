"""Vista de predicicion: Ridge y Kalman por vuelta con metricas.

Endpoints:
    POST /api/modelos/kalman/estimar
    POST /api/modelos/ridge/ajustar

Muestra las curvas de degradacion estimada junto a la verdad/proxy y una
tabla de metricas (MAE, etc.).
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.paleta import ACENTO, EXITO, TEXTO
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaPrediccion(VistaBase):
    """Panel de predicicion de degradacion (Ridge + Kalman)."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._construir_ui()
        self._conectar_senales()
        # Kalman/Ridge necesitan una sesion activa; se piden al cargarla.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Estima cuánto se desgasta el neumático vuelta a vuelta. La línea "
            "negra es la referencia (verdad o proxy), la azul marca la "
            "tendencia de Ridge y la verde suaviza el estado con Kalman. "
            "MAE y RMSE son el error: cuanto más bajos, mejor. Ajusta los "
            "parámetros y pulsa <b>Recalcular predicciones</b>."
        )

        grp_controles = QGroupBox("Parametros de los modelos")
        lay = QHBoxLayout()

        self.spin_q_nivel = QDoubleSpinBox()
        self.spin_q_nivel.setRange(0.0, 1.0)
        self.spin_q_nivel.setDecimals(6)
        self.spin_q_nivel.setValue(0.0001)
        self.spin_q_nivel.setToolTip(
            "Cuánto se fía Kalman de que el nivel de desgaste puede cambiar. "
            "Más valor = reacciona antes."
        )
        lay.addWidget(QLabel("Kalman q_nivel:"))
        lay.addWidget(self.spin_q_nivel)

        self.spin_q_pend = QDoubleSpinBox()
        self.spin_q_pend.setRange(0.0, 1.0)
        self.spin_q_pend.setDecimals(6)
        self.spin_q_pend.setValue(0.00001)
        self.spin_q_pend.setToolTip(
            "Cuánto puede cambiar la pendiente del desgaste. Más valor = "
            "sigue curvas más pronunciadas."
        )
        lay.addWidget(QLabel("q_pendiente:"))
        lay.addWidget(self.spin_q_pend)

        self.spin_r = QDoubleSpinBox()
        self.spin_r.setRange(0.0, 1.0)
        self.spin_r.setDecimals(6)
        self.spin_r.setValue(0.001)
        self.spin_r.setToolTip(
            "Ruido que se espera en la medición. Más valor = curva más suave, "
            "pero responde más tarde."
        )
        lay.addWidget(QLabel("R:"))
        lay.addWidget(self.spin_r)

        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.0, 10000.0)
        self.spin_alpha.setDecimals(3)
        self.spin_alpha.setValue(0.1)
        self.spin_alpha.setToolTip(
            "Fuerza de la regularización de Ridge. Más valor = tendencia más "
            "simple y menos sensible al ruido."
        )
        lay.addWidget(QLabel("Ridge alpha:"))
        lay.addWidget(self.spin_alpha)

        self.btn_calcular = QPushButton("Recalcular predicciones")
        lay.addWidget(self.btn_calcular)
        lay.addStretch()
        grp_controles.setLayout(lay)
        layout.addWidget(grp_controles)

        self.grafico = pg.PlotWidget()
        self.grafico.setLabel("left", "Degradacion")
        self.grafico.setLabel("bottom", "Vuelta")
        self.grafico.showGrid(x=True, y=True)
        self.grafico.setTitle("Prediccion de degradacion (sin datos)")

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

        grp_grafico = QGroupBox("Curvas por vuelta")
        lay_g = QVBoxLayout()
        lay_g.addWidget(self.grafico)
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
        self.tabla.setHorizontalHeaderLabels(["Modelo", "MAE", "RMSE"])
        self.tabla.horizontalHeader().setStretchLastSection(True)

        grp_metricas = QGroupBox("Metricas")
        lay_m = QVBoxLayout()
        lay_m.addWidget(self.tabla)
        grp_metricas.setLayout(lay_m)
        layout.addWidget(grp_metricas)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_calcular.clicked.connect(self._solicitar_predicciones)

        self.api.kalman_recibido.connect(self._mostrar_kalman)
        self.api.error_kalman.connect(self._mostrar_error_kalman)
        self.api.ridge_recibido.connect(self._mostrar_ridge)
        self.api.error_ridge.connect(self._mostrar_error_ridge)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        """Recalcular modelos cuando cambia la sesion activa."""
        self._solicitar_predicciones()

    def _solicitar_predicciones(self) -> None:
        self.api.kalman(
            q_nivel=self.spin_q_nivel.value(),
            q_pendiente=self.spin_q_pend.value(),
            r=self.spin_r.value(),
            monotono=True,
        )
        self.api.ridge(alpha=self.spin_alpha.value())

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
        self.grafico.setTitle("Prediccion de degradacion (Ridge + Kalman)")

    def _dibujar_referencia(self, datos: dict) -> None:
        vueltas = datos.get("verdad_laps", datos.get("proxy_laps", []))
        valores = datos.get("verdad", datos.get("proxy", []))
        if vueltas and valores:
            self.curva_verdad.setData(vueltas, valores)

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
