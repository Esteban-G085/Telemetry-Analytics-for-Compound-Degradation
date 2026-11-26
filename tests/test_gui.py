"""Tests de humo de la GUI PySide6 (sin servidor: cliente API falso).

.verify que las pestañas arrancan sin sesion, que se refrescan al cargar una y
que sus graficos/tablas entienden el formato real de la API. Sin estos tests la
GUI puede quedar "bonita pero vacia" sin que pytest se entere.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from telemetria.gui.cliente_api import ApiClient
from telemetria.gui.reduccion import presupuesto_puntos
from telemetria.gui.ventana_principal import VentanaPrincipal

SESION = {
    "nombre": "sim_test_99.csv",
    "laps": [1, 2, 3],
    "vueltas": [
        {"lap": 1, "n_muestras": 5000},
        {"lap": 2, "n_muestras": 4990},
        {"lap": 3, "n_muestras": 1},  # como la vuelta 9 real: no da PSD
    ],
    "n_muestras": 5000,
    "canales": ["wheel_slip_fl"],
}
CANALES = [
    "timestamp_s",
    "lap",
    "wheel_slip_fl",
    "temp_core_c_fl",
    "speed_kmh",
    "throttle",
    "brake",
]


class ApiFalso(ApiClient):
    """Cliente que registra llamadas y emite senales sin tocar la red."""

    def __init__(self) -> None:
        super().__init__(base_url="http://127.0.0.1:1")
        self.llamadas: list[str] = []
        self.kwargs: dict[str, dict] = {}

    def salud(self) -> None:
        self.llamadas.append("salud")
        self.salud_recibida.emit({"version": "test"})

    def sesion_activa(self) -> None:
        self.llamadas.append("sesion_activa")
        self.error_sesion_activa.emit("404 Not Found: no hay sesion activa")

    def sesiones(self) -> None:
        self.llamadas.append("sesiones")
        self.sesiones_recibidas.emit({"sesiones": []})

    def conectar_telemetria(self) -> None:
        self.estado_telemetria.emit("conectado")

    def desconectar_telemetria(self) -> None:
        self.estado_telemetria.emit("desconectado")

    def canales(self) -> None:
        self.llamadas.append("canales")

    def espectro(self, **kwargs) -> None:
        self.llamadas.append("espectro")
        self.kwargs["espectro"] = kwargs

    def vuelta(self, **kwargs) -> None:
        self.llamadas.append("vuelta")
        self.kwargs["vuelta"] = kwargs

    def vuelta_comparar(self, **kwargs) -> None:
        self.llamadas.append("vuelta_comparar")
        self.kwargs["vuelta_comparar"] = kwargs

    def kalman(self, **kwargs) -> None:
        self.llamadas.append("kalman")

    def ridge(self, **kwargs) -> None:
        self.llamadas.append("ridge")

    def robustez(self, **kwargs) -> None:
        self.llamadas.append("robustez")

    def sensores(self, **kwargs) -> None:
        self.llamadas.append("sensores")

    def features(self) -> None:
        self.llamadas.append("features")

    def config(self) -> None:
        # VistaLaboratorio lo pide al construirse; sin esta redundancia el
        # cliente real intentaría hablar con el backend durante los tests.
        self.llamadas.append("config")
        self.config_recibida.emit({})

    def vivo_sesiones(self) -> None:
        self.llamadas.append("vivo_sesiones")

    def vivo_layout(self) -> None:
        self.llamadas.append("vivo_layout")

    def cerrar(self) -> None:
        pass


class ApiConCacheFalso(ApiClient):
    """Cliente real con `_get` falso para comprobar la caché de vueltas."""

    def __init__(self) -> None:
        super().__init__(base_url="http://127.0.0.1:1")
        self.peticiones = 0

    def _get(self, path: str) -> dict:
        self.peticiones += 1
        return {
            "t": [0.0, 1.0, 2.0],
            "series": {"throttle": [0.0, 1.0, 0.5], "brake": [1.0, 0.0, 0.5]},
        }

    def cerrar(self) -> None:
        pass


def _esperar(qt_app, condicion, timeout_s: float = 5.0) -> None:
    limite = time.perf_counter() + timeout_s
    while time.perf_counter() < limite and not condicion():
        qt_app.processEvents()
        time.sleep(0.01)
    assert condicion(), "la señal Qt no llegó a tiempo"


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def api(qt_app) -> ApiFalso:
    return ApiFalso()


@pytest.fixture
def ventana(qt_app, api) -> VentanaPrincipal:
    ventana = VentanaPrincipal(api)
    ventana.show()
    yield ventana
    ventana.close()


def test_arranca_sin_sesion_sin_textos_de_error(ventana) -> None:
    sesiones = ventana.pestanas.widget(0)
    telemetria = ventana.pestanas.widget(1)
    replay = ventana.pestanas.widget(6)

    assert "Sin sesion activa" in sesiones.lbl_activa.text()
    assert "404" not in sesiones.lbl_activa.text()
    assert "409" not in telemetria.lbl_canales.text()
    assert "404" not in replay.lbl_kpis.text()


def test_todas_las_pestanas_tienen_ayuda_arriba(ventana) -> None:
    for indice in range(ventana.pestanas.count()):
        vista = ventana.pestanas.widget(indice)
        ayuda = getattr(vista, "_ayuda", None)
        assert ayuda is not None, f"Pestaña {indice} sin ayuda"
        assert ayuda.text().strip()

        primera = vista._layout.itemAt(0).widget()
        assert isinstance(primera, QFrame)
        assert ayuda in primera.findChildren(QLabel)


def test_cargar_sesion_refresca_todas_las_vistas(ventana, api) -> None:
    api.llamadas.clear()
    api.sesion_activa_recibida.emit(SESION)

    for esperada in ("canales", "kalman", "ridge", "robustez", "sensores", "features"):
        assert esperada in api.llamadas


def test_espectro_y_prediccion_usan_el_formato_real_de_la_api(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})

    espectro = ventana.pestanas.widget(2)
    assert espectro.combo_canal.currentData() == "wheel_slip_fl"
    api.espectro_recibido.emit(
        {
            "canal": "wheel_slip_fl",
            "lap": 1,
            "freqs": [0.0, 1.0, 2.0],
            "psd_limpio_db": [-10.0, -20.0, -30.0],
            "psd_crudo_db": [-5.0, -15.0, -25.0],
        }
    )
    assert len(espectro.curva_limpia.getData()[0]) == 3
    assert len(espectro.curva_cruda.getData()[0]) == 3

    prediccion = ventana.pestanas.widget(3)
    api.kalman_recibido.emit(
        {
            "laps_test": [2, 3],
            "pred": [0.2, 0.3],
            "verdad_laps": [2, 3],
            "verdad": [0.21, 0.31],
            "metricas": {"mae": 0.011, "rmse": 0.022},
        }
    )
    api.ridge_recibido.emit(
        {
            "laps_all": [1, 2, 3],
            "pred_all": [0.1, 0.2, 0.3],
            "metricas": {"mae": 0.003, "rmse": 0.004},
        }
    )
    assert len(prediccion.curva_kalman.getData()[0]) == 2
    assert len(prediccion.curva_ridge.getData()[0]) == 3
    assert prediccion.tabla.item(0, 1).text() == "0.011"
    assert prediccion.tabla.item(1, 1).text() == "0.003"


def test_selectores_ocultan_contexto_y_usan_nombres_amables(ventana, api) -> None:
    api.canales_recibidos.emit({"canales": CANALES})
    espectro = ventana.pestanas.widget(2)
    replay = ventana.pestanas.widget(6)

    for combo in (espectro.combo_canal, replay.combo_canal):
        claves = [combo.itemData(i) for i in range(combo.count())]
        assert "timestamp_s" not in claves
        assert "lap" not in claves
        assert "wheel_slip_fl" in claves

        fila = combo.findData("wheel_slip_fl")
        assert combo.itemText(fila) == "Deslizamiento FL (delantera izquierda)"
        assert combo.itemData(fila, Qt.ItemDataRole.ToolTipRole)

    claves_lista = [
        replay.lista_comparar.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(replay.lista_comparar.count())
    ]
    assert "timestamp_s" not in claves_lista
    assert "lap" not in claves_lista


def test_espectro_solo_pide_vueltas_de_la_sesion(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    espectro = ventana.pestanas.widget(2)

    assert espectro.spin_lap.minimum() == 0  # 0 = "Todas"
    assert espectro.spin_lap.maximum() == 2
    assert espectro._laps == [1, 2]  # la vuelta 3 tiene 1 muestra

    api.llamadas.clear()
    espectro.spin_lap.setValue(2)
    assert "espectro" in api.llamadas
    assert api.kwargs["espectro"]["lap"] == 2

    # Un valor externo fuera de rango no debe llegar al backend (evita 422).
    espectro.spin_lap.blockSignals(True)
    espectro.spin_lap.setRange(0, 1000)
    espectro.spin_lap.setValue(999)
    espectro.spin_lap.blockSignals(False)
    api.llamadas.clear()
    espectro._solicitar_espectro()
    assert "espectro" not in api.llamadas


def test_espectro_traduce_el_422(ventana, api) -> None:
    espectro = ventana.pestanas.widget(2)
    api.error_espectro.emit(
        "Client error '422 Unprocessable Entity' for url 'http://.../espectro'"
    )
    titulo = espectro.grafico.getPlotItem().titleLabel.text
    assert "422" not in titulo
    assert "muestras suficientes" in titulo


def test_paleta_clara_unica(qt_app) -> None:
    import pyqtgraph as pg

    from telemetria.gui.paleta import PAPEL, TEXTO, aplicar_paleta_clara

    aplicar_paleta_clara(qt_app)
    assert pg.getConfigOption("background") == PAPEL
    assert pg.getConfigOption("foreground") == TEXTO


def test_replay_no_manda_texto_de_error_como_canal(ventana, api) -> None:
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)
    assert replay.combo_canal.currentData() == "wheel_slip_fl"
    api.vuelta_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 0.01],
            "series": {"wheel_slip_fl": [0.1, 0.2]},
            "crudo": {"wheel_slip_fl": [0.11, 0.21]},
            "outliers": {},
            "kpis": {"n_invalidos": 0, "outliers_total": 0},
            "n_total": 2,
        }
    )
    assert len(replay.curva_limpia.getData()[0]) == 2


def test_replay_preset_y_comparador_multisenal(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)

    assert replay.combo_preset.currentText() == "Acelerador + freno"
    marcados = [
        replay.lista_comparar.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(replay.lista_comparar.count())
        if replay.lista_comparar.item(i).checkState() == Qt.CheckState.Checked
    ]
    assert marcados == ["throttle", "brake"]
    assert api.kwargs["vuelta_comparar"]["lap"] == 1
    assert api.kwargs["vuelta_comparar"]["canales"] == ["throttle", "brake"]

    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 0.5, 1.0],
            "series": {
                "throttle": [0.0, 1.0, 0.5],
                "brake": [1.0, 0.0, 0.5],
            },
        }
    )
    assert set(replay._curvas_comparar) == {"throttle", "brake"}
    assert replay._curvas_comparar["throttle"].name() == "Acelerador"
    assert replay._curvas_comparar["brake"].name() == "Freno"
    assert len(replay._curvas_comparar["throttle"].getData()[0]) == 3
    titulo = replay.grafico_comparar.getPlotItem().titleLabel.text
    assert "2 señales" in titulo


def test_replay_normaliza_distintas_unidades(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)

    replay.chk_normalizar.setChecked(True)
    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 1.0, 2.0],
            "series": {
                "throttle": [10.0, 20.0, 30.0],
                "brake": [100.0, 200.0, 300.0],
            },
        }
    )
    for curva in replay._curvas_comparar.values():
        y = curva.getData()[1]
        assert min(y) == pytest.approx(0.0)
        assert max(y) == pytest.approx(1.0)
    assert replay._curvas_comparar["throttle"].name() == "Acelerador (10.00–30.00)"


def test_replay_comparacion_respeta_el_orden_elegido(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)

    # PySide entrega el dict ordenado por clave ('brake' antes que 'throttle').
    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 1.0, 2.0],
            "series": {
                "brake": [1.0, 0.0, 0.5],
                "throttle": [0.0, 1.0, 0.5],
            },
        }
    )
    assert list(replay._curvas_comparar) == ["throttle", "brake"]
    color_throttle = replay._curvas_comparar["throttle"].opts["pen"].color().name()
    color_brake = replay._curvas_comparar["brake"].opts["pen"].color().name()
    assert color_throttle != color_brake


def test_replay_progreso_y_diferencia(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)
    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 1.0, 2.0],
            "series": {
                "throttle": [0.0, 1.0, 0.5],
                "brake": [1.0, 0.0, 0.5],
            },
        }
    )

    replay.chk_progreso.setChecked(True)
    assert replay._curvas_comparar["throttle"].getData()[0] == pytest.approx(
        [0.0, 50.0, 100.0]
    )
    etiqueta_x = replay.grafico_comparar.getPlotItem().getAxis("bottom").labelText
    assert "Progreso" in etiqueta_x

    replay.chk_diferencia.setChecked(True)
    assert replay._curva_diferencia is not None
    assert replay._curva_diferencia.getData()[1] == pytest.approx([-1.0, 1.0, 0.0])


def test_replay_cursor_y_encuadre(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)
    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 1.0, 2.0],
            "series": {
                "throttle": [10.0, 20.0, 30.0],
                "brake": [100.0, 200.0, 300.0],
            },
        }
    )

    pos = replay.grafico_comparar.plotItem.sceneBoundingRect().center()
    replay._mover_cursor_comparacion(pos)
    assert replay._lectura_cursor is not None
    texto = replay._lectura_cursor.toPlainText()
    assert "Acelerador" in texto
    assert "Freno" in texto

    replay.grafico_comparar.setXRange(0.4, 0.6)
    replay.btn_encuadrar.click()
    x_min, x_max = replay.grafico_comparar.plotItem.vb.viewRange()[0]
    assert (x_min, x_max) == pytest.approx((0.0, 2.0), abs=0.1)


def test_vivo_llena_archivos_y_layout(ventana, api) -> None:
    vivo = ventana.pestanas.widget(7)
    api.vivo_sesiones_recibidas.emit(
        [
            {"nombre": "captura.csv", "kb": 12.5},
            {"nombre": "sim_test_99.csv", "kb": 36600.0, "origen": "raw"},
        ]
    )
    assert vivo.combo_archivo.count() == 2
    assert vivo.combo_archivo.currentText() == "sim_test_99.csv"

    api.vivo_layout_recibido.emit(
        {"disponible": False, "layout_ok": False, "error": None}
    )
    assert "AC publicando: no" in vivo.lbl_layout.text()


def test_robustez_muestra_mae_de_sensores(ventana, api) -> None:
    robustez = ventana.pestanas.widget(5)
    robustez.combo_sensor.setCurrentText("wheel_slip")
    robustez.combo_rueda.setCurrentText("fl")
    robustez.btn_anadir.click()
    assert robustez.tabla_sensores.rowCount() == 1

    api.sensores_recibidos.emit(
        {
            "caidos": [{"canal": "wheel_slip", "rueda": "fl"}],
            "mae_base": 0.09,
            "mae": 0.12,
            "delta": 0.03,
        }
    )
    assert robustez.tabla_sensores.item(0, 2).text() == "0.12"
    assert "Error sin fallos: 0.09" in robustez.lbl_sensores.text()
    assert "Subida: ↑ 0.03" in robustez.lbl_sensores.text()


def test_guia_rapida_se_abre_y_explica_metricas(ventana) -> None:
    ventana.btn_guia.click()
    dialogo = ventana._dialogo_guia

    assert dialogo is not None
    assert dialogo.isVisible()
    texto = dialogo.contenido.toPlainText()
    for esperado in (
        "MAE",
        "RMSE",
        "Replay",
        "Glosario",
        "Sesiones",
        "minimapa",
        "Rango visible",
        "Unidades",
    ):
        assert esperado in texto
    dialogo.close()


def test_replay_muestra_tarjetas_de_calidad(ventana, api) -> None:
    replay = ventana.pestanas.widget(6)
    api.vuelta_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 0.01, 0.02, 0.03],
            "series": {"wheel_slip_fl": [0.1, 0.2, 0.3, 0.4]},
            "crudo": {"wheel_slip_fl": [0.1, 0.2, 9.9, 0.4]},
            "valido": [True, True, False, True],
            "outliers": {"wheel_slip_fl": [2]},
            "kpis": {"n_invalidos": 1, "outliers_total": 1},
            "n_total": 4,
        }
    )

    assert replay.lbl_muestras_validas.text() == "3"
    assert replay.lbl_descartadas.text() == "1"
    assert replay.lbl_calidad.text() == "75.0 %"
    for etiqueta in (
        replay.lbl_muestras_validas,
        replay.lbl_descartadas,
        replay.lbl_calidad,
    ):
        assert etiqueta.toolTip()


def test_prediccion_y_robustez_usan_nombres_claros(ventana, api) -> None:
    prediccion = ventana.pestanas.widget(3)
    assert prediccion.tabla.horizontalHeaderItem(1).text() == "Error medio (MAE)"
    assert prediccion.tabla.horizontalHeaderItem(2).text() == "Error grande (RMSE)"
    assert prediccion.tabla.horizontalHeaderItem(1).toolTip()
    assert prediccion.spin_alpha.toolTip()

    laboratorio = ventana.pestanas.widget(4)
    etiquetas_lab = [lbl.text() for lbl in laboratorio.findChildren(QLabel)]
    for esperada in (
        "Kalman · nivel (Q):",
        "Kalman · pendiente (Q):",
        "Kalman · ruido (R):",
    ):
        assert esperada in etiquetas_lab
    assert laboratorio.spin_q_nivel.toolTip()

    robustez = ventana.pestanas.widget(5)
    assert robustez.tabla_sensores.horizontalHeaderItem(3).text() == "Subida del error ↑"
    assert robustez.tabla_sensores.horizontalHeaderItem(3).toolTip()
    assert robustez.spin_snr.toolTip()


def test_espectro_etiqueta_las_bandas(ventana, api) -> None:
    api.espectro_recibido.emit(
        {
            "canal": "wheel_slip_fl",
            "lap": 1,
            "freqs": [0.0, 1.0, 2.0],
            "psd_limpio_db": [-10.0, -20.0, -30.0],
            "bandas": {"baja": [0.0, 1.0], "media": [1.0, 2.0], "alta": [2.0, 3.0]},
        }
    )
    espectro = ventana.pestanas.widget(2)
    assert [e.toPlainText() for e in espectro._etiquetas_banda] == [
        "Baja",
        "Media",
        "Alta",
    ]


def test_replay_pide_puntos_segun_el_ancho_del_grafico(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)

    assert api.kwargs["vuelta"]["max_puntos"] == presupuesto_puntos(
        replay.grafico.width()
    )
    assert api.kwargs["vuelta_comparar"]["max_puntos"] == presupuesto_puntos(
        replay.grafico_comparar.width()
    )


def test_replay_zoom_redibuja_sin_repetir_peticion(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)
    peticiones = api.llamadas.count("vuelta_comparar")

    n = 3000
    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [float(i) * 0.01 for i in range(n)],
            "series": {
                "throttle": [float(i % 100) for i in range(n)],
                "brake": [float(100 - i % 100) for i in range(n)],
            },
        }
    )
    puntos_completos = len(replay._curvas_comparar["throttle"].getData()[0])
    assert puntos_completos < n

    replay.grafico_comparar.setXRange(0.0, 5.0)
    puntos_zoom = len(replay._curvas_comparar["throttle"].getData()[0])
    assert puntos_zoom < puntos_completos
    assert api.llamadas.count("vuelta_comparar") == peticiones
    assert "LTTB" in replay.lbl_puntos.text()


def test_replay_muestra_rango_visible_y_minimapa(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)

    n = 3000
    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [float(i) for i in range(n)],
            "series": {
                "throttle": [float(i % 100) for i in range(n)],
                "brake": [float(100 - i % 100) for i in range(n)],
            },
        }
    )

    contexto = replay.contexto_comparar
    assert contexto.minimapa.scene() is not None
    assert "Viendo:" in contexto.lbl_rango.text()
    assert "minimapa" in contexto.minimapa.toolTip().lower() or contexto.minimapa.toolTip()
    assert "Viendo:" in contexto.lbl_rango.text()
    assert "0.0–2999.0 s" in contexto.lbl_rango.text()
    assert "100 %" in contexto.lbl_rango.text()
    assert "s" in contexto.lbl_rango.toolTip() or contexto.lbl_rango.toolTip()

    replay.grafico_comparar.setXRange(1000.0, 1500.0, padding=0)
    assert "1000.0–1500.0 s" in contexto.lbl_rango.text()
    assert "17 %" in contexto.lbl_rango.text()
    inicio, fin = contexto._region.getRegion()
    assert 990 <= inicio <= 1010
    assert 1490 <= fin <= 1510

    contexto._region.setRegion((2000.0, 2500.0))
    vista = replay.grafico_comparar.plotItem.vb.viewRange()[0]
    assert 1990 <= vista[0] <= 2010
    assert 2490 <= vista[1] <= 2510

    contexto.btn_ver_todo.click()
    vista = replay.grafico_comparar.plotItem.vb.viewRange()[0]
    assert 3050 <= vista[1] <= 3070
    assert "Tiempo de vuelta (s)" in replay.grafico_comparar.getAxis("bottom").labelText


def test_replay_etiqueta_ejes_con_unidades(ventana, api) -> None:
    api.sesion_activa_recibida.emit(SESION)
    api.canales_recibidos.emit({"canales": CANALES})
    replay = ventana.pestanas.widget(6)

    api.vuelta_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 1.0, 2.0],
            "series": {"speed_kmh": [10.0, 20.0, 30.0]},
        }
    )
    assert "km/h" in replay.grafico.getAxis("left").labelText
    assert "s" in replay.contexto_detalle.lbl_rango.text()
    replay.contexto_detalle.btn_ver_todo.click()
    assert "0.0–2.0 s" in replay.contexto_detalle.lbl_rango.text()

    api.vuelta_comparar_recibida.emit(
        {
            "lap": 1,
            "t": [0.0, 1.0, 2.0],
            "series": {"throttle": [10.0, 20.0, 30.0]},
        }
    )
    assert "mando" in replay.grafico_comparar.getAxis("left").labelText

    replay.chk_normalizar.setChecked(True)
    assert "normalizado" in replay.grafico_comparar.getAxis("left").labelText
    assert "10.00" in replay._nombre_serie("throttle", True)

    replay.chk_progreso.setChecked(True)
    assert "Progreso de vuelta (%)" in replay.grafico_comparar.getAxis("bottom").labelText
    assert "%" in replay.contexto_comparar.lbl_rango.text()


def test_cliente_cachea_vuelta_y_limpia_al_cambiar_de_sesion(qt_app) -> None:
    api = ApiConCacheFalso()
    api._registrar_sesion({"id": "sim_test_99"})
    recibidos: list[dict] = []
    api.vuelta_comparar_recibida.connect(recibidos.append)

    params = dict(lap=1, canales=["throttle", "brake"], crudo=False, max_puntos=900)
    api.vuelta_comparar(**params)
    _esperar(qt_app, lambda: len(recibidos) >= 1)
    api.vuelta_comparar(**params)
    _esperar(qt_app, lambda: len(recibidos) >= 2)

    assert api.peticiones == 1
    assert recibidos[0] == recibidos[1]

    api._registrar_sesion({"id": "otra_sesion"})
    api.vuelta_comparar(**params)
    _esperar(qt_app, lambda: len(recibidos) >= 3)

    assert api.peticiones == 2
    api.cerrar()
