// Vista 3 — Predicciones: verdad/proxy, Ridge, Kalman, bandas y vuelta de caída.

import { api } from "../api.js";
import { estado, suscribir } from "../estado.js";
import { dibujarDegradacion, tablaMetricas } from "../componentes/degradacion.js";
import { pintarKpis, kpi } from "../componentes/tabla_kpis.js";
import { num } from "../formato.js";

const PLANTILLA = `
  <div class="aviso" id="v3-aviso">
    <strong>Sin sesión activa.</strong><br />Carga un CSV para ver las predicciones.
  </div>
  <div id="v3-contenido" class="oculto">
    <div class="barra-controles">
      <div class="grupo"><label>Umbral de caída</label>
        <input type="range" id="v3-umbral" min="0.1" max="0.95" step="0.05" value="0.5" style="width:200px" />
        <span class="pill" id="v3-umbral-valor">0.50</span>
      </div>
      <div class="separador"></div>
      <span class="pill" id="v3-sesion"></span>
    </div>
    <div class="kpis" id="v3-kpis"></div>
    <section class="panel">
      <h3>Evolución de la degradación <span class="texto-dim mono">verdad · proxy · Ridge · Kalman</span></h3>
      <div class="grafica" id="v3-grafica"></div>
    </section>
    <section class="panel">
      <h3>Métricas de precisión <span class="texto-dim mono">sobre el tramo de test</span></h3>
      <div id="v3-tabla"></div>
    </section>
  </div>
`;

export function montar(contenedor) {
  contenedor.innerHTML = PLANTILLA;
  const q = (sel) => contenedor.querySelector(sel);
  const ui = {
    aviso: q("#v3-aviso"),
    contenido: q("#v3-contenido"),
    umbral: q("#v3-umbral"),
    umbralValor: q("#v3-umbral-valor"),
    sesion: q("#v3-sesion"),
    kpis: q("#v3-kpis"),
    grafica: q("#v3-grafica"),
    tabla: q("#v3-tabla"),
  };

  let panel = null;
  let datos = null; // { ridge, kalman }
  let umbral = Number(ui.umbral.value);
  let sesionPrevia;
  let activo = true;

  function dibujar() {
    if (!datos) return;
    const { ridge, kalman } = datos;

    if (panel) panel.destruir();
    const dibujo = dibujarDegradacion(ui.grafica, ridge, kalman, umbral);
    panel = dibujo.panel;

    const { verdad: cVerdad, ridge: cRidge, kalman: cKalman } = dibujo.cruces;
    const dRidge = cVerdad != null && cRidge != null ? Math.abs(cRidge - cVerdad) : null;
    const dKalman = cVerdad != null && cKalman != null ? Math.abs(cKalman - cVerdad) : null;

    pintarKpis(ui.kpis, [
      kpi("Caída real", cVerdad ?? "—", { pie: `umbral ${num(umbral, 2)}`, tono: "accent" }),
      kpi("Δ Ridge", dRidge == null ? "—" : num(dRidge, 0), { unidad: "vueltas", tono: dRidge === 0 ? "ok" : "warn" }),
      kpi("Δ Kalman", dKalman == null ? "—" : num(dKalman, 0), { unidad: "vueltas", tono: dKalman === 0 ? "ok" : "warn" }),
      kpi("MAE Ridge", num(ridge.metricas.mae, 4), { pie: `α=${num(ridge.alpha, 3)}`, tono: "ok" }),
      kpi("MAE Kalman", num(kalman.metricas.mae, 4), { pie: `cobertura ${(kalman.cobertura * 100).toFixed(0)} %` }),
      kpi("R² Kalman", num(kalman.metricas.r2, 3), {}),
    ]);
    ui.tabla.innerHTML = tablaMetricas(ridge, kalman);
  }

  async function recargar() {
    if (!estado.sesionActiva) {
      ui.aviso.classList.remove("oculto");
      ui.contenido.classList.add("oculto");
      return;
    }
    ui.aviso.classList.add("oculto");
    ui.contenido.classList.remove("oculto");
    ui.sesion.textContent = `${estado.sesionActiva.id} · ${estado.laps.length} vueltas`;
    try {
      const [ridge, kalman] = await Promise.all([api.ridge({}), api.kalman({})]);
      if (!activo) return;
      datos = { ridge, kalman };
      dibujar();
    } catch (error) {
      if (!activo) return;
      pintarKpis(ui.kpis, [kpi("Error", "—", { pie: error.message, tono: "bad" })]);
    }
  }

  ui.umbral.addEventListener("input", () => {
    umbral = Number(ui.umbral.value);
    ui.umbralValor.textContent = num(umbral, 2);
    dibujar();
  });

  const desuscribir = suscribir((e) => {
    if (e.sesionActiva === sesionPrevia) return;
    sesionPrevia = e.sesionActiva;
    datos = null;
    recargar();
  });

  sesionPrevia = estado.sesionActiva;
  ui.umbralValor.textContent = num(umbral, 2);
  recargar();

  return () => {
    activo = false;
    desuscribir();
    panel?.destruir();
  };
}
