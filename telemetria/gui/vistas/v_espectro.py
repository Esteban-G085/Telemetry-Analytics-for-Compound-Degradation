"""Vista de espectro: PSD de Welch de un canal (crudo vs. limpio).

Endpoint: GET /api/telemetria/espectro?canal=...&lap=...&nperseg=...

Muestra dos curvas (crudo y limpio) con las bandas de frecuencia sombreadas.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
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
from telemetria.gui.etiquetas_canales import (
    descripcion_canal,
    etiqueta_canal,
    filtrar_canales,
)
from telemetria.gui.glosario import tooltip
from telemetria.gui.graficas import CursorGrafico
from telemetria.gui.paleta import COLORES_BANDA, TEXTO
from telemetria.gui.vistas.vista_base import VistaBase, error_amigable


class VistaEspectro(VistaBase):
    """Panel de espectro de Welch por canal."""

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(api, parent)
        self._canales: list[str] = []
        self._laps: list[int] = []
        self._bandas: list[pg.LinearRegionItem] = []
        self._etiquetas_banda: list[pg.TextItem] = []
        self._construir_ui()
        self._cursor = CursorGrafico(self.grafico)
        self._conectar_senales()
        # La lista de canales y el PSD dependen de la sesion activa.

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        layout = self._layout

        self.agregar_ayuda(
            "Muestra en qué frecuencias se mueve el deslizamiento de cada "
            "neumático. La curva verde es la señal ya filtrada; la roja es la "
            "original. La vuelta <b>0</b> usa toda la sesión. Las franjas "
            "sombreadas son las bandas baja, media y alta."
        )

        grp_controles = QGroupBox("Espectro de Welch (PSD)")
        lay = QHBoxLayout()

        self.combo_canal = QComboBox()
        self.combo_canal.setMinimumWidth(220)
        lay.addWidget(QLabel("Señal:"))
        lay.addWidget(self.combo_canal)

        self.spin_lap = QSpinBox()
        self.spin_lap.setRange(0, 1000)
        self.spin_lap.setValue(1)
        self.spin_lap.setSpecialValueText("Todas")
        self.spin_lap.setToolTip(
            "0 = toda la sesión. Elige una vuelta para ver solo ese tramo."
        )
        lay.addWidget(QLabel("Vuelta:"))
        lay.addWidget(self.spin_lap)

        self.spin_nperseg = QSpinBox()
        self.spin_nperseg.setRange(16, 2048)
        self.spin_nperseg.setValue(128)
        self.spin_nperseg.setSingleStep(16)
        self.spin_nperseg.setToolTip(
            "Tamaño del trozo usado para calcular el espectro. Más grande da "
            "más detalle en frecuencia, pero necesita más muestras."
        )
        lay.addWidget(QLabel("Tamaño de ventana:"))
        lay.addWidget(self.spin_nperseg)

        self.btn_calcular = QPushButton("Calcular espectro")
        lay.addWidget(self.btn_calcular)
        lay.addStretch()
        grp_controles.setLayout(lay)
        layout.addWidget(grp_controles)

        self.grafico = pg.PlotWidget()
        self.grafico.setLabel("left", "Densidad (dB/Hz)")
        self.grafico.setLabel("bottom", "Frecuencia (Hz)")
        self.grafico.showGrid(x=True, y=True)
        self.grafico.setTitle("Espectro (sin datos)")
        self.curva_limpia = self.grafico.plot(
            pen=pg.mkPen("g", width=2), name="Filtrada"
        )
        self.curva_cruda = self.grafico.plot(
            pen=pg.mkPen("r", width=1), name="Original"
        )
        self.grafico.addLegend()
        self.grafico.setToolTip(tooltip("psd"))
        self.grafico.setMinimumHeight(350)

        grp_grafico = QGroupBox("Gráfico")
        lay_g = QVBoxLayout()
        lay_g.addWidget(self.grafico)
        grp_grafico.setLayout(lay_g)
        layout.addWidget(grp_grafico, stretch=1)

        layout.addStretch()

    # ------------------------------------------------------------------ Senales
    def _conectar_senales(self) -> None:
        self.btn_calcular.clicked.connect(self._solicitar_espectro)
        self.combo_canal.currentTextChanged.connect(self._solicitar_espectro)
        self.spin_lap.valueChanged.connect(self._solicitar_espectro)
        self.spin_nperseg.valueChanged.connect(self._solicitar_espectro)

        self.api.canales_recibidos.connect(self._llenar_canales)
        self.api.error_canales.connect(self._mostrar_error_canales)
        self.api.espectro_recibido.connect(self._dibujar_espectro)
        self.api.error_espectro.connect(self._mostrar_error_espectro)
        self.api.sesion_activa_recibida.connect(self._on_sesion_activa)

    # ------------------------------------------------------------------ Slots
    def _on_sesion_activa(self, sesion: dict) -> None:
        """Al cargar una sesion acota las vueltas y pide los canales.

        El spin permitia hasta 1000 vueltas, asi que avanzar por encima de las
        vueltas reales producia un 422 del backend. Aqui se limita al rango de
        la sesion activa (0 sigue siendo 'Todas').
        """
        meta = sesion.get("vueltas") or []
        if isinstance(meta, list) and meta:
            # /api/sesiones/activa publica n_muestras por vuelta. El backend
            # necesita al menos 8 valores finitos para Welch; las vueltas
            # cortas (p. ej. la 9 de sim_test_99.csv, con 1 muestra) devuelven
            # un 422 que nunca deberia llegar a la interfaz.
            candidatas = [
                int(v["lap"])
                for v in meta
                if isinstance(v, dict)
                and str(v.get("lap", "")).lstrip("-").isdigit()
                and int(v.get("n_muestras", 0)) >= 8
            ]
        else:
            candidatas = [
                int(v)
                for v in (sesion.get("laps") or [])
                if str(v).lstrip("-").isdigit()
            ]
        self._laps = sorted(set(candidatas))
        self.spin_lap.blockSignals(True)
        self.spin_lap.setRange(0, max(self._laps, default=1))
        actual = self.spin_lap.value()
        if self._laps and actual != 0 and actual not in self._laps:
            actual = self._laps[0]
        self.spin_lap.setValue(actual)
        self.spin_lap.blockSignals(False)
        self.api.canales()

    def _llenar_canales(self, datos: dict) -> None:
        brutos = datos.get("canales", [])
        self._canales = (
            [c for c in filtrar_canales(brutos) if c.startswith("wheel_slip_")]
            if isinstance(brutos, list)
            else []
        )
        self.combo_canal.blockSignals(True)
        self.combo_canal.clear()
        for canal in self._canales:
            fila = self.combo_canal.count()
            self.combo_canal.addItem(etiqueta_canal(canal), canal)
            self.combo_canal.setItemData(
                fila, descripcion_canal(canal), Qt.ItemDataRole.ToolTipRole
            )
        # Empezar por la rueda delantera izquierda da un PSD reconocible.
        indice = self.combo_canal.findData("wheel_slip_fl")
        if indice >= 0:
            self.combo_canal.setCurrentIndex(indice)
        self.combo_canal.blockSignals(False)
        if self._canales:
            self._solicitar_espectro()
        else:
            self.grafico.setTitle("Sin canales de deslizamiento")
            self.curva_limpia.clear()
            self.curva_cruda.clear()

    def _solicitar_espectro(self) -> None:
        canal = self.combo_canal.currentData()
        if canal not in self._canales:
            return
        lap = self.spin_lap.value() or None
        if lap is not None and self._laps and lap not in self._laps:
            return
        nperseg = self.spin_nperseg.value()
        self.api.espectro(canal=canal, lap=lap, nperseg=nperseg)

    def _dibujar_espectro(self, datos: dict) -> None:
        # Claves reales de GET /api/telemetria/espectro (servicios/analisis.py).
        freqs = datos.get("freqs", [])
        limpia = datos.get("psd_limpio_db", [])
        cruda = datos.get("psd_crudo_db") or []

        self.curva_limpia.setData(freqs, limpia)
        self.curva_cruda.setData(freqs, cruda)
        series = {"Filtrada": limpia}
        if cruda:
            series["Original"] = cruda
        self._cursor.establecer_datos(
            list(freqs),
            series,
            unidades={nombre: "dB/Hz" for nombre in series},
            formato_x=lambda x, _i: f"{x:.2f} Hz",
        )
        self._dibujar_bandas(datos.get("bandas") or {})

        canal = etiqueta_canal(str(datos.get("canal", "?")))
        lap = datos.get("lap")
        lap_txt = "toda la sesión" if lap is None else f"vuelta {lap}"
        self.grafico.setTitle(f"Espectro · {canal} · {lap_txt}")

    def _dibujar_bandas(self, bandas: dict) -> None:
        """Pinta las bandas baja/media/alta con su nombre sobre la franja."""
        for franja in self._bandas:
            self.grafico.removeItem(franja)
        for etiqueta in self._etiquetas_banda:
            self.grafico.removeItem(etiqueta)
        self._bandas.clear()
        self._etiquetas_banda.clear()

        y_min, y_max = self.grafico.getPlotItem().getViewBox().viewRange()[1]
        alto = y_max - y_min
        y_texto = y_max - 0.08 * alto if alto > 0 else y_max
        nombres = {"baja": "Baja", "media": "Media", "alta": "Alta"}
        # PySide convierte los dict de las señales en QVariantMap, que ordena
        # las claves por nombre ('alta', 'baja', 'media'). Aquí imponemos el
        # orden lógico de frecuencias y dejamos las claves extra al final.
        orden = ("baja", "media", "alta")
        claves = [clave for clave in orden if clave in bandas]
        claves += sorted(clave for clave in bandas if clave not in orden)

        for indice, clave in enumerate(claves):
            rango = bandas[clave]
            if not isinstance(rango, (list, tuple)) or len(rango) < 2:
                continue
            x0, x1 = float(rango[0]), float(rango[1])
            color = QColor(COLORES_BANDA[indice % len(COLORES_BANDA)])
            color.setAlpha(35)
            franja = pg.LinearRegionItem(
                values=(x0, x1),
                brush=pg.mkBrush(color),
                movable=False,
            )
            franja.setZValue(-10)
            self.grafico.addItem(franja)
            self._bandas.append(franja)

            etiqueta = pg.TextItem(
                nombres.get(str(clave), str(clave).capitalize()),
                color=TEXTO,
                anchor=(0.03, 0.05),
            )
            etiqueta.setPos(x0 + 0.03 * (x1 - x0), y_texto)
            etiqueta.setZValue(5)
            self.grafico.addItem(etiqueta)
            self._etiquetas_banda.append(etiqueta)

    def _mostrar_error_canales(self, mensaje: str) -> None:
        self._canales = []
        self.combo_canal.blockSignals(True)
        self.combo_canal.clear()
        self.combo_canal.blockSignals(False)
        self.grafico.setTitle(error_amigable(mensaje))
        self.curva_limpia.clear()
        self.curva_cruda.clear()
        self._cursor.establecer_datos([], {})

    def _mostrar_error_espectro(self, mensaje: str) -> None:
        texto = str(mensaje)
        if "422" in texto:
            # El backend devuelve 422 cuando la vuelta no tiene muestras
            # suficientes; el texto crudo del servidor no ayuda al usuario.
            aviso = "Esa vuelta no tiene muestras suficientes. Elige otra o 'Todas'."
        else:
            aviso = error_amigable(texto)
        self.grafico.setTitle(aviso)
        self.curva_limpia.clear()
        self.curva_cruda.clear()
        self._cursor.establecer_datos([], {})
