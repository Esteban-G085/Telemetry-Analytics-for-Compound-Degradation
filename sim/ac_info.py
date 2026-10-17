"""Acceso a la memoria compartida de Assetto Corsa (fuente F3, Etapa 3).

AC publica tres paginas en la memoria compartida de Windows:

  - ``Local\\acpmf_physics``  -> canales por rueda (slip, carga, presion, ...)
  - ``Local\\acpmf_graphics`` -> estado de la sesion (vuelta completada, ...)
  - ``Local\\acpmf_static``   -> contexto (coche, pista, limites)

Se abren con ``mmap`` en modo lectura usando el nombre como *tag* (crea o abre
la seccion existente). El layout se declara con ``ctypes`` y ``_pack_ = 4``.

IMPORTANTE: el orden de los campos varia entre builds/mods. La struct declara
solo hasta los campos que usamos (``tyreCoreTemperature`` en physics,
``completedLaps`` en graphics) para que los offsets relevantes sean los
documentados; ``verificar_layout`` comprueba que los valores caigan en rangos
plausibles antes de fiarse de ellos.

Este modulo no importa nada del resto del proyecto: se puede usar suelto para
diagnosticar si AC esta publicando datos.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import c_float, c_int, c_wchar
from dataclasses import dataclass

from src.config import RUEDAS

PREFIJO_DEFECTO = "Local\\"

FILE_MAP_READ = 0x0004

# El volante de AC viene en radianes (rango ~ +-0.5 rad). Se normaliza a [-1, 1]
# dividiendo por este maximo (a confirmar contra el juego).
ANGULO_MAX_RAD = 0.5

if sys.platform == "win32":  # pragma: no cover - dependiente de plataforma
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.OpenFileMappingW.restype = ctypes.c_void_p
    _KERNEL32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    _KERNEL32.MapViewOfFile.restype = ctypes.c_void_p
    _KERNEL32.MapViewOfFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_size_t,
    ]
    _KERNEL32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    _KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
else:  # pragma: no cover
    _KERNEL32 = None


class SPageFilePhysics(ctypes.Structure):
    """Cabecera de ``acpmf_physics`` hasta las temperaturas de nucleo."""

    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("gas", c_float),
        ("brake", c_float),
        ("fuel", c_float),
        ("gear", c_int),
        ("rpms", c_int),
        ("steerAngle", c_float),
        ("speedKmh", c_float),
        ("velocity", c_float * 3),
        ("accG", c_float * 3),
        ("wheelSlip", c_float * 4),
        ("wheelLoad", c_float * 4),
        ("wheelsPressure", c_float * 4),
        ("wheelAngularSpeed", c_float * 4),
        ("tyreWear", c_float * 4),
        ("tyreDirtyLevel", c_float * 4),
        ("tyreCoreTemperature", c_float * 4),
    ]


class SPageFileGraphics(ctypes.Structure):
    """Cabecera de ``acpmf_graphics`` hasta ``carCoordinates``."""

    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("status", c_int),
        ("session", c_int),
        ("currentTime", c_float),
        ("lastTime", c_float),
        ("bestTime", c_float),
        ("split", c_float),
        ("completedLaps", c_int),
        ("position", c_int),
        ("iCurrentTime", c_int),
        ("iLastTime", c_int),
        ("iBestTime", c_int),
        ("sessionTimeLeft", c_float),
        ("distanceTraveled", c_float),
        ("isInPit", c_int),
        ("currentSectorIndex", c_int),
        ("lastSectorTime", c_int),
        ("numberOfLaps", c_int),
        ("carCoordinates", c_float * 3),
    ]


class SPageFileStatic(ctypes.Structure):
    """Cabecera de ``acpmf_static`` hasta los limites del motor."""

    _pack_ = 4
    _fields_ = [
        ("smVersion", c_wchar * 15),
        ("acVersion", c_wchar * 15),
        ("numberOfSessions", c_int),
        ("numCars", c_int),
        ("carModel", c_wchar * 33),
        ("track", c_wchar * 33),
        ("playerName", c_wchar * 33),
        ("surname", c_wchar * 33),
        ("maxRpm", c_int),
        ("maxFuel", c_float),
        ("fuelPerLap", c_float),
    ]


PAGINAS = {
    "physics": ("acpmf_physics", SPageFilePhysics),
    "graphics": ("acpmf_graphics", SPageFileGraphics),
    "static": ("acpmf_static", SPageFileStatic),
}


class MemoriaAC:
    """Abre las paginas de AC y expone lecturas tipadas.

    Uso::

        with MemoriaAC() as mem:
            if mem.disponible:
                muestra = mem.leer_muestra()

    Detecta si AC esta publicando datos: si las secciones no existen (juego
    cerrado) ``disponible`` queda en ``False`` y ``error`` explica por que. No
    crea las secciones si no existen (a diferencia de ``mmap`` con ``tagname``).
    """

    def __init__(self, prefijo: str = PREFIJO_DEFECTO):
        self.prefijo = prefijo
        self.disponible = False
        self.error: str | None = None
        self._vistas: dict[str, tuple[int, int]] = {}  # clave -> (handle, ptr)
        self.fisica: SPageFilePhysics | None = None
        self.graficos: SPageFileGraphics | None = None
        self.estatico: SPageFileStatic | None = None

    # --- ciclo de vida ---
    def abrir(self) -> "MemoriaAC":
        if sys.platform != "win32" or _KERNEL32 is None:
            self.error = "La memoria compartida de AC solo existe en Windows"
            return self
        try:
            self.fisica = self._mapear("physics")
            self.graficos = self._mapear("graphics")
            self._mapear_estatico()
            self.disponible = True
        except (OSError, ValueError, TypeError) as exc:  # AC cerrado o pagina inexistente
            self.error = f"No se pudo abrir la memoria de AC: {exc}"
            self.cerrar()
        return self

    def _mapear(self, clave: str):
        nombre, tipo = PAGINAS[clave]
        completo = self.prefijo + nombre
        handle = _KERNEL32.OpenFileMappingW(FILE_MAP_READ, False, completo)
        if not handle:
            raise OSError(f"la seccion {completo} no existe (¿AC no esta en pista?)")
        ptr = _KERNEL32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
        if not ptr:
            _KERNEL32.CloseHandle(handle)
            raise OSError(f"MapViewOfFile fallo para {completo}")
        self._vistas[clave] = (handle, ptr)
        return tipo.from_address(ptr)

    def _mapear_estatico(self) -> None:
        # La pagina static es opcional: si falla, el resto sigue siendo util.
        try:
            self.estatico = self._mapear("static")
        except OSError:
            self.estatico = None

    def cerrar(self) -> None:
        for handle, ptr in self._vistas.values():
            try:
                _KERNEL32.UnmapViewOfFile(ptr)
            finally:
                _KERNEL32.CloseHandle(handle)
        self._vistas.clear()
        self.fisica = self.graficos = self.estatico = None
        self.disponible = False

    def __enter__(self) -> "MemoriaAC":
        return self.abrir()

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    # --- lectura ---
    @property
    def packet_id(self) -> int:
        if self.fisica is None:
            return -1
        return int(self.fisica.packetId)

    def esperar_packet(self, anterior: int, timeout_s: float = 0.1, paso_s: float = 0.0005) -> int:
        """Bloquea hasta que el ``packetId`` cambie (o vence el timeout)."""
        limite = time.perf_counter() + timeout_s
        pid = self.packet_id
        while pid == anterior and time.perf_counter() < limite:
            time.sleep(paso_s)
            pid = self.packet_id
        return pid

    def leer_muestra(self, ciclo: int | None = None) -> dict | None:
        """Una muestra del esquema del proyecto + extras (``grip_*``).

        Devuelve ``None`` si aun no hay paginas abiertas.
        """
        if not self.disponible or self.fisica is None:
            return None
        fis = self.fisica
        graf = self.graficos
        lap = int(graf.completedLaps) + 1 if graf is not None else 1

        muestra: dict = {
            "timestamp_s": float(ciclo) if ciclo is not None else time.perf_counter(),
            "packetId": int(fis.packetId),
            "lap": lap,
            "speed_kmh": float(fis.speedKmh),
            "throttle": float(fis.gas),
            "brake": float(fis.brake),
            "steering": _normalizar_angulo(float(fis.steerAngle)),
            "fuel_kg": float(fis.fuel),
        }
        for i, w in enumerate(RUEDAS):
            muestra[f"temp_core_c_{w}"] = float(fis.tyreCoreTemperature[i])
            muestra[f"pressure_psi_{w}"] = float(fis.wheelsPressure[i])
            muestra[f"wheel_slip_{w}"] = float(fis.wheelSlip[i])
            muestra[f"wheel_load_n_{w}"] = float(fis.wheelLoad[i])
            muestra[f"dirty_level_{w}"] = float(fis.tyreDirtyLevel[i]) / 10.0
            # Extra (fuera del esquema): grip/salud 0..1 del neumatico.
            muestra[f"grip_{w}"] = float(fis.tyreWear[i])
        return muestra

    def contexto(self) -> dict:
        est = self.estatico
        if est is None:
            return {}
        return {
            "carModel": str(est.carModel).split("\x00")[0],
            "track": str(est.track).split("\x00")[0],
            "maxRpm": int(est.maxRpm),
            "maxFuel": float(est.maxFuel),
        }


def _normalizar_angulo(rad: float) -> float:
    """Radianes -> [-1, 1] (recorte defensivo)."""
    x = rad / ANGULO_MAX_RAD
    return max(-1.0, min(1.0, x))


# --------------------------------------------------------------------------
# Verificacion de layout (paso 1 de la Etapa 3)
# --------------------------------------------------------------------------
@dataclass
class InformeLayout:
    disponible: bool
    packet_id: int
    checks: dict  # nombre -> (valor, ok)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.disponible and all(ok for _v, ok in self.checks.values())


def verificar_layout(ruta: str | None = None, muestras: int = 1) -> InformeLayout:
    """Lee unas muestras y comprueba rangos plausibles del layout."""
    del ruta  # reservado: permitiria leer un volcado de depuracion
    with MemoriaAC() as mem:
        if not mem.disponible:
            return InformeLayout(False, -1, {}, mem.error)
        muestra = mem.leer_muestra()
        if muestra is None:
            return InformeLayout(False, -1, {}, "sin datos")

        def rango(nombre: str, valor: float, lo: float, hi: float):
            return nombre, (round(valor, 4), lo <= valor <= hi)

        checks = dict(
            [
                rango("speed_kmh", muestra["speed_kmh"], 0.0, 400.0),
                rango("throttle", muestra["throttle"], 0.0, 1.001),
                rango("brake", muestra["brake"], 0.0, 1.001),
                rango("temp_core_c_fl", muestra["temp_core_c_fl"], 0.0, 250.0),
                rango("pressure_psi_fl", muestra["pressure_psi_fl"], 5.0, 60.0),
                rango("wheel_load_n_fl", muestra["wheel_load_n_fl"], -5000.0, 25000.0),
            ]
        )
        return InformeLayout(True, muestra["packetId"], checks)


if __name__ == "__main__":  # pragma: no cover - diagnostico manual
    info = verificar_layout()
    nombre = PAGINAS["physics"][0]
    if not info.disponible:
        print(f"AC no disponible ({nombre}): {info.error}")
    else:
        print(f"AC disponible, packetId={info.packet_id}, layout_ok={info.ok}")
        for clave, (valor, ok) in info.checks.items():
            print(f"  {'OK ' if ok else 'MAL'} {clave} = {valor}")
