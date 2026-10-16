// Vista 4 — Laboratorio de parámetros.
//
// Dos familias de controles:
//   · Modelo (Ridge α, Kalman Q/R, monotonicidad, ablación) → reactivos por
//     WebSocket: el servidor recalcula y devuelve la curva sin recargar.
//   · Limpieza y features (corte, MAD, grados-segundo, k_fuel) → requieren
//     reprocesar la sesión: se guardan como overrides y se recarga el CSV.

import { api } from "../api.js";
import { estado, suscribir } from "../estado.js";
import { recargarSesion, ponerPill } from "../sesion.js";
import { crearPanelDegradacion, pintarDegradacion, tablaMetricas } from "../componentes/degradacion.js";
import { pintarKpis, kpi } from "../componentes/tabla_kpis.js";
import { num } from "../formato.js";

// Controles reactivos (WebSocket). El valor del slider es el exponente log10.
const MODELO = [
  { id: "alpha", etiqueta: "α Ridge", min: -3, max: 3, paso: 0.05, formato: (v) => num(10 ** v, 4) },
  { id: "q_nivel", etiqueta: "Q nivel", min: -6, max: -2, paso: 0.1, formato: (v) => `10^${num(v, 2)}` },
  { id: "q_pendiente", etiqueta: "Q pendiente", min: -7, max: -3, paso: 0.1, formato: (v) => `10^${num(v, 2)}` },
  { id: "r", etiqueta: "R medición", min: -5, max: -1, paso: 0.1, formato: (v) => `10^${num(v, 2)}` },
];

// Controles que obligan a reprocesar la sesión (valores lineales).
const PIPELINE = [
  { id: "corte", etiqueta: "Corte Butterworth", unidad: "Hz", min: 5, max: 40, paso: 0.5, ruta: ["limpieza", "filtro", "corte_hz"], formato: (v) => num(v, 1) },
  { id: "mad", etiqueta: "Umbral MAD", unidad: "σ", min: 6, max: 20, paso: 0.5, ruta: ["limpieza", "outlier_mad_umbral"], formato: (v) => num(v, 1) },
  { id: "temp", etiqueta: "Umbral grados·segundo", unidad: "°C", min: 70, max: 110, paso: 1, ruta: ["features", "temp_umbral_c"], formato: (v) => num(v, 0) },
  { id: "kfuel", etiqueta: "k_fuel", unidad: "s/kg", min: 0.01, max: 0.08, paso: 0.001, ruta: ["etiquetas", "k_fuel_s_kg"], formato: (v) => num(v, 3) },
];

// Interpolación causal de huecos: activa = 0.5 s, desactivada = 0 (solo aísla).
const HUECO_MAX_S = 0.5;

// Ablación física (D15): quita los grupos derivados de estas subcadenas.
// Misma lista que main.py:148 (ablación por circularidad de la Etapa 1).
const ABLACION = ["slip", "temp", "psd", "grados_segundo", "trabajo"];

function filaControl(p) {
  return `
    <div class="control">
      <label for="v4-${p.id}">${p.etiqueta}${p.unidad ? ` <span class="texto-dim">[${p.unidad}]</span>` : ""}</label>
      <span class="valor mono" id="v4-${p.id}-valor">—</span>
      <input type="range" id="v4-${p.id}" min="${p.min}" max="${p.max}" step="${p.paso}" />
    </div>`;
}

