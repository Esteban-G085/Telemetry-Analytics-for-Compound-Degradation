"""Cliente de la API para la interfaz de escritorio (PySide6).

Envuelve los endpoints REST de FastAPI (httpx) y el WebSocket de telemetria
(QWebSocket). Emite senales Qt para que la GUI se actualice sin bloquearse.

Todas las peticiones REST se disparan en el hilo global de Qt (QThreadPool)
para que la ventana nunca se congele mientras espera al servidor.

Endpoints cubiertos (todos los de la API FastAPI):
    REST:
        GET  /health
        GET  /api/sesiones, GET  /api/sesiones/activa
        POST /api/sesiones/cargar
        GET  /api/telemetria/canales
        GET  /api/telemetria/vuelta/{lap}
        GET  /api/telemetria/stint
        GET  /api/telemetria/espectro
        POST /api/modelos/kalman/estimar
        POST /api/modelos/ridge/ajustar
        POST /api/modelos/robustez
        POST /api/modelos/sensores
        GET  /api/modelos/features
        GET  /api/modelos/dispersion
        GET  /api/modelos/correlacion
        GET  /api/config, POST /api/config, DELETE /api/config
        POST /api/vivo/iniciar, POST /api/vivo/detener
        GET  /api/vivo/estado, GET /api/vivo/ventana
        GET  /api/vivo/sesiones, GET /api/vivo/layout
    WS:
        /ws/telemetria  (tramas de control y datos)
"""

from __future__ import annotations

import json
from typing import Callable

import httpx
import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWebSockets import QWebSocket


class _TareaRest(QRunnable):
    """Ejecuta una peticion REST en un hilo de fondo y emite el resultado."""

    def __init__(
        self,
        fn: Callable[[], object],
        senal_exito: Signal,
        senal_error: Signal,
    ) -> None:
        super().__init__()
        self.fn = fn
        self.senal_exito = senal_exito
        self.senal_error = senal_error

    def run(self) -> None:  # noqa: D401
        try:
            resultado = self.fn()
            self.senal_exito.emit(resultado)
        except Exception as exc:  # noqa: BLE001 - se reenvia como senal
            self.senal_error.emit(str(exc))


