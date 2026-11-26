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
    "r2": (
        "R²: proporción de la variabilidad explicada por el modelo. 1 es "
        "perfecto, 0 similar a predecir siempre la media y un valor negativo "
        "peor que esa media. Solo se calcula con más de una vuelta de prueba."
    ),
    "cobertura": (
        "Cobertura de bandas: porcentaje de vueltas de prueba cuyo valor real "
        "cae dentro del intervalo de Kalman. Con pocas vueltas solo puede "
        "tomar unos pocos valores."
    ),
    "error_caida": (
        "Error en la vuelta de caída: diferencia entre el valor observado y el "
        "estimado en la primera vuelta que supera el umbral de caída. Muestra "
        "si el modelo anticipa o retrasa ese cambio."
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
        "Alpha aplicado a Ridge en el experimento actual: controla la "
        "regularización. Más valor da una tendencia más simple. La lista de "
        "config.yaml son candidatos para validación cruzada; el primero de esa "
        "lista no es necesariamente el alpha usado. Alpha no se guarda en "
        "config.yaml: solo afecta al recálculo actual."
    ),
    "kalman_q": (
        "Q de Kalman: cuánto puede cambiar el nivel o la pendiente entre "
        "vueltas. Más valor hace que el filtro reaccione antes."
    ),
    "kalman_r": (
        "R de Kalman: ruido esperado en la medición. Más valor da una curva "
        "más suave, que responde más tarde."
    ),
    "kalman_monotono": (
        "Kalman monótono: impone que el nivel estimado no baje y que la "
        "pendiente no sea negativa. Es coherente con un desgaste que solo "
        "crece, pero inadecuado si la señal debe poder recuperarse o caer."
    ),
    "restablecer_fabrica": (
        "Restablecer valores de fábrica: descarta los overrides guardados y "
        "vuelve a los valores originales de config.yaml, tanto en la "
        "configuración como en los controles. No afecta a la sesión de datos."
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
        "Cursor: al pasar el ratón por una gráfica aparecen dos guías y una "
        "caja con la posición exacta y el valor de cada serie con su unidad. "
        "La caja cambia de lado cerca del borde para no cortarse."
    ),
    "modo_archivo": (
        "Modo archivo: estás viendo un CSV cargado. Las funciones en tiempo "
        "real (WebSocket y pestaña 'En vivo') quedan desactivadas a propósito."
    ),
    "modo_vivo": (
        "Modo vivo: estás capturando datos ahora. Las pestañas que analizan "
        "archivos quedan desactivadas para no mezclar dos fuentes distintas."
    ),
    "encuadrar": (
        "Ver toda la vuelta: vuelve a ajustar el eje horizontal al rango "
        "completo de la vuelta cargada."
    ),
    "rango": (
        "Rango visible: trozo de la vuelta que se está viendo ahora. La "
        "etiqueta lo muestra en segundos o en porcentaje y el minimapa lo "
        "resalta sombreado."
    ),
    "minimapa": (
        "Minimapa: visión completa de la vuelta debajo de la gráfica. La zona "
        "sombreada es lo que ves arriba; arrástrala para desplazarte sin "
        "perder la referencia."
    ),
    "unidades": (
        "Unidades del eje Y: la magnitud real de cada señal (km/h, °C, N, psi "
        "o mando). Al normalizar, el eje pasa a 0–1 y la leyenda y el cursor "
        "recuerdan el valor original."
    ),
    "zoom_in": "Acercar (+): reduce el rango visible alrededor del centro de la gráfica. La rueda del ratón hace lo mismo alrededor del puntero.",
    "zoom_out": "Alejar (−): amplía el rango visible. Nunca se puede alejar más allá del conjunto completo de datos.",
    "pan": "Mover: arrastra la gráfica para desplazarte por el rango de datos. Los límites impiden llegar a zonas vacías.",
    "region": "Seleccionar región: arrastra sobre la gráfica para ampliar solo el rectángulo elegido.",
    "restablecer": "Inicio: vuelve a la vista original con la que se cargaron los datos.",
    "ajustar": "Ajustar: adapta ambos ejes a todas las muestras recibidas, con un margen pequeño.",
    "auto_y": "Auto Y: escala el eje vertical automáticamente cuando cambian los datos. Desactívalo para conservar la escala actual.",
}

# (nombre visible, clave en GLOSARIO) para la guía rápida.
TERMINOS: tuple[tuple[str, str], ...] = (
    ("MAE", "mae"),
    ("RMSE", "rmse"),
    ("R²", "r2"),
    ("Cobertura de bandas", "cobertura"),
    ("Error en la caída", "error_caida"),
    ("SNR", "snr"),
    ("Outlier", "outlier"),
    ("PSD y Welch", "psd"),
    ("Bandas", "banda"),
    ("Alpha de Ridge", "alpha"),
    ("Q y R de Kalman", "kalman_q"),
    ("Ruido R", "kalman_r"),
    ("Kalman monótono", "kalman_monotono"),
    ("Restablecer valores de fábrica", "restablecer_fabrica"),
    ("Subida del error", "delta"),
    ("Verdad y proxy", "verdad"),
    ("Vuelta", "vuelta"),
    ("Downsample", "downsample"),
    ("Calidad", "calidad"),
    ("Progreso de vuelta", "progreso"),
    ("Diferencia A − B", "diferencia"),
    ("Cursor", "cursor"),
    ("Modo archivo", "modo_archivo"),
    ("Modo vivo", "modo_vivo"),
    ("Rango visible y minimapa", "rango"),
    ("Unidades", "unidades"),
    ("Navegación de gráficas", "pan"),
    ("Zoom con límites", "zoom_in"),
)


def tooltip(clave: str) -> str:
    """Devuelve el texto listo para un tooltip; nunca devuelve vacío."""
    return GLOSARIO.get(clave, "Consulta la guía rápida para entender este control.")