const PLANTILLA = `
  <div class="aviso" id="v4-aviso">
    <strong>Sin sesión activa.</strong><br />Carga un CSV para ajustar los parámetros.
  </div>
  <div id="v4-contenido" class="oculto">
    <div class="barra-controles">
      <span class="pill" id="v4-sesion"></span>
      <span class="pill" id="v4-proceso"></span>
      <div class="separador"></div>
      <button class="btn" id="v4-guardar">Guardar config</button>
      <button class="btn ghost" id="v4-descargar">Descargar YAML</button>
      <button class="btn ghost" id="v4-reset">Restablecer</button>
    </div>
    <div class="kpis" id="v4-kpis"></div>
    <div class="rejilla lab">
      <section class="panel">
        <h3>Modelo <span class="texto-dim mono">reactivo · WebSocket</span></h3>
        <div class="controles-lista">
          ${MODELO.map(filaControl).join("")}
          <label class="switch"><input type="checkbox" id="v4-ablacion" /> Ablación (sin slip/temperatura/PSD/grados/fricción)</label>
          <label class="switch"><input type="checkbox" id="v4-monotono" /> Monotonicidad estricta (Kalman)</label>
        </div>
      </section>
      <section class="panel">
        <h3>Limpieza y features <span class="texto-dim mono">reprocesa la sesión</span></h3>
        <div class="controles-lista">
          ${PIPELINE.map(filaControl).join("")}
          <label class="switch"><input type="checkbox" id="v4-huecos" /> Interpolar huecos cortos (≤ 0.5 s)</label>
          <label class="switch"><input type="checkbox" id="v4-calibrar" /> Calibrar k_fuel por regresión</label>
        </div>
      </section>
    </div>
    <section class="panel">
      <h3>Evolución de la degradación <span class="texto-dim mono">los sliders redibujan esta curva</span></h3>
      <div class="grafica" id="v4-grafica"></div>
    </section>
    <section class="panel">
      <h3>Métricas de precisión <span class="texto-dim mono">tramo de test</span></h3>
      <div id="v4-tabla"></div>
    </section>
  </div>
`;

const leerRuta = (obj, ruta) => ruta.reduce((o, k) => (o == null ? undefined : o[k]), obj);

function escribirRuta(destino, ruta, valor) {
  const claves = [...ruta];
  const ultima = claves.pop();
  let nodo = destino;
  for (const k of claves) {
    if (typeof nodo[k] !== "object" || nodo[k] === null) nodo[k] = {};
    nodo = nodo[k];
  }
  nodo[ultima] = valor;
}

