// Vista 1 — Señal cruda vs. limpia: control de calidad y outliers.

import { api } from "../api.js";
import { estado, suscribir, actualizar } from "../estado.js";
import { Panel, color, linea, huecosDe } from "../componentes/graficas.js";
import { pintarKpis, kpi } from "../componentes/tabla_kpis.js";
import { num, entero } from "../formato.js";

const MAGNITUDES = [
  { id: "wheel_slip", nombre: "Slip", unidad: "" },
  { id: "temp_core_c", nombre: "Temperatura", unidad: "°C" },
  { id: "wheel_load_n", nombre: "Carga", unidad: "N" },
  { id: "pressure_psi", nombre: "Presión", unidad: "psi" },
];

const RUEDAS = [
  { id: "fl", nombre: "FL" },
  { id: "fr", nombre: "FR" },
  { id: "rl", nombre: "RL" },
  { id: "rr", nombre: "RR" },
];

const REFERENCIAS = [
  { id: "speed_kmh", nombre: "Velocidad", unidad: "km/h" },
  { id: "throttle", nombre: "Acelerador", unidad: "%" },
  { id: "brake", nombre: "Freno", unidad: "%" },
  { id: "steering", nombre: "Dirección", unidad: "" },
  { id: "fuel_kg", nombre: "Combustible", unidad: "kg" },
];

const COLORES_RUEDA = { fl: "--w-fl", fr: "--w-fr", rl: "--w-rl", rr: "--w-rr" };
const COLORES_MAGNITUD = {
  wheel_slip: "--slip",
  temp_core_c: "--temp",
  wheel_load_n: "--carga",
  pressure_psi: "--presion",
  speed_kmh: "--speed",
  throttle: "--ok",
  brake: "--bad",
  steering: "--accent",
  fuel_kg: "--warn",
};

function colorDeCanal(canal) {
  const rueda = canal.slice(-2);
  if (COLORES_RUEDA[rueda]) return color(COLORES_RUEDA[rueda]);
  const magnitud = canal.replace(/_(fl|fr|rl|rr)$/, "");
  return color(COLORES_MAGNITUD[magnitud] ?? "--accent");
}

function magnitudDe(canal) {
  const id = canal.replace(/_(fl|fr|rl|rr)$/, "");
  return MAGNITUDES.find((m) => m.id === id);
}

const PLANTILLA = `
  <div class="aviso" id="v1-aviso">
    <strong>Sin sesión activa.</strong><br />
    Elige un CSV en la barra superior o arrastra un archivo aquí para empezar.
  </div>
  <div id="v1-contenido" class="oculto">
    <div class="barra-controles">
      <div class="grupo"><label>Canal</label><div class="pastillas" id="v1-canal"></div></div>
      <div class="grupo"><label>Rueda</label><div class="pastillas" id="v1-rueda"></div></div>
      <div class="grupo"><label>Referencia</label><select class="input" id="v1-ref"></select></div>
      <div class="separador"></div>
      <div class="grupo">
        <button class="btn icono" id="v1-prev" title="Vuelta anterior">←</button>
        <span class="pill" id="v1-lap">Vuelta —</span>
        <button class="btn icono" id="v1-next" title="Vuelta siguiente">→</button>
        <label class="switch"><input type="checkbox" id="v1-stint" /> Stint completo</label>
      </div>
    </div>
    <div class="kpis" id="v1-kpis"></div>
    <section class="panel">
      <h3>Señal · crudo vs. limpio <span class="texto-dim mono" id="v1-titulo"></span></h3>
      <div class="grafica" id="v1-grafica"></div>
    </section>
    <section class="panel">
      <h3>Referencia <span class="texto-dim mono" id="v1-titulo-ref"></span></h3>
      <div class="grafica" id="v1-ref-grafica"></div>
    </section>
  </div>
`;

