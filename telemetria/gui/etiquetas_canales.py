"""Nombres comprensibles para las señales de telemetría.

La API devuelve nombres de columna (`wheel_slip_fl`, `temp_core_c_fr`, ...).
Están bien para el código, pero no explican nada a quien abre la ventana por
primera vez. Este módulo traduce solo la capa visual: las claves JSON no se
tocan.

`timestamp_s` es el eje temporal y `lap` es el agrupador de vueltas, así que
ninguno de los dos se ofrece como señal para dibujar.
"""

from __future__ import annotations

SENALES_NO_GRAFICABLES = frozenset({"timestamp_s", "lap"})

NOMBRES_BASE = {
    "speed_kmh": "Velocidad",
    "throttle": "Acelerador",
    "brake": "Freno",
    "steering": "Dirección",
    "fuel_kg": "Combustible",
}

PREFIJOS = (
    ("wheel_slip", "Deslizamiento"),
    ("temp_core_c", "Temperatura núcleo"),
    ("wheel_load_n", "Carga de rueda"),
    ("pressure_psi", "Presión"),
)

RUEDAS = {
    "fl": "FL (delantera izquierda)",
    "fr": "FR (delantera derecha)",
    "rl": "RL (trasera izquierda)",
    "rr": "RR (trasera derecha)",
}

UNIDADES = {
    "speed_kmh": "km/h",
    "fuel_kg": "kg",
    "temp_core_c": "°C",
    "wheel_load_n": "N",
    "pressure_psi": "psi",
}

# Entradas sin unidad física documentada. "mando" describe qué es el valor,
# sin inventar una unidad: en los CSV de prueba hay fuera de rango (por ejemplo
# throttle=-149), así que no afirmamos que sea siempre 0–1 ni un porcentaje.
UNIDADES_TEXTO = {
    "throttle": "mando",
    "brake": "mando",
    "steering": "mando",
    "wheel_slip": "ratio",
}


def es_graficable(canal: str) -> bool:
    """¿Tiene sentido dibujar esta columna como una señal?"""
    return canal not in SENALES_NO_GRAFICABLES


def filtrar_canales(canales: list[str] | tuple[str, ...]) -> list[str]:
    """Quita las columnas que son contexto, no señales."""
    return [c for c in canales if es_graficable(c)]


def _describir_nucleo(canal: str) -> tuple[str, str]:
    if canal in NOMBRES_BASE:
        return NOMBRES_BASE[canal], UNIDADES.get(canal, "")

    for prefijo, nombre in PREFIJOS:
        if canal == prefijo:
            return nombre, UNIDADES.get(prefijo, "")
        if canal.startswith(prefijo + "_"):
            sufijo = canal[len(prefijo) + 1 :]
            rueda = RUEDAS.get(sufijo, sufijo.upper())
            unidad = UNIDADES.get(prefijo, "")
            return f"{nombre} {rueda}", unidad
    return canal, ""


def etiqueta_canal(canal: str) -> str:
    """Nombre corto para combos, leyendas y títulos."""
    if canal == "timestamp_s":
        return "Tiempo (s)"
    if canal == "lap":
        return "Vuelta"

    nombre, unidad = _describir_nucleo(canal)
    return f"{nombre} ({unidad})" if unidad else nombre


def unidad_canal(canal: str) -> str:
    """Unidad que debe mostrarse en el eje Y de una señal."""
    if canal in UNIDADES:
        return UNIDADES[canal]

    for prefijo, unidad in UNIDADES.items():
        if canal.startswith(prefijo + "_") or canal == prefijo:
            return unidad
    for prefijo, unidad in UNIDADES_TEXTO.items():
        if canal.startswith(prefijo + "_") or canal == prefijo:
            return unidad
    return ""


def descripcion_canal(canal: str) -> str:
    """Texto más largo para tooltips."""
    if canal == "timestamp_s":
        return "Tiempo transcurrido desde el inicio de la sesión. Es el eje X."
    if canal == "lap":
        return "Número de vuelta. Sirve para agrupar, no es una señal."

    etiqueta = etiqueta_canal(canal)
    if canal in {"throttle", "brake", "steering"}:
        return (
            f"{etiqueta}: mando del piloto a lo largo de la vuelta. El valor "
            "suele ir de 0 a 1; si el CSV trae picos fuera de ese rango se "
            "conservan, no se recortan."
        )
    if canal.startswith("wheel_slip"):
        return f"{etiqueta}: deslizamiento de la rueda; sube cuando pierde agarre."
    if canal.startswith("temp_core_c"):
        return f"{etiqueta}: temperatura del neumático; suele crecer con el uso."
    if canal.startswith("pressure_psi"):
        return f"{etiqueta}: presión de la rueda."
    if canal.startswith("wheel_load_n"):
        return f"{etiqueta}: carga vertical soportada por la rueda."
    if canal == "speed_kmh":
        return "Velocidad del coche en km/h."
    if canal == "fuel_kg":
        return "Combustible restante. Baja con cada vuelta."
    return etiqueta
