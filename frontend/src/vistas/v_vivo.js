// Vista 7 — En vivo (Etapa 3).
//
// La captura ocurre en el servidor (memoria compartida de AC o "modo seco"
// reproduciendo un CSV). Este vista se conecta al WebSocket `/api/vivo/stream`,
// que empuja ~10 tramas/s con el estado del motor en vivo y la ventana reciente:
//   - osciloscopio del canal/rueda elegidos,
//   - espectro en vivo (PSD de la ventana),
//   - planta 2×2 con el semáforo de degradación por rueda,
//   - predicción de degradación (Kalman) de las próximas vueltas.

import { api, CanalVivo } from "../api.js";
import { Panel, color, linea } from "../componentes/graficas.js";
import { pintarKpis, kpi } from "../componentes/tabla_kpis.js";
import { num, entero, pct } from "../formato.js";

const RUEDAS = [
  { id: "fl", nombre: "Del. izq." },
  { id: "fr", nombre: "Del. der." },
  { id: "rl", nombre: "Tras. izq." },
  { id: "rr", nombre: "Tras. der." },
];

const MAGNITUDES = [
  { id: "wheel_slip", nombre: "Slip", unidad: "" },
  { id: "temp_core_c", nombre: "Temperatura", unidad: "°C" },
  { id: "wheel_load_n", nombre: "Carga", unidad: "N" },
  { id: "pressure_psi", nombre: "Presión", unidad: "psi" },
  { id: "speed_kmh", nombre: "Velocidad", unidad: "km/h", sinRueda: true },
];

const N_VENTANA = 600; // 6 s a 100 Hz

const PLANTILLA = `
  <div class="barra-controles">
    <div class="grupo"><label>Fuente</label><select class="input" id="v7-fuente">
      <option value="ac">En vivo (AC)</option>
      <option value="seco">Modo seco (CSV)</option>
    </select></div>
    <div class="grupo" id="v7-grupo-archivo" hidden><label>CSV</label>
      <select class="input" id="v7-archivo"></select></div>
    <div class="grupo" id="v7-grupo-ritmo"><label>Ritmo</label><select class="input" id="v7-ritmo">
      <option value="rt">tiempo real</option>
      <option value="max">máxima velocidad</option>
    </select></div>
    <button class="btn" id="v7-iniciar">▶ Iniciar</button>
    <button class="btn ghost" id="v7-detener" disabled>■ Detener</button>
    <div class="separador"></div>
    <span class="pill" id="v7-ws"><span class="punto"></span>desconectado</span>
    <span class="pill" id="v7-captura">inactivo</span>
  </div>

  <div class="aviso" id="v7-aviso" hidden></div>

  <div class="kpis" id="v7-kpis"></div>

  <div class="barra-controles">
    <div class="grupo"><label>Canal</label><select class="input" id="v7-canal"></select></div>
    <div class="grupo"><label>Rueda</label><select class="input" id="v7-rueda"></select></div>
    <div class="separador"></div>
    <span class="nota" id="v7-csv"></span>
  </div>

  <div class="rejilla">
    <section class="panel">
      <h3>Osciloscopio <span class="texto-dim mono">ventana deslizante · 6 s</span></h3>
      <div class="grafica" id="v7-osciloscopio"></div>
    </section>
    <section class="panel">
      <h3>Acelerador / Freno <span class="texto-dim mono">pedales · %</span></h3>
      <div class="grafica" id="v7-pedales"></div>
    </section>
  </div>

  <div class="rejilla lab">
    <section class="panel">
      <h3>Espectro en vivo <span class="texto-dim mono">PSD de la ventana</span></h3>
      <div class="grafica" id="v7-espectro"></div>
    </section>
    <section class="panel">
      <h3>Degradación por rueda <span class="texto-dim mono">grip auto-calibrado</span></h3>
      <div class="planta" id="v7-planta"></div>
      <div class="nota" id="v7-planta-nota"></div>
    </section>
  </div>

  <section class="panel">
    <h3>Predicción de degradación <span class="texto-dim mono">Kalman · próximas vueltas</span></h3>
    <div id="v7-prediccion"></div>
  </section>
`;