export function montar(contenedor) {
  contenedor.innerHTML = PLANTILLA;
  const q = (sel) => contenedor.querySelector(sel);
  const ui = {
    aviso: q("#v1-aviso"),
    contenido: q("#v1-contenido"),
    canal: q("#v1-canal"),
    rueda: q("#v1-rueda"),
    ref: q("#v1-ref"),
    lap: q("#v1-lap"),
    prev: q("#v1-prev"),
    next: q("#v1-next"),
    stint: q("#v1-stint"),
    kpis: q("#v1-kpis"),
    titulo: q("#v1-titulo"),
    tituloRef: q("#v1-titulo-ref"),
    grafica: q("#v1-grafica"),
    refGrafica: q("#v1-ref-grafica"),
  };

  let panel = null;
  let panelRef = null;
  let sesionPrevia;
  let peticion = 0;
  let activo = true;

  ui.canal.innerHTML = MAGNITUDES.map(
    (m) => `<button class="pastilla" data-canal="${m.id}">${m.nombre}</button>`,
  ).join("");
  ui.rueda.innerHTML = RUEDAS.map(
    (r) => `<button class="pastilla" data-rueda="${r.id}">${r.nombre}</button>`,
  ).join("");

  const canalPrincipal = () => `${estado.canal}_${estado.rueda}`;

  function sincronizarControles() {
    for (const b of ui.canal.children) b.classList.toggle("activa", b.dataset.canal === estado.canal);
    for (const b of ui.rueda.children) b.classList.toggle("activa", b.dataset.rueda === estado.rueda);
    ui.stint.checked = estado.stint;
    const n = estado.laps.length;
    const indice = estado.laps.indexOf(estado.lap);
    ui.lap.textContent = estado.stint
      ? "Stint completo"
      : `Vuelta ${indice >= 0 ? indice + 1 : "—"} / ${n || "—"}`;
    ui.prev.disabled = estado.stint || indice <= 0;
    ui.next.disabled = estado.stint || indice < 0 || indice >= n - 1;
    const magn = magnitudDe(canalPrincipal());
    ui.titulo.textContent = `${canalPrincipal()}${magn?.unidad ? ` [${magn.unidad}]` : ""}`;
    const ref = REFERENCIAS.find((r) => r.id === estado.ref);
    ui.tituloRef.textContent = estado.ref ? `${estado.ref}${ref?.unidad ? ` [${ref.unidad}]` : ""}` : "";
  }

  function refrescarOpciones() {
    const disponibles = REFERENCIAS.filter((r) => estado.canales.includes(r.id));
    if (!disponibles.some((r) => r.id === estado.ref)) estado.ref = disponibles[0]?.id ?? "speed_kmh";
    ui.ref.innerHTML = disponibles.map((r) => `<option value="${r.id}">${r.nombre}</option>`).join("");
    ui.ref.value = estado.ref ?? "";
    ui.ref.disabled = disponibles.length === 0;
  }

  function construir(payload, canal) {
    const t = payload.t;
    const limpio = payload.series[canal] ?? [];
    const crudo = payload.crudo?.[canal] ?? null;
    const series = [];
    const data = [t];
    if (crudo) {
      series.push(linea({ etiqueta: "crudo", color: "rgba(148, 163, 184, 0.5)", ancho: 1 }));
      data.push(crudo);
    }
    series.push(linea({ etiqueta: "limpio", color: colorDeCanal(canal), ancho: 1.6 }));
    data.push(limpio);
    const marcadores = (payload.outliers?.[canal] ?? []).map((i) => ({ x: t[i], y: limpio[i] }));
    return { series, data, marcadores, huecos: huecosDe(t, payload.valido ?? []) };
  }

  function pintar(payload) {
    const principal = canalPrincipal();

    if (panel) panel.destruir();
    if (panelRef) panelRef.destruir();

    const principalDatos = construir(payload, principal);
    panel = new Panel(ui.grafica, { series: principalDatos.series, ejeY: { size: 58 } });
    panel.datos(principalDatos.data);
    panel.anotaciones({ marcadores: principalDatos.marcadores, huecos: principalDatos.huecos });

    const refDatos = construir(payload, estado.ref);
    panelRef = new Panel(ui.refGrafica, { series: refDatos.series, altura: 190, ejeY: { size: 58 } });
    panelRef.datos(refDatos.data);
    panelRef.anotaciones({ huecos: refDatos.huecos });

    const k = payload.kpis;
    const atenuacion = k.atenuacion_db?.[principal];
    const duracion = estado.vueltas.find((v) => v.lap === estado.lap)?.duracion_s;
    pintarKpis(ui.kpis, [
      kpi("Muestras", entero(payload.n), {
        pie: payload.downsample ? `min/max de ${entero(payload.n_total)}` : `${entero(payload.n_total)} originales`,
        tono: "accent",
      }),
      kpi("Vuelta", payload.lap ?? "stint", { pie: duracion ? `${num(duracion, 2)} s` : "" }),
      kpi("Inválidos", entero(k.n_invalidos), { tono: k.n_invalidos > 0 ? "warn" : "ok" }),
      kpi("Outliers", entero(k.outliers_total), { tono: k.outliers_total > 0 ? "warn" : "ok" }),
      kpi("Atenuación", atenuacion == null ? "—" : num(atenuacion, 1), { unidad: "dB", pie: "crudo vs. limpio" }),
      kpi("fs", num(payload.fs, 0), { unidad: "Hz" }),
    ]);
  }

  function mostrarAviso() {
    ui.aviso.classList.remove("oculto");
    ui.contenido.classList.add("oculto");
  }

  function mostrarContenido() {
    ui.aviso.classList.add("oculto");
    ui.contenido.classList.remove("oculto");
  }

  async function recargar() {
    if (!estado.sesionActiva) {
      mostrarAviso();
      return;
    }
    mostrarContenido();
    const id = ++peticion;
    try {
      const canales = [canalPrincipal(), estado.ref].filter(Boolean);
      const payload = estado.stint
        ? await api.stint({ canales })
        : await api.vuelta(estado.lap, { canales });
      if (!activo || id !== peticion) return;
      pintar(payload);
    } catch (error) {
      if (!activo || id !== peticion) return;
      pintarKpis(ui.kpis, [kpi("Error", "—", { pie: error.message, tono: "bad" })]);
    }
  }

  // --- interacción ---
  ui.canal.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-canal]");
    if (!b) return;
    actualizar({ canal: b.dataset.canal });
    sincronizarControles();
    recargar();
  });
  ui.rueda.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-rueda]");
    if (!b) return;
    actualizar({ rueda: b.dataset.rueda });
    sincronizarControles();
    recargar();
  });
  ui.ref.addEventListener("change", () => {
    actualizar({ ref: ui.ref.value });
    sincronizarControles();
    recargar();
  });
  ui.stint.addEventListener("change", () => {
    actualizar({ stint: ui.stint.checked });
    sincronizarControles();
    recargar();
  });
  const mover = (delta) => {
    const i = estado.laps.indexOf(estado.lap);
    const j = Math.min(Math.max(i + delta, 0), estado.laps.length - 1);
    if (j === i || j < 0) return;
    actualizar({ lap: estado.laps[j] });
    sincronizarControles();
    recargar();
  };
  ui.prev.addEventListener("click", () => mover(-1));
  ui.next.addEventListener("click", () => mover(1));

  const alTeclear = (ev) => {
    if (estado.stint || ev.target.tagName === "SELECT") return;
    if (ev.key === "ArrowLeft") mover(-1);
    if (ev.key === "ArrowRight") mover(1);
  };
  document.addEventListener("keydown", alTeclear);

  const desuscribir = suscribir((e) => {
    if (e.sesionActiva === sesionPrevia) return;
    sesionPrevia = e.sesionActiva;
    refrescarOpciones();
    sincronizarControles();
    recargar();
  });

  // --- arranque ---
  sesionPrevia = estado.sesionActiva;
  refrescarOpciones();
  sincronizarControles();
  recargar();

  return () => {
    activo = false;
    document.removeEventListener("keydown", alTeclear);
    desuscribir();
    panel?.destruir();
    panelRef?.destruir();
  };
}
