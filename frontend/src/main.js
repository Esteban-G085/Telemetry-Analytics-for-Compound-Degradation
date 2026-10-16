// Punto de entrada: shell (sesión, pestañas, WebSocket) y enrutado de vistas.

import "./estilos/variables.css";
import "./estilos/layout.css";
import "./estilos/widgets.css";
import "./estilos/uplot_tema.css";

import { api, CanalTelemetria } from "./api.js";
import { actualizar } from "./estado.js";
import { activarSesion, ponerPill } from "./sesion.js";
import * as vTelemetria from "./vistas/v_telemetria.js";
import * as vEspectro from "./vistas/v_espectro.js";
import * as vPrediccion from "./vistas/v_prediccion.js";
import * as vLaboratorio from "./vistas/v_laboratorio.js";
import * as vRobustez from "./vistas/v_robustez.js";
import * as vReplay from "./vistas/v_replay.js";

const VISTAS = [
  { id: "telemetria", num: "1", titulo: "Telemetría", modulo: vTelemetria },
  { id: "espectro", num: "2", titulo: "Espectro", modulo: vEspectro },
  { id: "prediccion", num: "3", titulo: "Predicción", modulo: vPrediccion },
  { id: "laboratorio", num: "4", titulo: "Laboratorio", modulo: vLaboratorio },
  { id: "robustez", num: "5", titulo: "Robustez", modulo: vRobustez },
  { id: "replay", num: "6", titulo: "Replay", modulo: vReplay },
];

const ui = {
  tabs: document.getElementById("tabs"),
  vista: document.getElementById("vista"),
  sesion: document.getElementById("sel-sesion"),
  archivo: document.getElementById("archivo"),
  estadoSesion: document.getElementById("estado-sesion"),
};

let limpiarVista = null;
let vistaActual = null;

// --------------------------------------------------------------------------
// Pestañas y enrutado
// --------------------------------------------------------------------------
function pintarTabs() {
  ui.tabs.innerHTML = VISTAS.map(
    (v) =>
      `<button class="tab" data-vista="${v.id}"><span class="num">${v.num}</span>${v.titulo}</button>`,
  ).join("");
  ui.tabs.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-vista]");
    if (b) montarVista(b.dataset.vista);
  });
}

function montarVista(id) {
  const vista = VISTAS.find((v) => v.id === id);
  if (!vista || id === vistaActual) return;
  limpiarVista?.();
  limpiarVista = null;
  ui.vista.innerHTML = "";
  vistaActual = id;
  for (const b of ui.tabs.children) b.classList.toggle("activa", b.dataset.vista === id);
  limpiarVista = vista.modulo.montar(ui.vista) ?? null;
}

// --------------------------------------------------------------------------
// Sesión (selector + subida)
// --------------------------------------------------------------------------
async function refrescarLista() {
  const datos = await api.sesiones();
  ui.sesion.innerHTML =
    `<option value="">— elegir sesión —</option>` +
    datos.sesiones
      .map(
        (s) =>
          `<option value="${s.nombre}"${s.cargada ? " selected" : ""}>${s.nombre} · ${s.kb} kB${
            s.tiene_verdad ? " · verdad" : ""
          }</option>`,
      )
      .join("");
  if (datos.activa) ui.sesion.value = datos.activa.endsWith(".csv") ? datos.activa : `${datos.activa}.csv`;
}

async function activarYListar(resumen) {
  await activarSesion(resumen);
  ponerPill(`${resumen.id} · ${resumen.n_muestras.toLocaleString("es-ES")} muestras`, "ok");
  await refrescarLista();
}

async function cargarSesion(nombre) {
  if (!nombre) return;
  ponerPill("cargando…", "warn");
  try {
    await activarYListar(await api.cargar(nombre));
  } catch (error) {
    ponerPill(`error: ${error.message}`, "bad");
  }
}

async function subirArchivo(archivo) {
  ponerPill("subiendo…", "warn");
  try {
    await activarYListar(await api.subir(archivo));
  } catch (error) {
    ponerPill(`error: ${error.message}`, "bad");
  }
}

// --------------------------------------------------------------------------
// WebSocket (D3): los resultados de Kalman/Ridge se publican en el estado.
// --------------------------------------------------------------------------
function conectarWS() {
  const canal = new CanalTelemetria({
    onEstado: (estadoWs) => {
      actualizar({ wsEstado: estadoWs });
      const pill = document.getElementById("ws-estado");
      if (pill) pill.className = `pill ${estadoWs === "conectado" ? "ok" : estadoWs === "conectando" ? "warn" : "bad"}`;
      if (pill) pill.innerHTML = `<span class="punto"></span>${estadoWs}`;
    },
    onMensaje: (msg) => {
      if (msg.tipo === "kalman") actualizar({ ultimoKalman: msg });
      else if (msg.tipo === "ridge") actualizar({ ultimoRidge: msg });
    },
  });
  window.__telemetriaWS = canal;
}

// --------------------------------------------------------------------------
// Arranque
// --------------------------------------------------------------------------
async function iniciar() {
  pintarTabs();
  montarVista("telemetria");

  const pill = document.createElement("span");
  pill.id = "ws-estado";
  pill.className = "pill";
  pill.innerHTML = `<span class="punto"></span>desconectado`;
  ui.estadoSesion.after(pill);

  ui.sesion.addEventListener("change", () => cargarSesion(ui.sesion.value));
  ui.archivo.addEventListener("change", () => {
    if (ui.archivo.files[0]) subirArchivo(ui.archivo.files[0]);
    ui.archivo.value = "";
  });

  // Arrastrar y soltar CSV sobre la vista.
  const zona = document.body;
  for (const tipo of ["dragover", "dragenter"]) {
    zona.addEventListener(tipo, (ev) => ev.preventDefault());
  }
  zona.addEventListener("drop", (ev) => {
    ev.preventDefault();
    const archivo = ev.dataTransfer?.files?.[0];
    if (archivo) subirArchivo(archivo);
  });

  conectarWS();

  try {
    await refrescarLista();
    const { activa } = await api.sesiones();
    if (activa) {
      const resumen = await api.sesionActiva();
      await activarSesion(resumen);
      ponerPill(`${resumen.id} · ${resumen.n_muestras.toLocaleString("es-ES")} muestras`, "ok");
    } else {
      ponerPill("sin sesión", "");
    }
  } catch (error) {
    ponerPill(`error: ${error.message}`, "bad");
  }
}

iniciar();
