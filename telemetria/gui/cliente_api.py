"""Cliente de la API para la interfaz de escritorio (PySide6).

REST con :class:`QNetworkAccessManager` (asíncrono, sin hilos propios) y los dos
WebSockets con :class:`QWebSocket`. Emite señales Qt para que la GUI se
actualice sin bloquearse.

🐴: antes había un ``httpx.Client`` sincrónico dentro de un ``QThreadPool``,
un ``_get``/``_post``/``_delete`` por método y una tarea por endpoint. Un solo
``_pedir`` con QNetworkAccessManager cubre lo mismo con Qt nativo.

Endpoints cubiertos:
    GET  /health, /api/sesiones, /api/sesiones/activa
    POST /api/sesiones/cargar, /api/telemetria/vuelta/{lap}, /api/telemetria/espectro
    POST /api/modelos/{kalman/estimar,ridge/ajustar,robustez,sensores}
    GET  /api/modelos/features, /api/config, POST/DELETE /api/config
    POST /api/vivo/{iniciar,detener}, GET /api/vivo/{estado,ventana,sesiones,layout}
    WS   /ws/telemetria, /api/vivo/stream
"""

from __future__ import annotations

import json

import numpy as np
from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket


def _entregar(destino, valor) -> None:
    """Emite una señal Qt o llama un callback; los dos caben en `_pedir`."""
    if hasattr(destino, "emit"):
        destino.emit(valor)
    else:
        destino(valor)


