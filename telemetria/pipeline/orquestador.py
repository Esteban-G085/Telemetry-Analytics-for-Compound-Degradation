"""Orquestacion del pipeline de la Etapa 1.

Uso (a traves del punto de entrada unico `python -m telemetria`):
    python -m telemetria pipeline --fuente sim --config config.yaml
    python -m telemetria pipeline --entrada data/raw/sim_42.csv --fuente sim
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from telemetria.pipeline import etiquetas, evaluacion, features, limpieza, modelo, reporte
from telemetria.pipeline.config import cargar_config

RAIZ = Path(__file__).resolve().parents[2]
log = logging.getLogger("etapa1")


def configurar_logging(verboso: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _etiquetas_ventana(feats, verdad, proxy, cfg):
    """Etiqueta de cada ventana: verdad por muestra, o proxy por vuelta."""
    if verdad is not None:
        return modelo.etiquetas_por_ventana(feats, verdad, cfg)
    mapa = dict(zip(proxy["lap"], proxy["degradacion_proxy"]))
    return feats["lap"].map(mapa).to_numpy(dtype=float)


def _hash_archivo(ruta: Path, bloque: int = 1 << 20) -> str:
    """sha256 del CSV de entrada, leido por bloques para no cargarlo en RAM."""
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def correr(entrada, fuente, ruta_config, salida, semilla):
    t0 = time.time()
    cfg = cargar_config(ruta_config)
    dir_raw = RAIZ / "data" / "raw"
    dir_proc = RAIZ / "data" / "processed"
    dir_rep = Path(salida) if salida else RAIZ / "data" / "reports"
    for d in (dir_raw, dir_proc, dir_rep):
        d.mkdir(parents=True, exist_ok=True)

    # --- 1. Entrada ---
    ruta_verdad = None
    if entrada is None:
        if fuente != "sim":
            raise SystemExit("Solo la fuente 'sim' genera datos; usa --entrada en otro caso.")
        from telemetria.adquisicion import generador

        log.info("Generando datos simulados (semilla=%s)...", semilla if semilla is not None else cfg["sim"]["semilla"])
        ruta_crudo, ruta_verdad = generador.generar(cfg, dir_raw, semilla=semilla)
        log.info("Escrito %s", ruta_crudo.name)
    else:
        ruta_crudo = Path(entrada)
        posible = ruta_crudo.with_name(ruta_crudo.stem + "_verdad.csv")
        ruta_verdad = posible if posible.exists() else None

    df_raw = pd.read_csv(ruta_crudo)

    # --- 2. Limpieza (incluye remuestreo y filtrado) ---
    log.info("Limpiando (%d muestras)...", len(df_raw))
    intermedios: dict = {}
    df_limpio, registro, estado = limpieza.preprocesar(df_raw, cfg, intermedios=intermedios)
    log.info("Registro de calidad: %s", registro)
    df_limpio.to_csv(dir_proc / "senal_limpia.csv.gz", index=False, compression="gzip")

    # --- 3. Features ---
    log.info("Extrayendo features por ventana...")
    feats = features.features_por_ventanas(df_limpio, cfg)
    if feats.empty:
        raise SystemExit("No se generaron ventanas validas. Revisa la limpieza.")
    feats_vuelta = features.agregar_por_vuelta(feats)
    log.info("Ventanas: %d | features por vuelta: %s", len(feats), feats_vuelta.shape)

    # --- 4. Etiquetas ---
    verdad = pd.read_csv(ruta_verdad) if ruta_verdad else None
    proxy = etiquetas.proxy_degradacion(df_limpio, cfg, fs=cfg["fs"])
    resultado = {"registro": registro, "limpio": df_limpio, "resampleado": intermedios.get("resampleado")}

    if verdad is not None:
        y_vuelta_df = etiquetas.verdad_por_vuelta(verdad)
        resultado["calidad_proxy"] = etiquetas.comparar_proxy(proxy, y_vuelta_df)
        log.info("Calidad del proxy vs. verdad: %s", resultado["calidad_proxy"])
    else:
        y_vuelta_df = proxy[["lap", "degradacion_proxy"]].rename(
            columns={"degradacion_proxy": "degradacion"}
        )
    resultado["proxy"] = proxy

    y_ventana = _etiquetas_ventana(feats, verdad, proxy, cfg)

    # --- 5. Split temporal por vueltas (nunca al azar) ---
    laps_w = feats["lap"].to_numpy()
    train_laps, test_laps = modelo.split_temporal(np.unique(laps_w), cfg["modelo"]["prop_test"])
    m_tr = np.isin(laps_w, train_laps)
    m_te = np.isin(laps_w, test_laps)
    log.info("Vueltas train=%d test=%d", len(train_laps), len(test_laps))

    # degradacion real por vuelta en test (para comparar modelos)
    verdad_lap = dict(zip(y_vuelta_df["lap"], y_vuelta_df["degradacion"]))
    y_test = np.array([verdad_lap[l] for l in test_laps], dtype=float)
    y_train_lap = np.array([verdad_lap[l] for l in train_laps], dtype=float)

    metricas_todo = {}

    # --- Ridge a nivel VENTANA (modelo principal); se agrega por vuelta ---
    Xw, cols_w = modelo.matriz_features(feats)
    ridge = modelo.entrenar_ridge(Xw[m_tr], y_ventana[m_tr], laps_w[m_tr], cfg)
    pred_w = modelo.predecir_ridge(ridge, Xw)
    pred_ridge = (
        pd.DataFrame({"lap": laps_w, "pred": pred_w})
        .groupby("lap")["pred"]
        .mean()
        .reindex(test_laps)
        .to_numpy(dtype=float)
    )
    metricas_todo["Ridge (ventana->vuelta)"] = evaluacion.metricas(y_test, pred_ridge)
    resultado["importancias"] = modelo.importancias(ridge, cols_w)
    resultado["fisica"] = evaluacion.verificacion_fisica(resultado["importancias"])

    # persistencia: coeficientes y modelo entrenado (para reutilizar en Etapa 3)
    resultado["importancias"].to_csv(dir_proc / "importancias.csv", index=False)
    joblib.dump(ridge, dir_proc / "modelo_ridge.joblib")
    log.info("Guardado modelo Ridge en %s", dir_proc / "modelo_ridge.joblib")

    # Ablacion por circularidad: sin features derivadas de slip/temperatura.
    # OJO: trabajo_friccion = suma(|slip|*carga*v*dt) tambien deriva del slip,
    # por eso se excluye aunque su nombre no contenga "slip".
    Xa, cols_a = modelo.matriz_features(
        feats, excluir=("slip", "temp", "psd", "grados_segundo", "trabajo")
    )
    ridge_abl = modelo.entrenar_ridge(Xa[m_tr], y_ventana[m_tr], laps_w[m_tr], cfg)
    pred_abl = (
        pd.DataFrame({"lap": laps_w, "pred": modelo.predecir_ridge(ridge_abl, Xa)})
        .groupby("lap")["pred"]
        .mean()
        .reindex(test_laps)
        .to_numpy(dtype=float)
    )
    metricas_todo["Ridge ablacionado (sin slip/temp)"] = evaluacion.metricas(y_test, pred_abl)

    # Baselines a nivel vuelta
    for nombre, met in evaluacion.baselines(y_train_lap, y_test).items():
        metricas_todo[nombre] = met

    # --- Kalman a nivel vuelta ---
    kal = modelo.KalmanDegradacion(
        cfg["modelo"]["kalman"]["q_nivel"],
        cfg["modelo"]["kalman"]["q_pendiente"],
        cfg["modelo"]["kalman"]["r"],
        monotono=cfg["modelo"]["kalman"].get("monotono", True),
    )
    res_kal = kal.filtrar(y_train_lap)
    medias_k, var_k = kal.predecir(res_kal, len(test_laps))
    metricas_todo["Kalman (vuelta)"] = evaluacion.metricas(y_test, medias_k)
    cobertura = evaluacion.cobertura_bandas(y_test, medias_k, var_k, cfg["evaluacion"]["z"])
    log.info("Cobertura de bandas Kalman: %.2f", cobertura)

    umbral = cfg["etiquetas"]["umbral_caida"]
    error_caida = {
        "Ridge (ventana->vuelta)": evaluacion.error_vuelta_caida(y_test, pred_ridge, umbral),
        "Kalman (vuelta)": evaluacion.error_vuelta_caida(y_test, medias_k, umbral),
    }
    log.info("Error vuelta de caida (Ridge|Kalman): %s", error_caida)

    sensibilidad = evaluacion.sensibilidad_kalman(y_train_lap, y_test, cfg)
    log.info("Sensibilidad de Kalman a R: %s", sensibilidad)

    # --- Robustez al ruido (input, no etiqueta) ---
    snr = evaluacion.prueba_robustez_snr(
        ridge, Xw[m_te], y_ventana[m_te], cfg["evaluacion"]["snr_db"], rng=np.random.default_rng(7)
    )

    # --- 6. Reporte ---
    resultado.update(
        {
            "features_vuelta": feats_vuelta,
            "metricas": metricas_todo,
            "vuelta_true": y_test,
            "pred_ridge": pred_ridge,
            "pred_kalman": medias_k,
            "var_kalman": var_k,
            "snr": snr,
            "cobertura": cobertura,
            "error_caida": error_caida,
            "sensibilidad_kalman": sensibilidad,
            "hash_entrada": _hash_archivo(ruta_crudo),
            "config_yaml": Path(ruta_config).read_text(encoding="utf-8"),
            "entrada": str(ruta_crudo),
        }
    )
    log.info("Verificacion fisica (signos): %s", resultado["fisica"])
    ruta = reporte.generar_reporte(resultado, dir_rep / "reporte_etapa1.html", cfg)
    log.info("Reporte: %s", ruta)
    log.info("MAE por modelo: %s", {k: round(v["mae"], 4) for k, v in metricas_todo.items()})
    log.info("Listo en %.1f s", time.time() - t0)
    return metricas_todo


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Pipeline Etapa 1 (telemetria pipeline)")
    p.add_argument("--entrada", default=None, help="CSV de telemetria; si se omite, se genera (sim)")
    p.add_argument("--fuente", default="sim", choices=["sim"], help="fuente de datos")
    p.add_argument("--config", default=str(RAIZ / "config.yaml"))
    p.add_argument("--salida", default=None, help="carpeta de reportes")
    p.add_argument("--semilla", type=int, default=None)
    p.add_argument("-v", "--verboso", action="store_true")
    args = p.parse_args(argv)

    configurar_logging(args.verboso)
    correr(args.entrada, args.fuente, args.config, args.salida, args.semilla)


if __name__ == "__main__":
    main()
