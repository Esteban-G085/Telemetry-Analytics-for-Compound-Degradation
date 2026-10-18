"""Reporte HTML con las figuras del pipeline (Etapa 1).

Todos los graficos se incrustan en base64 para que el HTML sea autocontenido.
"""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin display
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.signal import welch  # noqa: E402

from telemetria.pipeline.config import RUEDAS  # noqa: E402


def _a_base64(fig) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _fig_a_html(fig, titulo: str) -> str:
    b64 = _a_base64(fig)
    return (
        f'<figure><figcaption>{titulo}</figcaption>'
        f'<img src="data:image/png;base64,{b64}" alt="{titulo}"/></figure>'
    )


def _fig_crudo_vs_limpio(resampleado, limpio, cfg):
    fs = float(cfg["fs"])
    rueda = "rl"
    col = f"wheel_slip_{rueda}"
    fig, ax = plt.subplots(figsize=(10, 3.5))
    t = limpio["timestamp_s"].to_numpy()
    tramo = min(int(20 * fs), len(t))
    ax.plot(t[:tramo], resampleado[col].to_numpy()[:tramo], alpha=0.45, label="crudo")
    ax.plot(t[:tramo], limpio[col].to_numpy()[:tramo], label="limpio", linewidth=1.2)
    ax.set_title(f"Senal cruda vs. limpia ({col})")
    ax.set_xlabel("t [s]")
    ax.legend(loc="upper right")
    return fig


def _fig_espectro(resampleado, limpio, cfg):
    fs = float(cfg["fs"])
    col = "wheel_slip_rl"
    x_crudo = np.nan_to_num(resampleado[col].to_numpy(dtype=float))
    x_limpio = limpio[col].to_numpy(dtype=float)
    nperseg = int(min(cfg["features"]["welch_nperseg"], len(x_crudo)))
    f1, p1 = welch(x_crudo, fs=fs, nperseg=nperseg)
    f2, p2 = welch(x_limpio, fs=fs, nperseg=nperseg)
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.semilogy(f1, p1, alpha=0.5, label="crudo")
    ax.semilogy(f2, p2, label="filtrado")
    ax.axvline(float(cfg["limpieza"]["filtro"]["corte_hz"]), color="r", ls="--", label="corte")
    ax.set_title("Densidad espectral (Welch) del slip")
    ax.set_xlabel("f [Hz]")
    ax.set_ylabel("PSD")
    ax.legend()
    return fig


def _fig_features_vuelta(features_vuelta):
    if features_vuelta is None or features_vuelta.empty:
        return None
    cols = [c for c in ("trabajo_friccion_rl", "grados_segundo_rl", "slip_mean_rl") if c in features_vuelta.columns]
    if not cols:
        return None
    fig, axes = plt.subplots(1, len(cols), figsize=(4.2 * len(cols), 3.2))
    axes = np.atleast_1d(axes)
    for ax, c in zip(axes, cols):
        ax.plot(features_vuelta["lap"], features_vuelta[c], marker="o", ms=3)
        ax.set_title(c)
        ax.set_xlabel("vuelta")
    return fig


def _fig_prediccion(vuelta_true, pred_ridge, pred_kalman, var_kalman, umbral):
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(1, len(vuelta_true) + 1)
    ax.plot(x, vuelta_true, "k-o", ms=4, label="real")
    if pred_ridge is not None:
        ax.plot(x, pred_ridge, "--s", ms=3, label="Ridge")
    if pred_kalman is not None:
        ax.plot(x, pred_kalman, "-^", ms=3, label="Kalman")
        if var_kalman is not None:
            desv = 1.96 * np.sqrt(np.asarray(var_kalman, dtype=float))
            ax.fill_between(x, pred_kalman - desv, pred_kalman + desv, alpha=0.2)
    ax.axhline(umbral, color="r", ls=":", label="umbral caida")
    ax.set_title("Degradacion por vuelta: real vs. predicha")
    ax.set_xlabel("vuelta")
    ax.set_ylabel("degradacion [0-1]")
    ax.legend()
    return fig