export function montar(contenedor) {
  contenedor.innerHTML = PLANTILLA;
  const q = (sel) => contenedor.querySelector(sel);
  const ui = {
    fuente: q("#v7-fuente"),
    grupoArchivo: q("#v7-grupo-archivo"),
    archivo: q("#v7-archivo"),
    grupoRitmo: q("#v7-grupo-ritmo"),
    ritmo: q("#v7-ritmo"),
    iniciar: q("#v7-iniciar"),
    detener: q("#v7-detener"),
    ws: q("#v7-ws"),
    captura: q("#v7-captura"),
    aviso: q("#v7-aviso"),
    kpis: q("#v7-kpis"),
    canal: q("#v7-canal"),
    rueda: q("#v7-rueda"),
    csv: q("#v7-csv"),
    osc: q("#v7-osciloscopio"),
    pedales: q("#v7-pedales"),
    espectro: q("#v7-espectro"),
    planta: q("#v7-planta"),
    plantaNota: q("#v7-planta-nota"),
    prediccion: q("#v7-prediccion"),
  };

  let activo = true;
  let panelOsc = null;
  let panelPed = null;
  let panelEsp = null;
  let canalWs = null;
  let ultimo = null;

  ui.canal.innerHTML = MAGNITUDES.map((m) => `<option value="${m.id}">${m.nombre}</option>`).join("");
  ui.rueda.innerHTML = RUEDAS.map((r) => `<option value="${r.id}">${r.nombre}</option>`).join("");

  // --- canal/rueda seleccionados (nombre de columna del esquema) ---
  function magnitud() {
    return MAGNITUDES.find((m) => m.id === ui.canal.value) ?? MAGNITUDES[0];
  }
  function canalActual() {
    const m = magnitud();
    return m.sinRueda ? m.id : `${m.id}_${ui.rueda.value}`;
  }
  function magnitudActual() {
    return magnitud();
  }

  function ajustarControlesFuente() {
    const seco = ui.fuente.value === "seco";
    ui.grupoArchivo.hidden = !seco;
    ui.grupoRitmo.hidden = !seco;
    ui.rueda.disabled = magnitud().sinRueda;
  }

  // --- paneles ---
  function crearPaneles() {
    if (!panelOsc) {
      panelOsc = new Panel(ui.osc, {
        series: [linea({ etiqueta: magnitud().nombre, color: color("--accent"), ancho: 1.6, puentes: true })],
        altura: 260,
        sync: "vivo",
        ejeX: { label: "s" },
        ejeY: { label: magnitud().unidad || "—" },
      });
    }
    if (!panelPed) {
      panelPed = new Panel(ui.pedales, {
        series: [
          linea({ etiqueta: "Acelerador", color: color("--ok"), ancho: 1.6, puentes: true }),
          linea({ etiqueta: "Freno", color: color("--bad"), ancho: 1.6, puentes: true }),
        ],
        altura: 260,
        sync: "vivo",
        ejeX: { label: "s" },
        ejeY: { label: "%" },
      });
    }
    if (!panelEsp) {
      panelEsp = new Panel(ui.espectro, {
        series: [linea({ etiqueta: "PSD", color: color("--warn"), ancho: 1.6 })],
        altura: 240,
        sync: "vivo-espectro",
        ejeX: { label: "Hz" },
        ejeY: { label: "dB/Hz" },
      });
    }
  }

  // --- render de una trama del WebSocket ---
  function render(msg) {
    ultimo = msg;
    crearPaneles();
    const m = magnitudActual();
    const canal = canalActual();

    const deg = msg.degradacion ?? {};
    const vals = Object.values(deg).filter((v) => v != null);
    const media = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;

    pintarKpis(ui.kpis, [
      kpi("Muestras", entero(msg.n ?? 0), { pie: `${msg.fuente ?? "—"} · ${num(msg.segundos, 1)} s` }),
      kpi("Vuelta", msg.lap ?? "—", { pie: msg.packetId != null ? `packetId ${msg.packetId}` : "—" }),
      kpi(
        "Degradación media",
        media == null ? "—" : pct(media),
        { tono: media == null ? undefined : media > 0.6 ? "bad" : media > 0.3 ? "warn" : "ok", pie: msg.degradacion_modo },
      ),
      kpi("Grip FL", msg.grip?.fl == null ? "—" : num(msg.grip.fl, 4), { pie: "tyreWear" }),
    ]);

    // osciloscopio
    const vent = msg.ventana ?? { t: [], series: {} };
    const serie = vent.series?.[canal] ?? [];
    panelOsc.datos([vent.t ?? [], serie]);
    panelOsc.el.parentElement.querySelector("h3").innerHTML =
      `Osciloscopio <span class="texto-dim mono">${m.nombre}${m.sinRueda ? "" : ` · ${ui.rueda.value.toUpperCase()}`}</span>`;

    // pedales: AC entrega acelerador/freno en 0..1 -> los pasamos a %.
    const aPct = (arr) => (arr ?? []).map((v) => (v == null ? null : v * 100));
    panelPed.datos([vent.t ?? [], aPct(vent.series?.throttle), aPct(vent.series?.brake)]);

    // espectro
    const esp = msg.espectro;
    if (esp) {
      panelEsp.datos([esp.freqs, esp.psd_db]);
      panelEsp.el.parentElement.querySelector("h3").innerHTML =
        `Espectro en vivo <span class="texto-dim mono">${esp.canal}</span>`;
    }

    // planta
    ui.planta.innerHTML = RUEDAS.map((r) => {
      const d = deg[r.id];
      const g = msg.grip?.[r.id];
      return `
        <div class="rueda" style="background:${colorDegradacion(d)}">
          <div class="nombre">${r.id.toUpperCase()} · ${r.nombre}</div>
          <div class="temp">${d == null ? "—" : pct(d, 1)}</div>
          <div class="detalle">
            <span>Grip <span class="mono">${g == null ? "—" : num(g, 4)}</span></span>
          </div>
        </div>`;
    }).join("");
    ui.plantaNota.textContent =
      msg.degradacion_modo === "verdad"
        ? "Degradación desde el grip de AC (pico auto-calibrado) o columna inyectada."
        : "Sin señal de grip: abre AC en pista o usa el modo seco con un CSV que traiga verdad.";

    dibujarPrediccion(msg.prediccion);

    ui.csv.textContent = msg.ruta_csv ? `registrando en ${msg.ruta_csv}` : "";
    if (msg.error) {
      ui.aviso.hidden = false;
      ui.aviso.innerHTML = `<strong>Error de captura.</strong><br />${msg.error}`;
    } else {
      ui.aviso.hidden = true;
    }
    const on = !!msg.activo;
    ui.captura.textContent = on ? "capturando" : msg.n > 0 ? "detenido" : "inactivo";
    ui.captura.className = `pill ${on ? "ok" : ""}`;
    ui.iniciar.disabled = on;
    ui.detener.disabled = !on;
  }

  function dibujarPrediccion(pred) {
    if (!pred || (!pred.media?.length && !pred.obs?.length)) {
      ui.prediccion.innerHTML = `<div class="nota">Aún no hay vueltas suficientes para predecir (mínimo 3).</div>`;
      return;
    }
    const filas = [];
    (pred.laps_obs ?? []).forEach((l, i) => {
      filas.push(
        `<tr><td class="mono">vuelta ${l}</td><td class="mono">${num(pred.obs[i], 4)}</td><td class="mono texto-dim">observado</td></tr>`,
      );
    });
    (pred.laps_pred ?? []).forEach((l, i) => {
      const lo = pred.banda_inf?.[i];
      const hi = pred.banda_sup?.[i];
      filas.push(
        `<tr><td class="mono">vuelta ${l}</td><td class="mono">${num(pred.media[i], 4)}</td>` +
          `<td class="mono texto-dim">${lo == null ? "—" : `${num(lo, 3)} … ${num(hi, 3)}`}</td></tr>`,
      );
    });
    ui.prediccion.innerHTML = `
      <table class="tabla">
        <thead><tr><th>Vuelta</th><th>Degradación</th><th>Intervalo</th></tr></thead>
        <tbody>${filas.join("")}</tbody>
      </table>`;
  }

  function colorDegradacion(d) {
    if (d == null) return "transparent";
    const u = Math.max(0, Math.min(1, d));
    // verde (sano) → ámbar → rojo (gastado)
    const paradas = [
      [52, 211, 153],
      [251, 191, 36],
      [244, 63, 94],
    ];
    const pos = u * (paradas.length - 1);
    const i = Math.min(paradas.length - 2, Math.floor(pos));
    const f = pos - i;
    const c = paradas[i].map((v, k) => Math.round(v + (paradas[i + 1][k] - v) * f));
    return `rgba(${c.join(",")}, 0.22)`;
  }

  // --- WebSocket ---
  function ajustes() {
    const canales = Array.from(new Set([canalActual(), "throttle", "brake"]));
    return { canales, n: N_VENTANA };
  }

  function conectarWS() {
    canalWs = new CanalVivo({
      onEstado: (estadoWs) => {
        ui.ws.className = `pill ${estadoWs === "conectado" ? "ok" : estadoWs === "conectando" ? "warn" : "bad"}`;
        ui.ws.innerHTML = `<span class="punto"></span>${estadoWs}`;
        if (estadoWs === "conectado") canalWs.enviar(ajustes());
      },
      onMensaje: (msg) => {
        if (msg.tipo === "vivo") render(msg);
      },
    });
  }

  // --- acciones ---
  async function refrescarArchivos() {
    try {
      const { sesiones } = await api.vivoSesiones();
      ui.archivo.innerHTML = sesiones
        .map((s) => `<option value="${s.nombre}">${s.nombre}${s.origen === "raw" ? " (raw)" : ""}</option>`)
        .join("");
      const preferido = sesiones.find((s) => s.nombre === "sim_test_99.csv");
      if (preferido) ui.archivo.value = preferido.nombre;
    } catch {
      /* sin lista: se puede escribir el nombre a mano si hiciera falta */
    }
  }

  async function iniciar() {
    ui.aviso.hidden = true;
    const fuente = ui.fuente.value;
    const cuerpo = { fuente };
    if (fuente === "seco") {
      cuerpo.archivo = ui.archivo.value;
      cuerpo.ritmoHz = ui.ritmo.value === "max" ? 0 : null;
    }
    ui.iniciar.disabled = true;
    try {
      await api.vivoIniciar(cuerpo);
      canalWs?.enviar(ajustes());
    } catch (error) {
      ui.aviso.hidden = false;
      ui.aviso.innerHTML = `<strong>No se pudo iniciar.</strong><br />${error.message}`;
      ui.iniciar.disabled = false;
    }
  }

  async function detener() {
    try {
      await api.vivoDetener();
    } catch {
      /* ignora */
    }
  }

  // --- eventos ---
  ui.fuente.addEventListener("change", ajustarControlesFuente);
  ui.canal.addEventListener("change", () => {
    ui.rueda.disabled = magnitud().sinRueda;
    panelOsc?.destruir();
    panelOsc = null;
    canalWs?.enviar(ajustes());
  });
  ui.rueda.addEventListener("change", () => canalWs?.enviar(ajustes()));
  ui.iniciar.addEventListener("click", iniciar);
  ui.detener.addEventListener("click", detener);

  ajustarControlesFuente();
  refrescarArchivos();
  conectarWS();
  api.vivoEstado().then((e) => {
    if (activo && e && e.n > 0) render(e);
  });

  return () => {
    activo = false;
    canalWs?.cerrar();
    panelOsc?.destruir();
    panelPed?.destruir();
    panelEsp?.destruir();
  };
}