class ApiClient(QObject):
    """Cliente REST + WebSocket de la API de Telemetry Analytics.

    Argumentos:
        base_url: URL del backend FastAPI (por defecto http://127.0.0.1:8000).
    """

    # ------------------------------------------------------- Senales REST - salud
    salud_recibida = Signal(dict)
    error_salud = Signal(str)

    # ------------------------------------------------------- Senales REST - sesiones
    sesiones_recibidas = Signal(dict)
    error_sesiones = Signal(str)

    sesion_activa_recibida = Signal(dict)
    error_sesion_activa = Signal(str)

    # ------------------------------------------------------- Senales REST - telemetria
    canales_recibidos = Signal(dict)
    error_canales = Signal(str)

    vuelta_recibida = Signal(dict)
    error_vuelta = Signal(str)

    # Senal separada para el comparador multi-senal de Replay: asi una peticion
    # no pisa el grafico de detalle de una senal.
    vuelta_comparar_recibida = Signal(dict)
    error_vuelta_comparar = Signal(str)

    stint_recibido = Signal(dict)
    error_stint = Signal(str)

    espectro_recibido = Signal(dict)
    error_espectro = Signal(str)

    # ------------------------------------------------------- Senales REST - modelos
    kalman_recibido = Signal(dict)
    error_kalman = Signal(str)

    ridge_recibido = Signal(dict)
    error_ridge = Signal(str)

    robustez_recibida = Signal(dict)
    error_robustez = Signal(str)

    sensores_recibidos = Signal(dict)
    error_sensores = Signal(str)

    features_recibidas = Signal(list)
    error_features = Signal(str)

    dispersion_recibida = Signal(dict)
    error_dispersion = Signal(str)

    correlacion_recibida = Signal(dict)
    error_correlacion = Signal(str)

    # ------------------------------------------------------- Senales REST - config
    config_recibida = Signal(dict)
    error_config = Signal(str)

    # ------------------------------------------------------- Senales REST - vivo
    vivo_iniciado = Signal(dict)
    error_vivo_iniciar = Signal(str)

    vivo_detenido = Signal(dict)
    error_vivo_detener = Signal(str)

    vivo_estado_recibido = Signal(dict)
    error_vivo_estado = Signal(str)

    vivo_ventana_recibida = Signal(dict)
    error_vivo_ventana = Signal(str)

    vivo_sesiones_recibidas = Signal(list)
    error_vivo_sesiones = Signal(str)

    vivo_layout_recibido = Signal(dict)
    error_vivo_layout = Signal(str)

    # ------------------------------------------------------- Senales WebSocket
    mensaje_telemetria = Signal(dict)       # mensajes JSON de control (ping/pong/ajustes)
    mensaje_binario_telemetria = Signal(dict)  # tramas binarias decodificadas (cabecera + datos)
    estado_telemetria = Signal(str)  # "conectando", "conectado", "desconectado", "error: ..."

    # ------------------------------------------------------- Senales WS de vivo
    mensaje_vivo = Signal(dict)         # mensaje JSON tipo "vivo" con estado + ventana
    estado_vivo = Signal(str)           # "conectando", "conectado", "desconectado", "error: ..."

    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http", "ws") + "/ws/telemetria"

        self._cliente = httpx.Client(timeout=30.0)
        self._pool = QThreadPool.globalInstance()

        # Caché local de vueltas: alternar normalización/progreso/diferencia no
        # repite la petición HTTP. Se invalida al cambiar de sesión.
        self._cache_vueltas: dict[tuple, dict] = {}
        self._sesion_id: str | None = None

        # WebSocket de telemetria (sesiones grabadas)
        self._socket_telemetria = QWebSocket()
        self._socket_telemetria.connected.connect(self._on_conectado_telemetria)
        self._socket_telemetria.disconnected.connect(self._on_desconectado_telemetria)
        self._socket_telemetria.textMessageReceived.connect(self._on_mensaje)
        self._socket_telemetria.binaryMessageReceived.connect(self._on_binario)
        self._socket_telemetria.errorOccurred.connect(self._on_error_telemetria)
        self._cerrado_telemetria = False
        self._ultima_cabecera: dict | None = None

        # WebSocket de captura viva (/api/vivo/stream)
        self._socket_vivo = QWebSocket()
        self._socket_vivo.connected.connect(self._on_conectado_vivo)
        self._socket_vivo.disconnected.connect(self._on_desconectado_vivo)
        self._socket_vivo.textMessageReceived.connect(self._on_mensaje_vivo)
        self._socket_vivo.errorOccurred.connect(self._on_error_vivo)
        self._cerrado_vivo = False

    # ------------------------------------------------------------- Caché local
    def _registrar_sesion(self, datos: object) -> None:
        """Recuerda la sesión activa y limpia la caché si ha cambiado."""
        if not isinstance(datos, dict):
            return
        activa = datos.get("id") or datos.get("activa") or datos.get("nombre")
        if activa is None and "activa" in datos:
            activa = ""
        identificador = str(activa) if activa else None
        if identificador != self._sesion_id:
            self._sesion_id = identificador
            self._cache_vueltas.clear()

    @staticmethod
    def _clave_vuelta(
        sesion: str | None,
        lap: int,
        canales: str | list[str] | tuple[str, ...] | None,
        crudo: bool,
        max_puntos: int,
    ) -> tuple:
        if canales is None:
            lista: tuple[str, ...] = ()
        elif isinstance(canales, str):
            lista = tuple(c.strip() for c in canales.split(",") if c.strip())
        else:
            lista = tuple(canales)
        return (sesion or "", int(lap), lista, bool(crudo), int(max_puntos))

    def _vuelta_cacheada(self, clave: tuple, senal) -> bool:
        """Emite la vuelta ya descargada; devuelve si hubo acierto."""
        datos = self._cache_vueltas.get(clave)
        if datos is None:
            return False
        senal.emit(datos)
        return True

    # ------------------------------------------------------------------ REST utilitario
    def _get(self, path: str) -> object:
        resp = self._cliente.get(f"{self.base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, cuerpo: dict | None = None) -> object:
        resp = self._cliente.post(f"{self.base_url}{path}", json=cuerpo or {})
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> object:
        resp = self._cliente.delete(f"{self.base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def _ejecutar(
        self,
        fn: Callable[[], object],
        senal_exito: Signal,
        senal_error: Signal,
    ) -> None:
        self._pool.start(_TareaRest(fn, senal_exito, senal_error))

    # ------------------------------------------------------------------ REST - salud
    def salud(self) -> None:
        """Consulta GET /health (backend vivo?)."""
        self._ejecutar(self._get_salud, self.salud_recibida, self.error_salud)

    def _get_salud(self) -> dict:
        return self._get("/health")

    # ------------------------------------------------------------------ REST - sesiones
    def sesiones(self) -> None:
        """Consulta GET /api/sesiones (lista de CSV disponibles y sesion activa)."""
        self._ejecutar(self._get_sesiones, self.sesiones_recibidas, self.error_sesiones)

    def _get_sesiones(self) -> dict:
        datos = self._get("/api/sesiones")
        self._registrar_sesion(datos)
        return datos

    def sesion_activa(self) -> None:
        """Consulta GET /api/sesiones/activa."""
        self._ejecutar(
            self._get_sesion_activa,
            self.sesion_activa_recibida,
            self.error_sesion_activa,
        )

    def _get_sesion_activa(self) -> dict:
        datos = self._get("/api/sesiones/activa")
        self._registrar_sesion(datos)
        return datos

    def cargar_sesion(self, nombre: str) -> None:
        """POST /api/sesiones/cargar con {"nombre": nombre}."""

        def _post() -> dict:
            datos = self._post("/api/sesiones/cargar", {"nombre": nombre})
            self._registrar_sesion(datos)
            return datos

        self._ejecutar(_post, self.sesion_activa_recibida, self.error_sesion_activa)

    # ------------------------------------------------------------------ REST - telemetria
    def canales(self) -> None:
        """Consulta GET /api/telemetria/canales."""
        self._ejecutar(self._get_canales, self.canales_recibidos, self.error_canales)

    def _get_canales(self) -> dict:
        return self._get("/api/telemetria/canales")

    def vuelta(self, lap: int, canales: str | None = None, crudo: bool = False, max_puntos: int = 20000) -> None:
        """Consulta GET /api/telemetria/vuelta/{lap} (con caché local)."""
        clave = self._clave_vuelta(
            self._sesion_id, lap, canales, crudo, max_puntos
        )
        if self._vuelta_cacheada(clave, self.vuelta_recibida):
            return

        def _get() -> dict:
            params: dict = {"crudo": str(crudo).lower(), "max_puntos": max_puntos}
            if canales:
                params["canales"] = canales
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            datos = self._get(f"/api/telemetria/vuelta/{lap}?{qs}")
            self._cache_vueltas[clave] = datos
            return datos

        self._ejecutar(_get, self.vuelta_recibida, self.error_vuelta)

    def vuelta_comparar(
        self,
        lap: int,
        canales: list[str] | tuple[str, ...] | str,
        crudo: bool = False,
        max_puntos: int = 20000,
    ) -> None:
        """Consulta varias señales de una vuelta para el comparador (caché local)."""
        lista = canales if isinstance(canales, str) else ",".join(canales)
        clave = self._clave_vuelta(self._sesion_id, lap, canales, crudo, max_puntos)
        if self._vuelta_cacheada(clave, self.vuelta_comparar_recibida):
            return

        def _get() -> dict:
            params: dict = {
                "canales": lista,
                "crudo": str(crudo).lower(),
                "max_puntos": max_puntos,
            }
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            datos = self._get(f"/api/telemetria/vuelta/{lap}?{qs}")
            self._cache_vueltas[clave] = datos
            return datos

        self._ejecutar(
            _get, self.vuelta_comparar_recibida, self.error_vuelta_comparar
        )

    def stint(self, canales: str | None = None, crudo: bool = False, max_puntos: int = 20000) -> None:
        """Consulta GET /api/telemetria/stint (stint completo con downsampling)."""

        def _get() -> dict:
            params: dict = {"crudo": str(crudo).lower(), "max_puntos": max_puntos}
            if canales:
                params["canales"] = canales
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            return self._get(f"/api/telemetria/stint?{qs}")

        self._ejecutar(_get, self.stint_recibido, self.error_stint)

    def espectro(self, canal: str, lap: int | None = None, nperseg: int | None = None) -> None:
        """Consulta GET /api/telemetria/espectro."""

        def _get() -> dict:
            params: dict = {}
            if lap is not None:
                params["lap"] = lap
            if nperseg is not None:
                params["nperseg"] = nperseg
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            ruta = f"/api/telemetria/espectro?canal={canal}"
            if qs:
                ruta += "&" + qs
            return self._get(ruta)

        self._ejecutar(_get, self.espectro_recibido, self.error_espectro)

    # ------------------------------------------------------------------ REST - modelos
    def kalman(self, q_nivel: float | None = None, q_pendiente: float | None = None,
               r: float | None = None, monotono: bool | None = None) -> None:
        """POST /api/modelos/kalman/estimar."""

        def _post() -> dict:
            cuerpo: dict = {}
            if q_nivel is not None:
                cuerpo["q_nivel"] = q_nivel
            if q_pendiente is not None:
                cuerpo["q_pendiente"] = q_pendiente
            if r is not None:
                cuerpo["r"] = r
            if monotono is not None:
                cuerpo["monotono"] = monotono
            return self._post("/api/modelos/kalman/estimar", cuerpo)

        self._ejecutar(_post, self.kalman_recibido, self.error_kalman)

    def ridge(self, alpha: float | None = None, excluir: list[str] | None = None) -> None:
        """POST /api/modelos/ridge/ajustar."""

        def _post() -> dict:
            cuerpo: dict = {}
            if alpha is not None:
                cuerpo["alpha"] = alpha
            if excluir is not None:
                cuerpo["excluir"] = excluir
            return self._post("/api/modelos/ridge/ajustar", cuerpo)

        self._ejecutar(_post, self.ridge_recibido, self.error_ridge)

    def robustez(self, snr_db: list[float] | None = None) -> None:
        """POST /api/modelos/robustez (MAE vs ruido inyectado)."""

        def _post() -> dict:
            cuerpo: dict = {}
            if snr_db is not None:
                cuerpo["snr_db"] = snr_db
            return self._post("/api/modelos/robustez", cuerpo)

        self._ejecutar(_post, self.robustez_recibida, self.error_robustez)

    def sensores(self, caidos: list[dict] | None = None) -> None:
        """POST /api/modelos/sensores (MAE al desconectar canales)."""

        def _post() -> dict:
            cuerpo: dict = {}
            if caidos is not None:
                cuerpo["caidos"] = caidos
            return self._post("/api/modelos/sensores", cuerpo)

        self._ejecutar(_post, self.sensores_recibidos, self.error_sensores)

    def features(self) -> None:
        """Consulta GET /api/modelos/features (features numericas del modelo)."""
        self._ejecutar(self._get_features, self.features_recibidas, self.error_features)

    def _get_features(self) -> list:
        datos = self._get("/api/modelos/features")
        return datos.get("features", [])

    def dispersion(self, x: str, y: str = "degradacion") -> None:
        """Consulta GET /api/modelos/dispersion?x=...&y=..."""

        def _get() -> dict:
            return self._get(f"/api/modelos/dispersion?x={x}&y={y}")

        self._ejecutar(_get, self.dispersion_recibida, self.error_dispersion)

    def correlacion(self, features: list[str] | None = None) -> None:
        """Consulta GET /api/modelos/correlacion?features=a,b,c"""

        def _get() -> dict:
            if features:
                return self._get("/api/modelos/correlacion?features=" + ",".join(features))
            return self._get("/api/modelos/correlacion")

        self._ejecutar(_get, self.correlacion_recibida, self.error_correlacion)

    # ------------------------------------------------------------------ REST - configuracion
    def config(self) -> None:
        """Consulta GET /api/config."""
        self._ejecutar(self._get_config, self.config_recibida, self.error_config)

    def _get_config(self) -> dict:
        return self._get("/api/config")

    def guardar_config(self, overrides: dict) -> None:
        """POST /api/config con overrides anidados."""

        def _post() -> dict:
            return self._post("/api/config", overrides)

        self._ejecutar(_post, self.config_recibida, self.error_config)

    def reiniciar_config(self) -> None:
        """DELETE /api/config (valores de fabrica)."""

        def _delete() -> dict:
            return self._delete("/api/config")

        self._ejecutar(_delete, self.config_recibida, self.error_config)

    # ------------------------------------------------------------------ REST - vivo
    def vivo_iniciar(self, fuente: str = "seco", archivo: str | None = None,
                     ritmo_hz: float | None = None, bucle: bool = False) -> None:
        """POST /api/vivo/iniciar."""

        def _post() -> dict:
            cuerpo: dict = {"fuente": fuente, "bucle": bucle}
            if archivo is not None:
                cuerpo["archivo"] = archivo
            if ritmo_hz is not None:
                cuerpo["ritmo_hz"] = ritmo_hz
            return self._post("/api/vivo/iniciar", cuerpo)

        self._ejecutar(_post, self.vivo_iniciado, self.error_vivo_iniciar)

    def vivo_detener(self) -> None:
        """POST /api/vivo/detener."""

        def _post() -> dict:
            return self._post("/api/vivo/detener", {})

        self._ejecutar(_post, self.vivo_detenido, self.error_vivo_detener)

    def vivo_estado(self) -> None:
        """Consulta GET /api/vivo/estado."""
        self._ejecutar(self._get_vivo_estado, self.vivo_estado_recibido, self.error_vivo_estado)

    def _get_vivo_estado(self) -> dict:
        return self._get("/api/vivo/estado")

    def vivo_ventana(self, n: int | None = None, canales: list[str] | None = None) -> None:
        """Consulta GET /api/vivo/ventana (ultimas N muestras para osciloscopio)."""

        def _get() -> dict:
            params: dict = {}
            if n is not None:
                params["n"] = n
            if canales:
                params["canales"] = ",".join(canales)
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            ruta = "/api/vivo/ventana"
            if qs:
                ruta += "?" + qs
            return self._get(ruta)

        self._ejecutar(_get, self.vivo_ventana_recibida, self.error_vivo_ventana)

    def vivo_sesiones(self) -> None:
        """Consulta GET /api/vivo/sesiones (capturas guardadas)."""
        self._ejecutar(self._get_vivo_sesiones, self.vivo_sesiones_recibidas, self.error_vivo_sesiones)

    def _get_vivo_sesiones(self) -> list:
        datos = self._get("/api/vivo/sesiones")
        return datos.get("sesiones", [])

    def vivo_layout(self) -> None:
        """Consulta GET /api/vivo/layout (¿AC esta publicando?)."""
        self._ejecutar(self._get_vivo_layout, self.vivo_layout_recibido, self.error_vivo_layout)

    def _get_vivo_layout(self) -> dict:
        return self._get("/api/vivo/layout")

    # ------------------------------------------------------------------ WebSocket - telemetria
    def conectar_telemetria(self) -> None:
        """Abre el WebSocket /ws/telemetria."""
        self._cerrado_telemetria = False
        self.estado_telemetria.emit("conectando")
        self._socket_telemetria.open(self.ws_url)  # type: ignore[arg-type]

    def desconectar_telemetria(self) -> None:
        """Cierra el WebSocket de telemetria de forma intencionada."""
        self._cerrado_telemetria = True
        self._socket_telemetria.close()

    def _on_conectado_telemetria(self) -> None:
        self.estado_telemetria.emit("conectado")

    def _on_desconectado_telemetria(self) -> None:
        if not self._cerrado_telemetria:
            self.estado_telemetria.emit("desconectado")

    def _on_error_telemetria(self, error) -> None:
        self.estado_telemetria.emit(f"error: {error}")

    def _on_mensaje(self, mensaje: str) -> None:
        """Recibe un mensaje JSON del WebSocket de telemetria."""
        try:
            datos = json.loads(mensaje)
        except ValueError:
            return
        # Si es una cabecera de trama binaria, la guardamos para asociarla
        # con el payload binario que llega justo despues.
        if datos.get("tipo") == "trama" and "canales" in datos and "n_muestras" in datos:
            self._ultima_cabecera = datos
        else:
            self.mensaje_telemetria.emit(datos)

    def _on_binario(self, datos_binarios: bytes) -> None:
        """Decodifica una trama binaria Float32 little-endian con cabecera JSON.

        Formato: cabecera JSON enviada por texto (guardada en _ultima_cabecera)
        seguida de un payload Float32 con forma [n_canales, n_muestras].
        """
        if self._ultima_cabecera is None:
            return
        try:
            canales = self._ultima_cabecera.get("canales", [])
            n_muestras = int(self._ultima_cabecera.get("n_muestras", 0))
            flotantes = np.frombuffer(datos_binarios, dtype=np.float32)
            filas = []
            for i, canal in enumerate(canales):
                inicio = i * n_muestras
                fin = inicio + n_muestras
                filas.append({
                    "canal": canal,
                    "valores": flotantes[inicio:fin].tolist(),
                })
            self.mensaje_binario_telemetria.emit({
                "tipo": "trama_binaria",
                "canales": canales,
                "n_muestras": n_muestras,
                "filas": filas,
            })
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._ultima_cabecera = None

    # ------------------------------------------------------------------ WebSocket - vivo
    def conectar_vivo(self) -> None:
        """Abre el WebSocket /api/vivo/stream (captura en vivo ~10 Hz)."""
        self._cerrado_vivo = False
        self.estado_vivo.emit("conectando")
        ws_url_vivo = self.base_url.replace("http", "ws") + "/api/vivo/stream"
        self._socket_vivo.open(ws_url_vivo)  # type: ignore[arg-type]

    def desconectar_vivo(self) -> None:
        """Cierra el WebSocket de vivo de forma intencionada."""
        self._cerrado_vivo = True
        self._socket_vivo.close()

    def _on_conectado_vivo(self) -> None:
        self.estado_vivo.emit("conectado")

    def _on_desconectado_vivo(self) -> None:
        if not self._cerrado_vivo:
            self.estado_vivo.emit("desconectado")

    def _on_error_vivo(self, error) -> None:
        self.estado_vivo.emit(f"error: {error}")

    def _on_mensaje_vivo(self, mensaje: str) -> None:
        """Recibe un mensaje JSON del WebSocket de vivo (tipo "vivo")."""
        try:
            datos = json.loads(mensaje)
        except ValueError:
            return
        self.mensaje_vivo.emit(datos)

    def cerrar(self) -> None:
        """Libera recursos (HTTP client y ambos WebSockets).

        Se espera a las tareas REST en vuelo antes de cerrar el cliente httpx:
        si no, una peticion lenta puede emitir su senal cuando el QObject ya
        fue destruido y Qt imprime 'Signal source has been deleted'.
        """
        self.desconectar_telemetria()
        self.desconectar_vivo()
        self._pool.waitForDone(3000)
        self._cliente.close()
