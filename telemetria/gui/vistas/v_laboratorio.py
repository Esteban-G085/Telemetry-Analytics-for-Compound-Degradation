"""Taller de modelos: parámetros, configuración y features explicadas.

Endpoints:
    GET  /api/config
    POST /api/config   (guardar overrides)
    DELETE /api/config (restablecer valores de fábrica)
    GET  /api/modelos/features (features numéricas del modelo)

Aquí se centralizan **todos** los parámetros ajustables (Q/R y monotonía de
Kalman y alpha de Ridge). La pestaña Predicción solo muestra resultados. Las
claves enviadas al backend no cambian.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.glosario import tooltip
from telemetria.gui.parametros import (
    ETIQUETAS_PARAMETROS,
    PARAMETROS_POR_DEFECTO,
    descripcion_feature,
    estado_alpha,
    parametros_desde_config,
)
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaLaboratorio(VistaBase):
    """Taller donde se ajustan y explican los parámetros de los modelos."""

    parametros_cambiados = Signal(dict)

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._config_guardada: dict = {}
        self._config_cruda: dict = {}
        self._reiniciando = False
        self._construir_ui()
        self._conectar_senales()
        self._cargar_parametros(PARAMETROS_POR_DEFECTO)
        self._actualizar_tabla_config()

        self.api.config()
        # features depende de la sesion; se pide al cargarla.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Aquí ajustas <b>todos</b> los parámetros de los modelos y ves qué "
            "está guardado y qué cambiaría. Pulsa <b>Aplicar y recalcular</b> "
            "para que la pestaña <b>Predicción</b> muestre los resultados con "
            "los valores nuevos: allí solo se leen. <b>Guardar</b> deja los "
            "valores como overrides y <b>Restablecer</b> vuelve a config.yaml."
        )

        grp_modelo = QGroupBox("Parámetros de los modelos")
        lay = QGridLayout()

        self.spin_q_nivel = QDoubleSpinBox()
        self.spin_q_nivel.setRange(0.0, 1.0)
        self.spin_q_nivel.setDecimals(6)
        self.spin_q_pend = QDoubleSpinBox()
        self.spin_q_pend.setRange(0.0, 1.0)
        self.spin_q_pend.setDecimals(6)
        self.spin_r = QDoubleSpinBox()
        self.spin_r.setRange(0.0, 1.0)
        self.spin_r.setDecimals(6)
        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.0, 10000.0)
        self.spin_alpha.setDecimals(3)

        for fila, clave in enumerate(("q_nivel", "q_pendiente", "r")):
            spin = getattr(self, {
                "q_nivel": "spin_q_nivel",
                "q_pendiente": "spin_q_pend",
                "r": "spin_r",
            }[clave])
            etiqueta, clave_glosario = ETIQUETAS_PARAMETROS[clave]
            spin.setToolTip(tooltip(clave_glosario))
            lay.addWidget(QLabel(f"{etiqueta}:"), fila, 0)
            lay.addWidget(spin, fila, 1)

        alpha_etiqueta, alpha_tooltip = ETIQUETAS_PARAMETROS["alpha"]
        self.spin_alpha.setToolTip(tooltip(alpha_tooltip))
        lay.addWidget(QLabel(f"{alpha_etiqueta}:"), 0, 2)
        lay.addWidget(self.spin_alpha, 0, 3)

        self.chk_monotono = QCheckBox(ETIQUETAS_PARAMETROS["monotono"][0])
        self.chk_monotono.setChecked(True)
        self.chk_monotono.setToolTip(tooltip(ETIQUETAS_PARAMETROS["monotono"][1]))
        lay.addWidget(self.chk_monotono, 1, 2, 1, 2)

        self.btn_aplicar = QPushButton("Aplicar y recalcular")
        self.btn_aplicar.setToolTip(
            "Envía estos valores a los modelos y actualiza la pestaña "
            "Predicción. No cambia la configuración guardada."
        )
        lay.addWidget(self.btn_aplicar, 2, 0, 1, 2)

        lay.setColumnStretch(4, 1)
        grp_modelo.setLayout(lay)
        layout.addWidget(grp_modelo)

        grp_config = QGroupBox("Configuración guardada: antes y después")
        lay_c = QVBoxLayout()

        self.lbl_config = QLabel("Cargando configuración...")
        self.lbl_config.setWordWrap(True)
        lay_c.addWidget(self.lbl_config)

        self.tabla_config = QTableWidget(0, 4)
        self.tabla_config.setHorizontalHeaderLabels(
            ["Parámetro", "Guardado", "En pantalla", "Resultado"]
        )
        cabeceras = self.tabla_config.horizontalHeader()
        for columna in range(4):
            item = self.tabla_config.horizontalHeaderItem(columna)
            if item is not None:
                item.setToolTip(
                    "Comparación entre el valor guardado y el que estás "
                    " editando ahora."
                )
        cabeceras.setStretchLastSection(True)
        lay_c.addWidget(self.tabla_config)

        lay_botones = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar cambios")
        self.btn_guardar.setToolTip(
            "Guarda Q/R/monotonía en la configuración (claves modelo.kalman). "
            "Alpha se usa al recalcular; no se escribe en config.yaml."
        )
        self.btn_reiniciar = QPushButton("Restablecer valores de fábrica")
        self.btn_reiniciar.setToolTip(tooltip("restablecer_fabrica"))
        lay_botones.addWidget(self.btn_guardar)
        lay_botones.addWidget(self.btn_reiniciar)
        lay_botones.addStretch()
        lay_c.addLayout(lay_botones)
        grp_config.setLayout(lay_c)
        layout.addWidget(grp_config, stretch=1)

        grp_features = QGroupBox("Features numéricas del modelo")
        lay_f = QVBoxLayout()
        self.lbl_features = QLabel("Cargando features...")
        self.lbl_features.setWordWrap(True)
        lay_f.addWidget(self.lbl_features)
        self.lista_features = QListWidget()
        self.lista_features.setMaximumHeight(150)
        self.lista_features.setToolTip(
            "Cada línea es una columna que entra al modelo. Pasa el ratón "
            "para ver qué mide."
        )
        lay_f.addWidget(self.lista_features)
        grp_features.setLayout(lay_f)
        layout.addWidget(grp_features)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_aplicar.clicked.connect(self._aplicar_cambios)
        self.btn_guardar.clicked.connect(self._guardar_cambios)
        self.btn_reiniciar.clicked.connect(self._restablecer_config)

        for spin in (
            self.spin_q_nivel,
            self.spin_q_pend,
            self.spin_r,
            self.spin_alpha,
        ):
            spin.valueChanged.connect(self._actualizar_tabla_config)
        self.chk_monotono.toggled.connect(self._actualizar_tabla_config)

        self.api.config_recibida.connect(self._mostrar_config)
        self.api.error_config.connect(self._mostrar_error_config)
        self.api.features_recibidas.connect(self._mostrar_features)
        self.api.error_features.connect(self._mostrar_error_features)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        self.api.features()

    def _parametros_actuales(self) -> dict:
        return {
            "q_nivel": self.spin_q_nivel.value(),
            "q_pendiente": self.spin_q_pend.value(),
            "r": self.spin_r.value(),
            "monotono": self.chk_monotono.isChecked(),
            "alpha": self.spin_alpha.value(),
        }

    def _cargar_parametros(self, datos: dict) -> None:
        """Pone los spins en un valor sin disparar la tabla ni la API."""
        controles = (
            ("spin_q_nivel", "q_nivel"),
            ("spin_q_pend", "q_pendiente"),
            ("spin_r", "r"),
            ("spin_alpha", "alpha"),
        )
        for nombre, clave in controles:
            spin = getattr(self, nombre)
            spin.blockSignals(True)
            spin.setValue(float(datos.get(clave, PARAMETROS_POR_DEFECTO[clave])))
            spin.blockSignals(False)
        self.chk_monotono.blockSignals(True)
        self.chk_monotono.setChecked(bool(datos.get("monotono", True)))
        self.chk_monotono.blockSignals(False)

    def _mostrar_config(self, datos: dict) -> None:
        config = datos.get("config", datos) if isinstance(datos, dict) else {}
        self._config_cruda = config if isinstance(config, dict) else {}
        self._config_guardada = parametros_desde_config(config)
        if self._reiniciando:
            self._cargar_parametros(self._config_guardada)
            self._reiniciando = False
        self.lbl_config.setText(
            "«Guardado» muestra config.yaml (para alpha, la lista de "
            "candidatos o el único valor fijado). «En pantalla» es lo que se "
            "aplica al pulsar Aplicar. Q/R/monotonía se pueden guardar como "
            "overrides; alpha solo afecta al experimento actual y no se "
            "escribe en config.yaml."
        )
        self._actualizar_tabla_config()

    def _actualizar_tabla_config(self, *_args) -> None:
        actuales = self._parametros_actuales()
        guardados = self._config_guardada or PARAMETROS_POR_DEFECTO
        self.tabla_config.setRowCount(0)
        alpha_estado = estado_alpha(self._config_cruda)
        for clave, (etiqueta, clave_glosario) in ETIQUETAS_PARAMETROS.items():
            fila = self.tabla_config.rowCount()
            self.tabla_config.insertRow(fila)
            antes = guardados.get(clave, PARAMETROS_POR_DEFECTO[clave])
            ahora = actuales[clave]
            if clave == "alpha":
                antes_txt = alpha_estado["texto"]
                ahora_txt = f"{float(ahora):g}"
                if alpha_estado["usa_cv"]:
                    resultado = f"se aplica {ahora_txt} al recalcular"
                elif alpha_estado["guardado"] is None:
                    resultado = "no guardado; solo se aplica"
                else:
                    resultado = "sin cambios" if antes == ahora else "cambiará"
            elif isinstance(antes, bool) or isinstance(ahora, bool):
                antes_txt = "sí" if antes else "no"
                ahora_txt = "sí" if ahora else "no"
                resultado = "sin cambios" if antes == ahora else "cambiará"
            else:
                antes_txt = f"{float(antes):g}"
                ahora_txt = f"{float(ahora):g}"
                resultado = "sin cambios" if antes == ahora else "cambiará"
            celdas = (
                etiqueta,
                antes_txt,
                ahora_txt,
                resultado,
            )
            for columna, texto in enumerate(celdas):
                item = QTableWidgetItem(str(texto))
                item.setToolTip(tooltip(clave_glosario))
                self.tabla_config.setItem(fila, columna, item)

    def _mostrar_features(self, features: list) -> None:
        self.lista_features.clear()
        if not features:
            self.lbl_features.setText("Sin features disponibles.")
            return
        self.lbl_features.setText(
            f"{len(features)} columnas que entran al modelo "
            "(pasa el ratón por cada una):"
        )
        for nombre in features:
            item = QListWidgetItem(str(nombre))
            item.setToolTip(descripcion_feature(str(nombre)))
            self.lista_features.addItem(item)

    def _mostrar_error_config(self, mensaje: str) -> None:
        self.lbl_config.setText(error_amigable(mensaje))

    def _mostrar_error_features(self, mensaje: str) -> None:
        self.lbl_features.setText(error_amigable(mensaje))

    def _guardar_cambios(self) -> None:
        # Solo las claves que ya existen en config.yaml.
        kalman = {
            clave: self._parametros_actuales()[clave]
            for clave in ("q_nivel", "q_pendiente", "r", "monotono")
        }
        self.api.guardar_config({"modelo": {"kalman": kalman}})

    def _aplicar_cambios(self) -> None:
        self.parametros_cambiados.emit(self._parametros_actuales())

    def _restablecer_config(self) -> None:
        self._reiniciando = True
        self._cargar_parametros(PARAMETROS_POR_DEFECTO)
        self.api.reiniciar_config()
        self.parametros_cambiados.emit(dict(PARAMETROS_POR_DEFECTO))
