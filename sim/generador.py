"""Generador de datos simulados de telemetria (fuente F1).

Produce dos archivos:
  - un CSV crudo con ruido de sensor, outliers y huecos (esquema del proyecto);
  - un CSV aparte con la degradacion verdadera por muestra (solo validacion).

La degradacion es una variable oculta que aumenta con cada vuelta y se acopla a
slip y temperatura (config ``sim.acople``), tal como se describe en el plan
(seccion 4). Ademas, para que el proxy por tiempo de vuelta (D7) sea fisico:
  - la **masa de combustible** afecta la aceleracion/frenada (auto mas liviano =>
    vueltas mas rapidas);
  - la **degradacion** reduce el agarre en curva (goma gastada => vueltas mas
    lentas).
Asi el tiempo de vuelta corregido por combustible refleja el desgaste real y no
solo la monotonia del combustible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from src.config import RUEDAS, columnas_esquema

# Parametros aproximados de un GT de Assetto Corsa.
MASA_KG = 1300.0
G = 9.81
K_AERO = 1.6           # N por (m/s)^2
ALTURA_CG_M = 0.5
VIA_M = 1.6
BATALLA_M = 2.7
FRACCION_FRONTAL = 0.45
A_MAX = 12.0           # m/s^2 (a masa de referencia)
B_MAX = 25.0           # m/s^2 (a masa de referencia)
V_MIN_MS = 15.0
P_FRIO_PSI = 22.0
T_AMB_C = 25.0
GRIP_K = 0.12          # caida de velocidad en curva por unidad de degradacion

# Pista sintetica: (largo_m, vel_objetivo_kmh, curvatura_1_m).
# Curvatura positiva = curva a la derecha. Cada par (v, curvatura) cumple
# v^2 * curvatura <= ~16 m/s^2 (~1.6 g) para que la carga por rueda sea fisica.
PISTA_DEFECTO = (
    (500.0, 250.0, 0.0),
    (120.0, 140.0, 0.01),      # R = 100 m
    (300.0, 190.0, 0.0),
    (80.0, 75.0, -0.033),      # horquilla, R = 30 m
    (450.0, 255.0, 0.0),
    (100.0, 115.0, -0.0145),   # R = 69 m
    (350.0, 210.0, 0.0),
    (70.0, 70.0, 0.037),       # R = 27 m
    (420.0, 240.0, 0.0),
)

LARGO_VUELTA_M = float(sum(seg[0] for seg in PISTA_DEFECTO))


def _combustible(lap, frac, fuel0: float, kg_vuelta: float):
    """Combustible (kg) en la vuelta ``lap`` a la fraccion ``frac`` de la vuelta."""
    return np.maximum(0.0, fuel0 - kg_vuelta * (np.asarray(lap) - 1 + np.asarray(frac)))


def mass_safe(masa: float, masa_ref: float) -> float:
    """Evita division por cero si la masa quedara inconsistente."""
    return masa if masa > 1.0 else masa_ref


def _perfil_trayectoria(
    vueltas: int,
    fs: float,
    pista=PISTA_DEFECTO,
    grip_vuelta=None,
    masa_fn=None,
    masa_ref: float = MASA_KG,
):
    """Simula el perfil de velocidad con frenadas antes de las curvas.

    ``grip_vuelta`` reduce la velocidad objetivo en curva vuelta a vuelta (goma
    gastada) y ``masa_fn(lap, frac)`` ajusta los limites de aceleracion/frenada
    segun la masa (combustible). Devuelve tambien la fraccion de vuelta de cada
    muestra, util para interpolar magnitudes por vuelta.
    """
    dt = 1.0 / fs
    n_seg = len(pista)
    v_prox = np.array([pista[(i + 1) % n_seg][1] / 3.6 for i in range(n_seg)])

    t = 0.0
    v = 45.0
    tiempos, velocidades, curvaturas, laps, fracs = [], [], [], [], []

    for lap in range(1, vueltas + 1):
        grip = 1.0 if grip_vuelta is None else float(grip_vuelta[lap - 1])
        recorrido_lap = 0.0
        for i, (largo, v_kmh, curv) in enumerate(pista):
            v_obj = (v_kmh / 3.6) * grip
            v_sig = v_prox[i] * grip
            recorrido = 0.0
            while recorrido < largo:
                restante = max(0.0, largo - recorrido)
                frac = min((recorrido_lap + recorrido) / LARGO_VUELTA_M, 1.0)
                masa = masa_ref if masa_fn is None else float(masa_fn(lap, frac))
                a_max = A_MAX * masa_ref / mass_safe(masa, masa_ref)
                b_max = B_MAX * masa_ref / mass_safe(masa, masa_ref)
                v_lim = np.sqrt(max(0.0, v_sig**2 + 2.0 * b_max * restante))
                v_objetivo = min(v_obj, v_lim)
                if v < v_objetivo:
                    v = min(v + a_max * dt, v_objetivo)
                else:
                    v = max(v - b_max * dt, v_objetivo)
                v = max(v, V_MIN_MS)

                tiempos.append(t)
                velocidades.append(v)
                curvaturas.append(curv)
                laps.append(lap)
                fracs.append(frac)

                recorrido += v * dt
                t += dt
            recorrido_lap += largo

    return (
        np.asarray(tiempos),
        np.asarray(velocidades),
        np.asarray(curvaturas),
        np.asarray(laps),
        np.asarray(fracs),
    )


def _primer_orden(objetivo: np.ndarray, dt: float, tau: float, x0: float) -> np.ndarray:
    """Filtro de primer orden (inercia termica) resuelto con lfilter."""
    alpha = dt / tau
    b = [alpha]
    a = [1.0, -(1.0 - alpha)]
    zi = [(1.0 - alpha) * x0]
    y, _ = lfilter(b, a, objetivo, zi=zi)
    return y


def _degradacion_por_vuelta(vueltas: int, tasa_base: float, rng) -> np.ndarray:
    """Degradacion oculta por vuelta: monotona, suave y en [0, 0.95].

    Como la etiqueta se normaliza a 0-0.95, un factor de escala uniforme no
    cambia la forma. Por eso ``tasa_base`` controla **cuanto se acelera el
    desgaste hacia el final del stint** (la curva de caida): 0 = lineal,
    valores altos = caida marcada al final. La severidad por vuelta anade una
    variacion que no es trivialmente predecible.
    """
    sev = rng.normal(1.0, 0.15, size=vueltas)
    prog = np.arange(vueltas) / max(1, vueltas - 1)
    crecimiento = np.maximum(1e-3, sev * (1.0 + tasa_base * prog))
    crudo = np.cumsum(crecimiento)
    return (crudo - crudo[0]) / (crudo[-1] - crudo[0] + 1e-12) * 0.95


def generar_dataframe(cfg: dict, semilla: int | None = None):
    """Devuelve (telemetria_cruda, degradacion_verdadera)."""
    sim = cfg["sim"]
    fs = float(sim["fs_original"])
    dt = 1.0 / fs
    vueltas = int(sim["vueltas"])
    acople = float(sim.get("acople", 1.0))
    tasa_base = float(sim.get("tasa_degradacion", 1.0))
    semilla = int(sim["semilla"]) if semilla is None else int(semilla)
    rng = np.random.default_rng(semilla)

    # --- combustible: masa que baja con el tiempo ---
    kg_vuelta = float(sim["combustible_kg_vuelta"])
    fuel0 = float(sim["combustible_inicial_kg"])

    def masa_fn(lap, frac):
        return MASA_KG + float(_combustible(lap, frac, fuel0, kg_vuelta))

    # --- degradacion oculta por vuelta (antes de la trayectoria: define el grip) ---
    degrad_lap = _degradacion_por_vuelta(vueltas, tasa_base, rng)
    grip_vuelta = 1.0 - GRIP_K * degrad_lap

    t, v, curv, lap, frac = _perfil_trayectoria(
        vueltas, fs, grip_vuelta=grip_vuelta, masa_fn=masa_fn
    )
    n = t.size

    # degradacion por muestra: interpolacion lineal dentro de cada vuelta
    idx = np.clip(lap - 1, 0, vueltas - 1)
    idx_next = np.clip(lap, 0, vueltas - 1)
    degradacion = degrad_lap[idx] + frac * (degrad_lap[idx_next] - degrad_lap[idx])
    degradacion = np.clip(degradacion, 0.0, 1.0)

    acc = np.gradient(v, dt)
    lat = v**2 * curv
    v_max = max(float(np.max(v)), 1.0)

    throttle = np.clip(acc / A_MAX, 0.0, 1.0)
    brake = np.clip(-acc / B_MAX, 0.0, 1.0)
    steering = np.clip(curv * 12.0, -1.0, 1.0) + rng.normal(0.0, 0.01, n)

    # --- cargas por rueda (estatica + transferencia + aerodinamica) ---
    masa_total = MASA_KG + _combustible(lap, frac, fuel0, kg_vuelta)
    carga_total = masa_total * G + K_AERO * v**2
    base = carga_total / 4.0
    d_lat = masa_total * lat * ALTURA_CG_M / (VIA_M * 2.0)
    d_lon = masa_total * acc * ALTURA_CG_M / (BATALLA_M * 2.0)
    carga = {
        "fl": base + d_lat - d_lon * FRACCION_FRONTAL,
        "fr": base - d_lat - d_lon * FRACCION_FRONTAL,
        "rl": base + d_lat + d_lon * (1.0 - FRACCION_FRONTAL),
        "rr": base - d_lat + d_lon * (1.0 - FRACCION_FRONTAL),
    }
    # una rueda puede descargarse, pero no tener carga negativa
    for w in RUEDAS:
        carga[w] = np.maximum(carga[w], 50.0)

    # --- senales por rueda con ruido, offset y acoplamiento con el desgaste ---
    ruido = sim["ruido"]
    slip_lat = 0.11 * np.clip(np.abs(lat) / 8.0, 0.0, 1.2)

    datos = {
        "timestamp_s": t,
        "lap": lap.astype(float),
        "speed_kmh": v * 3.6,
        "throttle": throttle,
        "brake": brake,
        "steering": steering,
    }

    for w in RUEDAS:
        activo = 1.0 if w in ("rl", "rr") else 0.25
        slip = (
            0.015
            + slip_lat * (1.0 + 0.3 * activo)
            + 0.12 * throttle * (0.3 + activo)
            - 0.03 * brake
        )
        slip = slip * (1.0 + 0.35 * acople * degradacion)
        slip = slip + rng.normal(0.0, ruido["slip"], n) + rng.normal(0.0, 0.005)

        carga_w = carga[w] + rng.normal(0.0, ruido["load"], n)

        # La goma trabaja en un rango realista de ~85-120 C: el rozamiento la
        # calienta y el desgaste sube la temperatura de regimen.
        objetivo_temp = (
            T_AMB_C
            + 40.0
            + 45.0 * np.clip(slip, 0.0, 1.0)
            + 22.0 * (v / v_max)
            + 30.0 * acople * degradacion
        )
        temp = _primer_orden(objetivo_temp, dt, tau=8.0, x0=T_AMB_C)
        temp = temp + rng.normal(0.0, ruido["temp"], n) + rng.normal(0.0, 1.0)

        presion = (
            P_FRIO_PSI * (temp + 273.15) / (20.0 + 273.15)
            + rng.normal(0.0, ruido["pressure"], n)
            + rng.normal(0.0, 0.2)
        )

        sucio = np.cumsum(1e-4 * (1.0 + 10.0 * np.abs(slip) * brake)) * dt
        sucio = np.clip(sucio + rng.normal(0.0, 0.002, n), 0.0, 1.0)

        datos[f"temp_core_c_{w}"] = temp
        datos[f"pressure_psi_{w}"] = presion
        datos[f"wheel_slip_{w}"] = slip
        datos[f"wheel_load_n_{w}"] = carga_w
        datos[f"dirty_level_{w}"] = sucio

    # --- combustible (la misma funcion que uso para la masa) ---
    datos["fuel_kg"] = _combustible(lap, frac, fuel0, kg_vuelta)

    df = pd.DataFrame(datos)[columnas_esquema()]

    # La verdad se guarda antes de ensuciar la senal.
    verdad = pd.DataFrame(
        {"timestamp_s": t, "lap": lap.astype(int), "degradacion": degradacion}
    )

    _inyectar_outliers(df, cfg, rng)
    _inyectar_huecos(df, cfg, rng)

    # jitter de timestamp (sensores reales no son perfectamente uniformes)
    jitter = float(sim.get("jitter_s", 0.0))
    if jitter > 0:
        desplaz = rng.normal(0.0, jitter, n)
        ts = df["timestamp_s"].to_numpy() + desplaz
        ts = np.maximum.accumulate(ts)
        df["timestamp_s"] = ts

    return df, verdad


def _inyectar_outliers(df: pd.DataFrame, cfg: dict, rng) -> None:
    sim = cfg["sim"]
    n = len(df)
    canales = [c for c in df.columns if c not in ("timestamp_s", "lap")]
    n_out = int(sim["outliers_prop"] * n)
    if n_out <= 0:
        return
    idx = rng.choice(n, size=n_out, replace=False)
    col = rng.choice(canales, size=n_out)
    # picos grandes: multiplicar por un factor o sumar un offset grosero
    for i, c in zip(idx, col):
        if rng.random() < 0.5:
            df.iloc[i, df.columns.get_loc(c)] = df.iloc[i][c] * rng.uniform(20.0, 80.0)
        else:
            df.iloc[i, df.columns.get_loc(c)] = df.iloc[i][c] + rng.choice([200.0, -150.0])


def _inyectar_huecos(df: pd.DataFrame, cfg: dict, rng) -> None:
    sim = cfg["sim"]
    n = len(df)
    largo = int(sim.get("hueco_largo_muestras", 40))
    n_huecos = int(sim["huecos_prop"] * n / max(1, largo // 2))
    canales = [
        c
        for c in df.columns
        if c not in ("timestamp_s", "lap")
    ]
    for _ in range(n_huecos):
        inicio = int(rng.integers(0, max(1, n - largo)))
        c = canales[int(rng.integers(0, len(canales)))]
        df.iloc[inicio : inicio + largo, df.columns.get_loc(c)] = np.nan


def generar(cfg: dict, dir_salida: str | Path, semilla: int | None = None, nombre: str = "sim"):
    """Escribe los CSV de telemetria y de verdad. Devuelve (ruta_crudo, ruta_verdad)."""
    df, verdad = generar_dataframe(cfg, semilla)
    dir_salida = Path(dir_salida)
    dir_salida.mkdir(parents=True, exist_ok=True)
    s = int(semilla if semilla is not None else cfg["sim"]["semilla"])
    ruta_crudo = dir_salida / f"{nombre}_{s}.csv"
    ruta_verdad = dir_salida / f"{nombre}_{s}_verdad.csv"
    df.to_csv(ruta_crudo, index=False)
    verdad.to_csv(ruta_verdad, index=False)
    return ruta_crudo, ruta_verdad
