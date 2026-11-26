"""Definiciones cortas de los términos que aparecen en la interfaz.

La GUI debe entenderse sin leer el código. Aquí se concentra el significado de
las métricas y de los conceptos del pipeline, para que los tooltips y la guía
rápida digan siempre lo mismo. Las claves JSON del backend no se tocan.
"""

from __future__ import annotations

GLOSARIO: dict[str, str] = {
    "mae": (
        "MAE: error medio absoluto. En promedio, cuánto se equivoca la "
        "predicción. Menor es mejor."
    ),
    "rmse": (
        "RMSE: error cuadrático medio. Parecido al MAE, pero penaliza más los "
        "fallos grandes. Menor es mejor."
    ),
    "snr": (
        "SNR: relación señal/ruido en decibelios. Menos dB significa más ruido "
        "añadido a la señal."
    ),
    "outlier": (
        "Outlier: valor descartado por parecer un pico aislado y no un cambio "
        "real de la señal."
    ),
    "psd": (
        "PSD: densidad espectral de potencia. Indica cuánta energía tiene la "
        "señal en cada frecuencia."
    ),
    "welch": (
        "Welch: método para calcular el espectro dividiendo la señal en trozos "
        "y promediando el resultado."
    ),
    "banda": (
        "Banda: rango de frecuencias. Baja (0,5–5 Hz), media (5–15 Hz) y alta "
        "(15–40 Hz)."
    ),
    "alpha": (
        "Alpha de Ridge: parámetro que controla la regularización. Más valor "
        "da una tendencia más simple."
    ),
    "kalman_q": (
        "Q de Kalman: cuánto puede cambiar el nivel o la pendiente entre "
        "vueltas. Más valor hace que el filtro reaccione antes."
    ),
    "kalman_r": (
        "R de Kalman: ruido esperado en la medición. Más valor da una curva "
        "más suave, que responde más tarde."
    ),
    "delta": (
        "Subida del error: cuánto empeora el MAE al desconectar un sensor. "
        "La flecha ↑ indica ese aumento."
    ),
    "verdad": (
        "Verdad: degradación real simulada. Cuando no está disponible se usa "
        "un proxy calculado a partir del tiempo de vuelta."
    ),
    "proxy": (
        "Proxy: aproximación a la degradación construida con el tiempo de "
        "vuelta y el combustible, usada cuando no hay etiqueta real."
    ),
    "vuelta": (
        "Vuelta: tramo de la sesión comprendido entre dos pasadas por la "
        "línea de salida."
    ),
    "downsample": (
        "Downsample: reducción del número de puntos dibujados para que la "
        "gráfica responda rápido. El cálculo original no cambia."
    ),
    "calidad": (
        "Calidad: porcentaje de muestras de la vuelta que el pipeline marcó "
        "como válidas."
    ),
    "progreso": (
        "Progreso de vuelta: porcentaje recorrido desde el inicio (0 %) hasta "
        "el final (100 %). Permite comparar señales aunque las vueltas duren "
        "distinto."
    ),
    "diferencia": (
        "Diferencia A − B: resta de las dos señales seleccionadas. Con señales "
        "normalizadas muestra cuál va por encima en cada momento."
    ),
    "cursor": (
        "Cursor: línea que sigue al ratón y muestra el valor de cada señal en "
        "ese instante."
    ),
    "encuadrar": (
        "Ver toda la vuelta: vuelve a ajustar el eje horizontal al rango "
        "completo de la vuelta cargada."
    ),
}

# (nombre visible, clave en GLOSARIO) para la guía rápida.
TERMINOS: tuple[tuple[str, str], ...] = (
    ("MAE", "mae"),
    ("RMSE", "rmse"),
    ("SNR", "snr"),
    ("Outlier", "outlier"),
    ("PSD y Welch", "psd"),
    ("Bandas", "banda"),
    ("Alpha de Ridge", "alpha"),
    ("Q y R de Kalman", "kalman_q"),
    ("Ruido R", "kalman_r"),
    ("Subida del error", "delta"),
    ("Verdad y proxy", "verdad"),
    ("Vuelta", "vuelta"),
    ("Downsample", "downsample"),
    ("Calidad", "calidad"),
    ("Progreso de vuelta", "progreso"),
    ("Diferencia A − B", "diferencia"),
    ("Cursor", "cursor"),
)


def tooltip(clave: str) -> str:
    """Devuelve el texto listo para un tooltip; nunca devuelve vacío."""
    return GLOSARIO.get(clave, "Consulta la guía rápida para entender este control.")
