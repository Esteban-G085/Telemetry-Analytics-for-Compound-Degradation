"""Parámetros del modelo compartidos entre el Taller y la Predicción.

Los nombres de las claves son los que ya espera el backend
(``q_nivel``, ``q_pendiente``, ``r``, ``monotono`` y ``alpha``). Aquí solo se
centralizan los valores iniciales de la GUI y las explicaciones para que el
Taller de modelos y la pestaña de resultados digan siempre lo mismo.
"""

from __future__ import annotations

PARAMETROS_POR_DEFECTO: dict[str, float | bool] = {
    "q_nivel": 0.0001,
    "q_pendiente": 0.00001,
    "r": 0.001,
    "monotono": True,
    "alpha": 0.1,
}

# (etiqueta visible, clave del glosario) para cada parámetro editable.
ETIQUETAS_PARAMETROS: dict[str, tuple[str, str]] = {
    "q_nivel": ("Kalman · nivel (Q)", "kalman_q"),
    "q_pendiente": ("Kalman · pendiente (Q)", "kalman_q"),
    "r": ("Kalman · ruido (R)", "kalman_r"),
    "monotono": ("Kalman monótono", "verdad"),
    "alpha": ("Ridge · alpha", "alpha"),
}

_RUEDAS = {"fl": "delantera izquierda", "fr": "delantera derecha",
           "rl": "trasera izquierda", "rr": "trasera derecha"}

_PREFIXES = {
    "speed_mean": "Velocidad media de la ventana (km/h).",
    "speed_std": "Variación de la velocidad dentro de la ventana.",
    "throttle_mean": "Acelerador medio aplicado (0–1).",
    "brake_mean": "Freno medio aplicado (0–1).",
    "steering_std": "Variación de la dirección; indica cambios de trayectoria.",
    "slip_mean": "Deslizamiento medio de la rueda.",
    "slip_std": "Variación del deslizamiento de la rueda.",
    "slip_absmax": "Pico de deslizamiento de la rueda.",
    "slip_rms": "Deslizamiento eficaz (RMS) de la rueda.",
    "slip_energia": "Energía de deslizamiento acumulada en la ventana.",
    "temp_mean": "Temperatura media del núcleo del neumático.",
    "temp_std": "Variación térmica del neumático.",
    "temp_max": "Temperatura máxima alcanzada en la ventana.",
    "carga_mean": "Carga media soportada por la rueda (N).",
    "carga_max": "Carga máxima soportada por la rueda (N).",
    "trabajo_friccion": "Trabajo de fricción: desgaste mecánico estimado.",
    "grados_segundo": "Grados sobre el umbral térmico acumulados en la ventana.",
    "psd_baja": "Energía del deslizamiento en la banda baja (0,5–5 Hz).",
    "psd_media": "Energía del deslizamiento en la banda media (5–15 Hz).",
    "psd_alta": "Energía del deslizamiento en la banda alta (15–40 Hz).",
}


def parametros_desde_config(config: dict) -> dict[str, float | bool]:
    """Lee los valores guardados sin inventar claves nuevas en el backend."""
    valores = dict(PARAMETROS_POR_DEFECTO)
    if not isinstance(config, dict):
        return valores
    modelo = config.get("modelo") or {}
    kalman = modelo.get("kalman") or {}
    if isinstance(kalman, dict):
        for clave in ("q_nivel", "q_pendiente", "r", "monotono"):
            if clave in kalman:
                valores[clave] = kalman[clave]
    alphas = modelo.get("ridge_alphas") or []
    if isinstance(alphas, (list, tuple)) and alphas:
        try:
            valores["alpha"] = float(alphas[0])
        except (TypeError, ValueError):
            pass
    return valores


def descripcion_feature(nombre: str) -> str:
    """Explicación en español de una feature numérica del modelo."""
    texto = str(nombre)
    for prefijo, descripcion in _PREFIXES.items():
        if texto.startswith(prefijo):
            sufijo = texto[len(prefijo):].lstrip("_")
            rueda = _RUEDAS.get(sufijo)
            return f"{descripcion} {f'({rueda})' if rueda else ''}".strip()
    return "Feature numérica calculada a partir de la sesión cargada."
