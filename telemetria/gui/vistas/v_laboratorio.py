"""Vista de laboratorio: sliders de parametros y gestion de configuracion.

Endpoints:
    GET  /api/config
    POST /api/config   (guardar overrides)
    DELETE /api/config (restablecer valores de fabrica)
    GET  /api/modelos/features (features numericas del modelo)

Permite ajustar Q/R de Kalman y guardar/restablecer la configuracion activa.
El alpha de Ridge se ajusta en la pestaña de prediccion.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaLaboratorio(VistaBase):
    """Panel de laboratorio con controles de parametros y config."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._construir_ui()
        self._conectar_senales()

        self.api.config()
        # features depende de la sesion; se pide al cargarla.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Aquí se ajustan los parámetros internos de Kalman y se consulta "
            "la configuración activa. Los cambios se aplican al recalcular en "
            "la pestaña <b>Predicción</b>. <b>Guardar cambios</b> deja los "
            "valores como overrides; <b>Restablecer</b> vuelve a "
            "<i>config.yaml</i>. El parámetro alpha de Ridge está en Predicción."
        )

        grp_modelo = QGroupBox("Parametros de Kalman")
        lay = QHBoxLayout()

        self.spin_q_nivel = QDoubleSpinBox()
        self.spin_q_nivel.setRange(0.0, 1.0)
        self.spin_q_nivel.setDecimals(6)
        self.spin_q_nivel.setValue(0.0001)
        self.spin_q_nivel.setToolTip(
            "Cuánto se fía Kalman de que el nivel de desgaste puede cambiar."
        )
        lay.addWidget(QLabel("q_nivel:"))
        lay.addWidget(self.spin_q_nivel)

        self.spin_q_pend = QDoubleSpinBox()
        self.spin_q_pend.setRange(0.0, 1.0)
        self.spin_q_pend.setDecimals(6)
        self.spin_q_pend.setValue(0.00001)
        self.spin_q_pend.setToolTip(
            "Cuánto puede cambiar la pendiente del desgaste."
        )
        lay.addWidget(QLabel("q_pendiente:"))
        lay.addWidget(self.spin_q_pend)

        self.spin_r = QDoubleSpinBox()
        self.spin_r.setRange(0.0, 1.0)
        self.spin_r.setDecimals(6)
        self.spin_r.setValue(0.001)
        self.spin_r.setToolTip("Ruido esperado en la medición.")
        lay.addWidget(QLabel("R:"))
        lay.addWidget(self.spin_r)

        self.chk_monotono = QCheckBox("Kalman monotono")
        self.chk_monotono.setChecked(True)
        self.chk_monotono.setToolTip(
            "Obliga a que la degradación estimada no baje."
        )
        lay.addWidget(self.chk_monotono)

        lay.addStretch()
        grp_modelo.setLayout(lay)
        layout.addWidget(grp_modelo)

        grp_config = QGroupBox("Configuracion activa")
        lay_c = QVBoxLayout()

        self.lbl_config = QLabel("Cargando configuracion...")
        self.lbl_config.setWordWrap(True)
        lay_c.addWidget(self.lbl_config)

        lay_botones = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar cambios")
        self.btn_reiniciar = QPushButton("Restablecer valores de fabrica")
        lay_botones.addWidget(self.btn_guardar)
        lay_botones.addWidget(self.btn_reiniciar)
        lay_botones.addStretch()
        lay_c.addLayout(lay_botones)
        grp_config.setLayout(lay_c)
        layout.addWidget(grp_config)

        grp_features = QGroupBox("Features numericas del modelo")
        lay_f = QVBoxLayout()
        self.lbl_features = QLabel("Cargando features...")
        self.lbl_features.setWordWrap(True)
        lay_f.addWidget(self.lbl_features)
        grp_features.setLayout(lay_f)
        layout.addWidget(grp_features)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_guardar.clicked.connect(self._guardar_cambios)
        self.btn_reiniciar.clicked.connect(self._restablecer_config)

        self.api.config_recibida.connect(self._mostrar_config)
        self.api.error_config.connect(self._mostrar_error_config)
        self.api.features_recibidas.connect(self._mostrar_features)
        self.api.error_features.connect(self._mostrar_error_features)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        self.api.features()

    def _mostrar_config(self, datos: dict) -> None:
        config = datos.get("config", datos)
        self.lbl_config.setText(str(config))

    def _mostrar_features(self, features: list) -> None:
        self.lbl_features.setText(
            ", ".join(map(str, features)) if features else "Sin features"
        )

    def _mostrar_error_config(self, mensaje: str) -> None:
        self.lbl_config.setText(error_amigable(mensaje))

    def _mostrar_error_features(self, mensaje: str) -> None:
        self.lbl_features.setText(error_amigable(mensaje))

    def _guardar_cambios(self) -> None:
        overrides = {
            "modelo": {
                "kalman": {
                    "q_nivel": self.spin_q_nivel.value(),
                    "q_pendiente": self.spin_q_pend.value(),
                    "r": self.spin_r.value(),
                    "monotono": self.chk_monotono.isChecked(),
                },
            },
        }
        self.api.guardar_config(overrides)

    def _restablecer_config(self) -> None:
        self.api.reiniciar_config()