export function montar(contenedor) {
  contenedor.innerHTML = PLANTILLA;
  const q = (sel) => contenedor.querySelector(sel);
  const ui = {
    aviso: q("#v4-aviso"),
    contenido: q("#v4-contenido"),
    sesion: q("#v4-sesion"),
    proceso: q("#v4-proceso"),
    kpis: q("#v4-kpis"),
    grafica: q("#v4-grafica"),
    tabla: q("#v4-tabla"),
    ablacion: q("#v4-ablacion"),
    monotono: q("#v4-monotono"),
    huecos: q("#v4-huecos"),
    calibrar: q("#v4-calibrar"),
    guardar: q("#v4-guardar"),
    descargar: q("#v4-descargar"),
    reset: q("#v4-reset"),
  };

  let config = null;
  let datos = null; // { ridge, kalman }
  let panel = null;
  let umbral = 0.5;
  let sesionPrevia;
  let activo = true;
  let procesando = false;
  let ultimoRidge = null;
  let ultimoKalman = null;
  let temporizadorModelo = null;
  let temporizadorPipeline = null;

  // --- sliders ---------------------------------------------------------
  function setControl(p, valor) {
    const input = q(`#v4-${p.id}`);
    const salida = q(`#v4-${p.id}-valor`);
    if (!input || valor == null || Number.isNaN(valor)) return;
    input.value = String(valor);
    if (salida) salida.textContent = p.formato(Number(valor));
  }

  function valorControl(p) {
    return Number(q(`#v4-${p.id}`).value);
  }

  function aplicarConfig(cfg) {
    config = cfg;
    umbral = Number(cfg.etiquetas?.umbral_caida ?? 0.5);
    for (const p of PIPELINE) setControl(p, leerRuta(cfg, p.ruta));
    const kal = cfg.modelo?.kalman ?? {};
    setControl(MODELO[1], Math.log10(kal.q_nivel ?? 1e-4));
    setControl(MODELO[2], Math.log10(kal.q_pendiente ?? 1e-5));
    setControl(MODELO[3], Math.log10(kal.r ?? 1e-3));
    ui.monotono.checked = kal.monotono ?? true;
    ui.huecos.checked = Number(cfg.limpieza?.hueco_max_s ?? 0) > 0;
    ui.calibrar.checked = Boolean(cfg.etiquetas?.calibrar_k_fuel);
  }

  function paramsKalman() {
    return {
      q_nivel: 10 ** valorControl(MODELO[1]),
      q_pendiente: 10 ** valorControl(MODELO[2]),
      r: 10 ** valorControl(MODELO[3]),
      monotono: ui.monotono.checked,
    };
  }

  function overridesPipeline() {
    const o = {};
    for (const p of PIPELINE) escribirRuta(o, p.ruta, valorControl(p));
    escribirRuta(o, ["limpieza", "hueco_max_s"], ui.huecos.checked ? HUECO_MAX_S : 0);
    escribirRuta(o, ["etiquetas", "calibrar_k_fuel"], ui.calibrar.checked);
    return o;
  }

  function overridesCompletos() {
    const o = overridesPipeline();
    escribirRuta(o, ["modelo", "kalman"], paramsKalman());
    escribirRuta(o, ["modelo", "ridge_alphas"], [10 ** valorControl(MODELO[0])]);
    return o;
  }

  // --- dibujo ----------------------------------------------------------
  function dibujar() {
    if (!datos?.ridge || !datos?.kalman) return;
    if (!panel) panel = crearPanelDegradacion(ui.grafica);
    const cruces = pintarDegradacion(panel, datos.ridge, datos.kalman, umbral);

    const dRidge = cruces.verdad != null && cruces.ridge != null ? Math.abs(cruces.ridge - cruces.verdad) : null;
    const dKalman = cruces.verdad != null && cruces.kalman != null ? Math.abs(cruces.kalman - cruces.verdad) : null;
    const { ridge, kalman } = datos;
    pintarKpis(ui.kpis, [
      kpi("α Ridge", num(ridge.alpha, 4), { pie: `CV MAE ${num(ridge.cv_mae, 4)}`, tono: "ok" }),
      kpi("MAE Ridge", num(ridge.metricas.mae, 4), { pie: "test" }),
      kpi("MAE Kalman", num(kalman.metricas.mae, 4), { pie: `cobertura ${(kalman.cobertura * 100).toFixed(0)} %` }),
      kpi("Δ Ridge", dRidge == null ? "—" : num(dRidge, 0), { unidad: "vueltas", tono: dRidge === 0 ? "ok" : "warn" }),
      kpi("Δ Kalman", dKalman == null ? "—" : num(dKalman, 0), { unidad: "vueltas", tono: dKalman === 0 ? "ok" : "warn" }),
    ]);
    ui.tabla.innerHTML = tablaMetricas(ridge, kalman);
  }

  // --- peticiones de modelo -------------------------------------------
  async function pedirRidge() {
    const overrides = { alpha: 10 ** valorControl(MODELO[0]), excluir: ui.ablacion.checked ? ABLACION : [] };
    const canal = window.__telemetriaWS;
    if (canal?.abierto) {
      canal.enviar({ tipo: "ajuste_ridge", ...overrides });
      return;
    }
    const ridge = await api.ridge(overrides);
    if (!activo) return;
    datos = { ...(datos ?? {}), ridge };
    ultimoRidge = ridge;
    dibujar();
  }

  async function pedirKalman() {
    const overrides = paramsKalman();
    const canal = window.__telemetriaWS;
    if (canal?.abierto) {
      canal.enviar({ tipo: "ajuste_kalman", ...overrides });
      return;
    }
    const kalman = await api.kalman(overrides);
    if (!activo) return;
    datos = { ...(datos ?? {}), kalman };
    ultimoKalman = kalman;
    dibujar();
  }

  function agendarModelo(cual) {
    clearTimeout(temporizadorModelo);
    temporizadorModelo = setTimeout(() => {
      if (cual === "ridge") pedirRidge();
      else pedirKalman();
    }, 120);
  }

  // --- reproceso de la sesión -----------------------------------------
  async function reprocesar() {
    if (procesando || !estado.sesionActiva) return;
    procesando = true;
    ui.proceso.textContent = "reprocesando…";
    ui.proceso.className = "pill warn";
    for (const p of PIPELINE) q(`#v4-${p.id}`).disabled = true;
    try {
      const { config: nueva } = await api.guardarConfig(overridesPipeline());
      config = nueva;
      const resumen = await recargarSesion(estado.sesionActiva.nombre);
      ponerPill(`${resumen.id} · ${resumen.n_muestras.toLocaleString("es-ES")} muestras`, "ok");
      ui.proceso.textContent = "actualizado";
      ui.proceso.className = "pill ok";
    } catch (error) {
      ui.proceso.textContent = `error: ${error.message}`;
      ui.proceso.className = "pill bad";
    } finally {
      procesando = false;
      for (const p of PIPELINE) q(`#v4-${p.id}`).disabled = false;
    }
  }

  function agendarPipeline() {
    clearTimeout(temporizadorPipeline);
    temporizadorPipeline = setTimeout(reprocesar, 600);
  }

  // --- acciones de barra ----------------------------------------------
  async function guardar() {
    try {
      const { config: nueva } = await api.guardarConfig(overridesCompletos());
      config = nueva;
      ui.proceso.textContent = "guardado en servidor";
      ui.proceso.className = "pill ok";
    } catch (error) {
      ui.proceso.textContent = `error: ${error.message}`;
      ui.proceso.className = "pill bad";
    }
  }

  async function descargar() {
    try {
      await api.guardarConfig(overridesCompletos());
      const texto = await (await fetch(api.urlExportarConfig)).text();
      const url = URL.createObjectURL(new Blob([texto], { type: "text/yaml" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "config_custom.yaml";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      ui.proceso.textContent = "YAML descargado";
      ui.proceso.className = "pill ok";
    } catch (error) {
      ui.proceso.textContent = `error: ${error.message}`;
      ui.proceso.className = "pill bad";
    }
  }

  async function restablecer() {
    try {
      const { config: nueva } = await api.reiniciarConfig();
      aplicarConfig(nueva);
      await reprocesar();
      ui.proceso.textContent = "config de fábrica";
      ui.proceso.className = "pill";
    } catch (error) {
      ui.proceso.textContent = `error: ${error.message}`;
      ui.proceso.className = "pill bad";
    }
  }

  // --- ciclo de vida ---------------------------------------------------
  async function inicializar() {
    ui.aviso.classList.add("oculto");
    ui.contenido.classList.remove("oculto");
    ui.sesion.textContent = `${estado.sesionActiva.id} · ${estado.laps.length} vueltas`;
    try {
      const [{ config: cfg }, ridge, kalman] = await Promise.all([api.config(), api.ridge({}), api.kalman({})]);
      if (!activo) return;
      aplicarConfig(cfg);
      setControl(MODELO[0], Math.log10(ridge.alpha));
      ultimoRidge = ridge;
      ultimoKalman = kalman;
      datos = { ridge, kalman };
      dibujar();
    } catch (error) {
      if (!activo) return;
      pintarKpis(ui.kpis, [kpi("Error", "—", { pie: error.message, tono: "bad" })]);
    }
  }

  async function recargar() {
    if (!estado.sesionActiva) {
      ui.aviso.classList.remove("oculto");
      ui.contenido.classList.add("oculto");
      return;
    }
    await inicializar();
  }

  // --- eventos ---------------------------------------------------------
  for (const p of MODELO) {
    q(`#v4-${p.id}`).addEventListener("input", () => {
      const salida = q(`#v4-${p.id}-valor`);
      if (salida) salida.textContent = p.formato(valorControl(p));
      agendarModelo(p.id === "alpha" ? "ridge" : "kalman");
    });
  }
  for (const p of PIPELINE) {
    q(`#v4-${p.id}`).addEventListener("input", () => {
      const salida = q(`#v4-${p.id}-valor`);
      if (salida) salida.textContent = p.formato(valorControl(p));
      agendarPipeline();
    });
  }
  ui.ablacion.addEventListener("change", () => agendarModelo("ridge"));
  ui.monotono.addEventListener("change", () => agendarModelo("kalman"));
  ui.huecos.addEventListener("change", agendarPipeline);
  ui.calibrar.addEventListener("change", agendarPipeline);
  ui.guardar.addEventListener("click", guardar);
  ui.descargar.addEventListener("click", descargar);
  ui.reset.addEventListener("click", restablecer);

  const desuscribir = suscribir((e) => {
    if (e.sesionActiva !== sesionPrevia) {
      sesionPrevia = e.sesionActiva;
      datos = null;
      recargar();
      return;
    }
    if (e.ultimoRidge && e.ultimoRidge !== ultimoRidge) {
      ultimoRidge = e.ultimoRidge;
      datos = { ...(datos ?? {}), ridge: e.ultimoRidge };
      dibujar();
    } else if (e.ultimoKalman && e.ultimoKalman !== ultimoKalman) {
      ultimoKalman = e.ultimoKalman;
      datos = { ...(datos ?? {}), kalman: e.ultimoKalman };
      dibujar();
    }
  });

  sesionPrevia = estado.sesionActiva;
  recargar();

  return () => {
    activo = false;
    clearTimeout(temporizadorModelo);
    clearTimeout(temporizadorPipeline);
    desuscribir();
    panel?.destruir();
  };
}