class ApiClient(QObject):
    """Cliente REST + WebSocket de la API de Telemetry Analytics."""

    # --- REST ---
    salud_recibida = Signal(dict)
    error_salud = Signal(str)
    sesiones_recibidas = Signal(dict)
    error_sesiones = Signal(str)
    sesion_activa_recibida = Signal(dict)
    error_sesion_activa = Signal(str)
    canales_recibidos = Signal(dict)
    error_canales = Signal(str)
    vuelta_recibida = Signal(dict)
    error_vuelta = Signal(str)
    # El comparador usa su propia señal: una petición no pisa el detalle.
    vuelta_comparar_recibida = Signal(dict)
    error_vuelta_comparar = Signal(str)
    espectro_recibido = Signal(dict)
    error_espectro = Signal(str)
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
    config_recibida = Signal(dict)
    error_config = Signal(str)
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

    # Observación mínima para diagnósticos (ruta, código HTTP).
    peticion = Signal(str, int)

    # --- WebSocket ---
    mensaje_telemetria = Signal(dict)
    mensaje_binario_telemetria = Signal(dict)
    estado_telemetria = Signal(str)
    mensaje_vivo = Signal(dict)
    estado_vivo = Signal(str)

    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http", "ws") + "/ws/telemetria"

        self._red = QNetworkAccessManager(self)
        self._red.finished.connect(self._on_finished)
        self._pendientes: dict[QNetworkReply, tuple] = {}

        # Caché de vueltas: alternar normalización/progreso/diferencia no repite
        # la petición HTTP. Se invalida al cambiar de sesión.
        self._cache_vueltas: dict[tuple, dict] = {}
        self._sesion_id: str | None = None

        self._socket_telemetria = QWebSocket()
        self._socket_telemetria.connected.connect(self._on_conectado_telemetria)
        self._socket_telemetria.disconnected.connect(self._on_desconectado_telemetria)
        self._socket_telemetria.textMessageReceived.connect(self._on_mensaje)
        self._socket_telemetria.binaryMessageReceived.connect(self._on_binario)
        self._socket_telemetria.errorOccurred.connect(self._on_error_telemetria)
        self._cerrado_telemetria = False
        self._ultima_cabecera: dict | None = None

        self._socket_vivo = QWebSocket()
        self._socket_vivo.connected.connect(self._on_conectado_vivo)
        self._socket_vivo.disconnected.connect(self._on_desconectado_vivo)
        self._socket_vivo.textMessageReceived.connect(self._on_mensaje_vivo)
        self._socket_vivo.errorOccurred.connect(self._on_error_vivo)
        self._cerrado_vivo = False

    # ------------------------------------------------------------- Caché local
    def _registrar_sesion(self, datos: object) -> None:
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
    def _clave_vuelta(sesion, lap: int, canales, crudo: bool, max_puntos: int) -> tuple:
        if canales is None:
            lista: tuple[str, ...] = ()
        elif isinstance(canales, str):
            lista = tuple(c.strip() for c in canales.split(",") if c.strip())
        else:
            lista = tuple(canales)
        return (sesion or "", int(lap), lista, bool(crudo), int(max_puntos))

    def _vuelta_cacheada(self, clave: tuple, senal) -> bool:
        datos = self._cache_vueltas.get(clave)
        if datos is None:
            return False
        senal.emit(datos)
        return True

    # ------------------------------------------------------------ REST genérico
    def _pedir(
        self,
        ruta: str,
        exito,
        error,
        *,
        metodo: str = "GET",
        cuerpo: dict | None = None,
        transform=None,
    ) -> None:
        """Lanza una petición y enruta la respuesta a las señales dadas."""
        peticion = QNetworkRequest(QUrl(self.base_url + ruta))
        datos = QByteArray()
        if cuerpo is not None:
            peticion.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
            )
            datos = QByteArray(json.dumps(cuerpo).encode("utf-8"))
        fn = {
            "GET": self._red.get,
            "POST": self._red.post,
            "DELETE": self._red.deleteResource,
        }[metodo]
        reply = fn(peticion) if metodo != "POST" else fn(peticion, datos)
        self._pendientes[reply] = (exito, error, transform)

    def _on_finished(self, reply: QNetworkReply) -> None:
        exito, error, transform = self._pendientes.pop(reply, (None, None, None))
        estado = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        self.peticion.emit(reply.url().path(), estado)
        if exito is not None:
            if estado < 200 or estado >= 300:
                _entregar(error, f"HTTP {estado}: {reply.errorString()}")
            else:
                try:
                    texto = bytes(reply.readAll()).decode("utf-8")
                    datos = json.loads(texto) if texto.strip() else {}
                    _entregar(exito, transform(datos) if transform else datos)
                except (ValueError, UnicodeDecodeError) as exc:
                    _entregar(error, f"Respuesta no válida: {exc}")
        reply.deleteLater()

    # ------------------------------------------------------------------ REST
    def salud(self) -> None:
        self._pedir("/health", self.salud_recibida, self.error_salud)

    def sesiones(self) -> None:
        def guardar(datos):
            self._registrar_sesion(datos)
            self.sesiones_recibidas.emit(datos)

        self._pedir("/api/sesiones", guardar, self.error_sesiones)

    def sesion_activa(self) -> None:
        def guardar(datos):
            self._registrar_sesion(datos)
            self.sesion_activa_recibida.emit(datos)

        self._pedir("/api/sesiones/activa", guardar, self.error_sesion_activa)

    def cargar_sesion(self, nombre: str) -> None:
        self._pedir(
            "/api/sesiones/cargar",
            self.sesion_activa_recibida,
            self.error_sesion_activa,
            metodo="POST",
            cuerpo={"nombre": nombre},
        )

    def canales(self) -> None:
        self._pedir("/api/telemetria/canales", self.canales_recibidos, self.error_canales)

    @staticmethod
    def _qs(params: dict) -> str:
        return "&".join(f"{k}={v}" for k, v in params.items() if v is not None)

    def _pedir_vuelta(self, ruta: str, clave: tuple, exito, error) -> None:
        def guardar(datos):
            self._cache_vueltas[clave] = datos
            exito.emit(datos)

        self._pedir(ruta, guardar, error)

    def vuelta(
        self, lap: int, canales: str | None = None, crudo: bool = False, max_puntos: int = 20000
    ) -> None:
        clave = self._clave_vuelta(self._sesion_id, lap, canales, crudo, max_puntos)
        if self._vuelta_cacheada(clave, self.vuelta_recibida):
            return
        params = {"canales": canales, "crudo": str(crudo).lower(), "max_puntos": max_puntos}
        ruta = f"/api/telemetria/vuelta/{lap}?{self._qs(params)}"
        self._pedir_vuelta(ruta, clave, self.vuelta_recibida, self.error_vuelta)

    def vuelta_comparar(
        self,
        lap: int,
        canales: list[str] | tuple[str, ...] | str,
        crudo: bool = False,
        max_puntos: int = 20000,
    ) -> None:
        lista = canales if isinstance(canales, str) else ",".join(canales)
        clave = self._clave_vuelta(self._sesion_id, lap, lista, crudo, max_puntos)
        if self._vuelta_cacheada(clave, self.vuelta_comparar_recibida):
            return
        params = {"canales": lista, "crudo": str(crudo).lower(), "max_puntos": max_puntos}
        ruta = f"/api/telemetria/vuelta/{lap}?{self._qs(params)}"
        self._pedir_vuelta(
            ruta, clave, self.vuelta_comparar_recibida, self.error_vuelta_comparar
        )

    def espectro(self, canal: str, lap: int | None = None, nperseg: int | None = None) -> None:
        params = {"canal": canal, "lap": lap, "nperseg": nperseg}
        self._pedir(
            f"/api/telemetria/espectro?{self._qs(params)}",
            self.espectro_recibido,
            self.error_espectro,
        )

    def kalman(self, q_nivel=None, q_pendiente=None, r=None, monotono=None) -> None:
        cuerpo = {
            k: v
            for k, v in (
                ("q_nivel", q_nivel),
                ("q_pendiente", q_pendiente),
                ("r", r),
                ("monotono", monotono),
            )
            if v is not None
        }
        self._pedir(
            "/api/modelos/kalman/estimar",
            self.kalman_recibido,
            self.error_kalman,
            metodo="POST",
            cuerpo=cuerpo,
        )

    def ridge(self, alpha=None, excluir: list[str] | None = None) -> None:
        cuerpo = {k: v for k, v in (("alpha", alpha), ("excluir", excluir)) if v is not None}
        self._pedir(
            "/api/modelos/ridge/ajustar",
            self.ridge_recibido,
            self.error_ridge,
            metodo="POST",
            cuerpo=cuerpo,
        )

    def robustez(self, snr_db: list[float] | None = None) -> None:
        self._pedir(
            "/api/modelos/robustez",
            self.robustez_recibida,
            self.error_robustez,
            metodo="POST",
            cuerpo={} if snr_db is None else {"snr_db": snr_db},
        )

    def sensores(
        self,
        caidos: list[dict] | None = None,
        modo: str | None = None,
    ) -> None:
        cuerpo: dict = {}
        if caidos is not None:
            cuerpo["caidos"] = caidos
        if modo is not None:
            cuerpo["modo"] = modo
        self._pedir(
            "/api/modelos/sensores",
            self.sensores_recibidos,
            self.error_sensores,
            metodo="POST",
            cuerpo=cuerpo,
        )

    def features(self) -> None:
        self._pedir(
            "/api/modelos/features",
            self.features_recibidas,
            self.error_features,
            transform=lambda datos: datos.get("features", []),
        )

    def config(self) -> None:
        self._pedir("/api/config", self.config_recibida, self.error_config)

    def guardar_config(self, overrides: dict) -> None:
        self._pedir(
            "/api/config",
            self.config_recibida,
            self.error_config,
            metodo="POST",
            cuerpo=overrides,
        )

    def reiniciar_config(self) -> None:
        self._pedir(
            "/api/config",
            self.config_recibida,
            self.error_config,
            metodo="DELETE",
        )

    def vivo_iniciar(
        self, fuente: str = "seco", archivo: str | None = None,
        ritmo_hz: float | None = None, bucle: bool = False,
    ) -> None:
        cuerpo = {"fuente": fuente, "bucle": bucle}
        if archivo is not None:
            cuerpo["archivo"] = archivo
        if ritmo_hz is not None:
            cuerpo["ritmo_hz"] = ritmo_hz
        self._pedir(
            "/api/vivo/iniciar",
            self.vivo_iniciado,
            self.error_vivo_iniciar,
            metodo="POST",
            cuerpo=cuerpo,
        )

    def vivo_detener(self) -> None:
        self._pedir(
            "/api/vivo/detener",
            self.vivo_detenido,
            self.error_vivo_detener,
            metodo="POST",
            cuerpo={},
        )

    def vivo_estado(self) -> None:
        self._pedir("/api/vivo/estado", self.vivo_estado_recibido, self.error_vivo_estado)

    def vivo_ventana(self, n: int | None = None, canales: list[str] | None = None) -> None:
        params = {"n": n, "canales": ",".join(canales) if canales else None}
        self._pedir(
            f"/api/vivo/ventana?{self._qs(params)}",
            self.vivo_ventana_recibida,
            self.error_vivo_ventana,
        )

    def vivo_sesiones(self) -> None:
        self._pedir(
            "/api/vivo/sesiones",
            self.vivo_sesiones_recibidas,
            self.error_vivo_sesiones,
            transform=lambda datos: datos.get("sesiones", []),
        )

    def vivo_layout(self) -> None:
        self._pedir("/api/vivo/layout", self.vivo_layout_recibido, self.error_vivo_layout)

    # -------------------------------------------------------- WebSocket - telemetría
    def conectar_telemetria(self) -> None:
        self._cerrado_telemetria = False
        self.estado_telemetria.emit("conectando")
        self._socket_telemetria.open(self.ws_url)  # type: ignore[arg-type]

    def desconectar_telemetria(self) -> None:
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
        try:
            datos = json.loads(mensaje)
        except ValueError:
            return
        if datos.get("tipo") == "trama" and "canales" in datos and "n_muestras" in datos:
            self._ultima_cabecera = datos
        else:
            self.mensaje_telemetria.emit(datos)

    def _on_binario(self, datos_binarios: bytes) -> None:
        """Decodifica Float32 little-endian con forma [n_canales, n_muestras]."""
        if self._ultima_cabecera is None:
            return
        try:
            canales = self._ultima_cabecera.get("canales", [])
            n_muestras = int(self._ultima_cabecera.get("n_muestras", 0))
            flotantes = np.frombuffer(datos_binarios, dtype=np.float32)
            filas = []
            for i, canal in enumerate(canales):
                inicio = i * n_muestras
                filas.append({
                    "canal": canal,
                    "valores": flotantes[inicio : inicio + n_muestras].tolist(),
                })
            self.mensaje_binario_telemetria.emit({
                "tipo": "trama_binaria",
                "canales": canales,
                "n_muestras": n_muestras,
                "filas": filas,
            })
        except Exception:  # noqa: BLE001 - trama malformada, se descarta
            pass
        finally:
            self._ultima_cabecera = None

    # ------------------------------------------------------------ WebSocket - vivo
    def conectar_vivo(self) -> None:
        self._cerrado_vivo = False
        self.estado_vivo.emit("conectando")
        self._socket_vivo.open(  # type: ignore[arg-type]
            self.base_url.replace("http", "ws") + "/api/vivo/stream"
        )

    def desconectar_vivo(self) -> None:
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
        try:
            datos = json.loads(mensaje)
        except ValueError:
            return
        self.mensaje_vivo.emit(datos)

    def cerrar(self) -> None:
        """Libera los WebSockets; el manager vive como hijo de este QObject."""
        self.desconectar_telemetria()
        self.desconectar_vivo()