def _fig_snr(snr):
    if not snr:
        return None
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.plot([r["snr_db"] for r in snr], [r["mae"] for r in snr], "o-")
    ax.invert_xaxis()
    ax.set_title("MAE vs. SNR del input")
    ax.set_xlabel("SNR [dB]")
    ax.set_ylabel("MAE")
    return fig


def generar_reporte(datos: dict, ruta_html: str | Path, cfg: dict) -> Path:
    ruta_html = Path(ruta_html)
    ruta_html.parent.mkdir(parents=True, exist_ok=True)

    bloques = []
    if datos.get("resampleado") is not None and datos.get("limpio") is not None:
        bloques.append(_fig_a_html(_fig_crudo_vs_limpio(datos["resampleado"], datos["limpio"], cfg), "Senal cruda vs. limpia"))
        bloques.append(_fig_a_html(_fig_espectro(datos["resampleado"], datos["limpio"], cfg), "Espectro antes/despues del filtro"))

    fig_feat = _fig_features_vuelta(datos.get("features_vuelta"))
    if fig_feat is not None:
        bloques.append(_fig_a_html(fig_feat, "Features por vuelta"))

    if datos.get("vuelta_true") is not None:
        bloques.append(
            _fig_a_html(
                _fig_prediccion(
                    datos["vuelta_true"],
                    datos.get("pred_ridge"),
                    datos.get("pred_kalman"),
                    datos.get("var_kalman"),
                    float(cfg["etiquetas"]["umbral_caida"]),
                ),
                "Prediccion vs. real",
            )
        )

    fig_snr = _fig_snr(datos.get("snr"))
    if fig_snr is not None:
        bloques.append(_fig_a_html(fig_snr, "Robustez frente al ruido"))

    # tabla de metricas
    filas = []
    for nombre, met in (datos.get("metricas") or {}).items():
        if isinstance(met, dict):
            filas.append(
                "<tr><td>{}</td><td>{:.4f}</td><td>{:.4f}</td><td>{:.4f}</td></tr>".format(
                    nombre,
                    met.get("mae", float("nan")),
                    met.get("rmse", float("nan")),
                    met.get("r2", float("nan")),
                )
            )
    tabla = (
        "<table><thead><tr><th>modelo</th><th>MAE</th><th>RMSE</th><th>R2</th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table>"
    )

    # tabla de importancias (verificacion fisica)
    imp = datos.get("importancias")
    imp_tabla = ""
    if imp is not None and len(imp):
        filas_imp = "".join(
            "<tr><td>{}</td><td>{:+.4f}</td></tr>".format(html.escape(str(f)), float(c))
            for f, c in zip(imp["feature"], imp["coeficiente"])
        )
        imp_tabla = (
            "<h2>Importancias (Ridge, coeficientes estandarizados)</h2>"
            "<p>Positivo = mas degradacion. Las features estan muy correlacionadas, "
            "asi que los signos individuales no son concluyentes (verificacion fisica).</p>"
            "<table><thead><tr><th>feature</th><th>coeficiente</th></tr></thead>"
            f"<tbody>{filas_imp}</tbody></table>"
        )

    fisica = datos.get("fisica") or []
    fisica_tabla = ""
    if fisica:
        filas_fis = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}/{}</td><td>{:+.4f}</td><td>{}</td></tr>".format(
                html.escape(str(r["grupo"])),
                r["n"],
                html.escape(str(r["esperado"])),
                r["aciertos"],
                r["n"],
                float(r.get("suma", 0.0)),
                "sí" if r.get("coincide") else "no",
            )
            for r in fisica
        )
        fisica_tabla = (
            "<h2>Verificacion fisica (signos esperados)</h2>"
            "<p>Se espera coeficiente positivo en los grupos ligados al desgaste. "
            "Con features correlacionadas los signos individuales no son concluyentes; "
            "la suma por grupo es mas robusta porque los efectos que se cancelan se "
            "compensan. Es un diagnostico, no una aprobacion.</p>"
            "<table><thead><tr><th>grupo</th><th>n</th><th>esperado</th>"
            "<th>aciertos</th><th>suma</th><th>coincide</th></tr></thead>"
            f"<tbody>{filas_fis}</tbody></table>"
        )

    # cobertura de Kalman y error en la vuelta de caida
    cobertura = datos.get("cobertura")
    error_caida = datos.get("error_caida") or {}
    calidad_tabla = ""
    if cobertura is not None or error_caida:
        filas_cal = []
        if cobertura is not None:
            filas_cal.append(
                "<tr><td>Cobertura de bandas Kalman (objetivo ~0.95)</td>"
                f"<td>{float(cobertura):.2f}</td></tr>"
            )
        for nombre, val in error_caida.items():
            val_txt = "n/a" if val is None or (isinstance(val, float) and np.isnan(val)) else f"{int(val)} vueltas"
            filas_cal.append(f"<tr><td>Error vuelta de caida - {html.escape(nombre)}</td><td>{val_txt}</td></tr>")
        calidad_tabla = (
            "<h2>Cobertura y vuelta de caida</h2>"
            "<table><thead><tr><th>metrica</th><th>valor</th></tr></thead>"
            f"<tbody>{''.join(filas_cal)}</tbody></table>"
        )

    # sensibilidad de Kalman a R
    sens = datos.get("sensibilidad_kalman") or []
    sens_tabla = ""
    if sens:
        filas_sens = "".join(
            "<tr><td>{:.4g}</td><td>{:.4f}</td><td>{:.2f}</td></tr>".format(
                float(r["r"]), float(r["mae"]), float(r["cobertura"])
            )
            for r in sens
        )
        sens_tabla = (
            "<h2>Sensibilidad de Kalman a R</h2>"
            "<p>Con ~10 vueltas de test la cobertura solo toma multiplos de 0.1; "
            "se reporta la sensibilidad en vez de forzar un 0.95 exacto.</p>"
            "<table><thead><tr><th>R</th><th>MAE</th><th>cobertura</th></tr></thead>"
            f"<tbody>{filas_sens}</tbody></table>"
        )

    # trazabilidad: config usado + hash del CSV de entrada
    hash_entrada = html.escape(str(datos.get("hash_entrada", "(no disponible)")))
    entrada = html.escape(str(datos.get("entrada", "")))
    config_yaml = html.escape(datos.get("config_yaml") or "")
    trazabilidad = (
        "<h2>Trazabilidad</h2>"
        f"<p>Entrada: <code>{entrada}</code><br/>sha256: <code>{hash_entrada}</code></p>"
        "<details><summary>config.yaml usado</summary>"
        f"<pre><code>{config_yaml}</code></pre></details>"
    )

    registro = datos.get("registro") or {}
    reg_html = "".join(f"<li>{k}: {v}</li>" for k, v in registro.items())

    html_doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"/>
<title>Reporte Etapa 1</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 1000px; color:#111; }}
h1 {{ border-bottom: 2px solid #333; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
th, td {{ border: 1px solid #bbb; padding: 4px 10px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
figure {{ margin: 1.5rem 0; }}
figcaption {{ font-weight: 600; margin-bottom: .3rem; }}
img {{ max-width: 100%; border: 1px solid #eee; }}
code {{ background:#f4f4f4; padding: 2px 5px; }}
pre {{ background:#f4f4f4; padding: 10px; overflow:auto; }}
</style></head>
<body>
<h1>Reporte Etapa 1 - Pipeline offline</h1>
<p>Config: <code>{html.escape(str(cfg.get('nombre', 'config.yaml')))}</code></p>
{trazabilidad}
<h2>Metricas</h2>
{tabla}
{calidad_tabla}
{sens_tabla}
{fisica_tabla}
{imp_tabla}
<h2>Registro de calidad</h2>
<ul>{reg_html}</ul>
<h2>Figuras</h2>
{''.join(bloques)}
</body></html>
"""
    ruta_html.write_text(html_doc, encoding="utf-8")
    return ruta_html
