// Vista 2 — Espectro de Welch (crudo vs. limpio), energía por banda y planta
// 2×2 del coche con los valores medios de la vuelta seleccionada.

import { api } from "../api.js";
import { estado, suscribir } from "../estado.js";
import { Panel, color, linea } from "../componentes/graficas.js";
import { pintarKpis, kpi } from "../componentes/tabla_kpis.js";
import { num } from "../formato.js";

const RUEDAS = [
  { id: "fl", nombre: "Del. izq." },
  { id: "fr", nombre: "Del. der." },
  { id: "rl", nombre: "Tras. izq." },
  { id: "rr", nombre: "Tras. der." },
];

// Canales agregados por rueda para la planta (orden: temp, presión, carga, slip).
const CANALES_RUEDA = ["temp_core_c", "pressure_psi", "wheel_load_n", "wheel_slip"];

const NPERSEG = [64, 128, 256, 512];

const PLANTILLA = `
  <div class="aviso" id="v2-aviso">
    <strong>Sin sesión activa.</strong><br />Carga un CSV para ver el espectro.
  </div>
  <div id="v2-contenido" class="oculto">
    <div class="barra-controles">
      <div class="grupo"><label>Canal</label><select class="input" id="v2-canal"></select></div>
      <div class="grupo"><label>Rueda</label><select class="input" id="v2-rueda"></select></div>
      <div class="grupo"><label>Vuelta</label><select class="input" id="v2-lap"></select></div>
      <div class="grupo"><label>nperseg</label><select class="input" id="v2-nperseg"></select></div>
      <div class="grupo"><label>Eje X</label><select class="input" id="v2-escala">
        <option value="lineal">lineal</option>
        <option value="log">log</option>
      </select></div>
      <div class="separador"></div>
      <span class="pill" id="v2-sesion"></span>
    </div>
    <div class="kpis" id="v2-kpis"></div>
    <section class="panel">
      <h3>Densidad espectral de potencia <span class="texto-dim mono">crudo vs. limpio · dB/Hz</span></h3>
      <div class="grafica" id="v2-grafica"></div>
    </section>
    <section class="panel">
      <h3>Planta 2×2 <span class="texto-dim mono">media de la vuelta · temperatura = color</span></h3>
      <div class="planta" id="v2-planta"></div>
    </section>
  </div>
`;

const CANALES_MAGNITUD = ["temp_core_c", "pressure_psi", "wheel_load_n", "wheel_slip"];

export function montar(contenedor) {
  contenedor.innerHTML = PLANTILLA;
  const q = (sel) => contenedor.querySelector(sel);
  const ui = {
    aviso: q("#v2-aviso"),
    contenido: q("#v2-contenido"),
    canal: q("#v2-canal"),
    rueda: q("#v2-rueda"),
    lap: q("#v2-lap"),
    nperseg: q("#v2-nperseg"),
    escala: q("#v2-escala"),
    sesion: q("#v2-sesion"),
    kpis: q("#v2-kpis"),
    grafica: q("#v2-grafica"),
    planta: q("#v2-planta"),
  };

  let panel = null;
  let sesionPrevia;
  let activo = true;

  ui.rueda.innerHTML = RUEDAS.map((r) => `<option value="${r.id}">${r.nombre}</option>`).join("");
  ui.nperseg.innerHTML = NPERSEG.map((n) => `<option value="${n}">${n}</option>`).join("");
  ui.nperseg.value = "128";

  function canalActual() {
    return `${ui.canal.value}_${ui.rueda.value}`;
  }

  function lapActual() {
    return ui.lap.value === "" ? null : Number(ui.lap.value);
  }

  // Vuelta por defecto: la de más muestras (evita vueltas parciales de 1 muestra).
  function lapPorDefecto() {
    const vueltas = estado.vueltas ?? [];
    if (vueltas.length) {
      const mejor = vueltas.reduce((a, b) => (b.n_muestras > a.n_muestras ? b : a));
      return String(mejor.lap);
    }
    const laps = estado.laps ?? [];
    return laps.length ? String(laps[laps.length - 1]) : "";
  }

  // --- espectro --------------------------------------------------------
  function energiaBanda(freqs, db, banda) {
    const [a, b] = banda;
    let suma = 0;
    for (let i = 0; i < freqs.length; i += 1) {
      if (freqs[i] >= a && freqs[i] <= b) suma += 10 ** (db[i] / 10);
    }
    return suma;
  }

  function kpisBandas(datos) {
    const { freqs, psd_limpio_db, psd_crudo_db, bandas, delta_f, corte_hz, nperseg } = datos;
    const nombres = { baja: "baja", media: "media", alta: "alta" };
    const tarjetas = [];
    for (const [clave, banda] of Object.entries(bandas ?? {})) {
      const eLimpio = energiaBanda(freqs, psd_limpio_db, banda) * delta_f;
      const eCrudo = psd_crudo_db ? energiaBanda(freqs, psd_crudo_db, banda) * delta_f : null;
      const ate = eCrudo && eLimpio > 0 ? 10 * Math.log10(eCrudo / eLimpio) : null;
      tarjetas.push(
        kpi(
          `Banda ${nombres[clave] ?? clave}`,
          ate == null ? "—" : `${num(ate, 2)} dB`,
          {
            pie: `${banda[0]}–${banda[1]} Hz · limpio ${eLimpio.toExponential(1)}`,
            tono: ate != null && ate > 3 ? "ok" : undefined,
          },
        ),
      );
    }
    tarjetas.push(kpi("Resolución", `${num(delta_f, 3)} Hz`, { pie: `nperseg ${nperseg}` }));
    tarjetas.push(kpi("Corte", `${num(corte_hz, 1)} Hz`, { pie: "Butterworth orden 4" }));
    pintarKpis(ui.kpis, tarjetas);
  }

  function dibujarEspectro(datos) {
    const { bandas, corte_hz } = datos;
    const log = ui.escala.value === "log";
    // En escala logarítmica no se puede representar f = 0: se recorta el primer bin.
    let { freqs, psd_limpio_db, psd_crudo_db } = datos;
    if (log) {
      const i0 = Math.max(0, freqs.findIndex((f) => f > 0));
      freqs = freqs.slice(i0);
      psd_limpio_db = psd_limpio_db.slice(i0);
      psd_crudo_db = psd_crudo_db ? psd_crudo_db.slice(i0) : null;
    }
    const series = [
      linea({ etiqueta: "crudo", color: color("--warn"), ancho: 1, dash: [4, 3] }),
      linea({ etiqueta: "limpio", color: color("--accent"), ancho: 1.8 }),
    ];
    if (panel) panel.destruir();
    panel = new Panel(ui.grafica, {
      series,
      altura: 300,
      sync: "espectro",
      ejeX: { label: log ? "Hz (log)" : "Hz" },
      ejeY: { label: "dB/Hz" },
      escalaX: log ? { distr: 3, log: 10 } : undefined,
    });
    panel.datos([freqs, psd_crudo_db ?? freqs.map(() => null), psd_limpio_db]);
    panel.anotaciones({
      franjas: Object.values(bandas ?? {}).map(([a, b]) => ({ a, b, color: "rgba(34, 211, 238, 0.05)" })),
      lineas: [{ x: corte_hz, color: color("--bad") }],
    });
    kpisBandas(datos);
  }

  async function cargarEspectro() {
    try {
      const datos = await api.espectro({ canal: canalActual(), lap: lapActual(), nperseg: Number(ui.nperseg.value) });
      if (!activo) return;
      dibujarEspectro(datos);
    } catch (error) {
      if (!activo) return;
      panel?.destruir();
      panel = null;
      ui.grafica.innerHTML = `<div class="nota">No se pudo estimar la PSD: ${error.message}</div>`;
      pintarKpis(ui.kpis, [kpi("Error", "—", { pie: error.message, tono: "bad" })]);
    }
  }

  // --- planta 2×2 ------------------------------------------------------
  function colorTemperatura(t, tMin, tMax) {
    const rango = tMax - tMin || 1;
    const u = Math.max(0, Math.min(1, (t - tMin) / rango));
    // azul (frío) → ámbar (caliente)
    const paradas = [
      [56, 189, 248],
      [16, 185, 129],
      [251, 191, 36],
      [244, 63, 94],
    ];
    const pos = u * (paradas.length - 1);
    const i = Math.min(paradas.length - 2, Math.floor(pos));
    const f = pos - i;
    const mezcla = paradas[i].map((c, k) => Math.round(c + (paradas[i + 1][k] - c) * f));
    return `rgba(${mezcla.join(",")}, 0.22)`;
  }

  async function cargarPlanta() {
    const lap = lapActual() ?? Number(lapPorDefecto());
    if (!Number.isFinite(lap)) {
      ui.planta.innerHTML = "";
      return;
    }
    const canales = [];
    for (const w of RUEDAS) for (const c of CANALES_RUEDA) canales.push(`${c}_${w.id}`);
    canales.push("speed_kmh");
    const datos = await api.vuelta(lap, { canales, crudo: false, maxPuntos: 20000 });
    if (!activo) return;

    const media = (arr) => (arr && arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
    const dt = 1 / (datos.fs ?? 100);
    const vMs = (datos.series.speed_kmh ?? []).map((v) => (v ?? 0) / 3.6);
    // Trabajo de fricción acumulado: ∫ |slip|·F_z·v · dt  (kJ).
    const friccion = (slip, carga) => {
      let s = 0;
      for (let i = 0; i < slip.length; i += 1) {
        s += Math.abs(slip[i] ?? 0) * (carga[i] ?? 0) * (vMs[i] ?? 0);
      }
      return (s * dt) / 1000;
    };
    const resumen = RUEDAS.map((w) => {
      const leer = (c) => datos.series[`${c}_${w.id}`];
      return {
        ...w,
        temp: media(leer("temp_core_c")),
        presion: media(leer("pressure_psi")),
        carga: media(leer("wheel_load_n")),
        slip: media(leer("wheel_slip")),
        friccion: friccion(leer("wheel_slip") ?? [], leer("wheel_load_n") ?? []),
      };
    });
    const temps = resumen.map((r) => r.temp).filter((v) => v != null);
    const tMin = Math.min(...temps);
    const tMax = Math.max(...temps);

    ui.planta.innerHTML = resumen
      .map(
        (r) => `
      <div class="rueda" style="background:${colorTemperatura(r.temp, tMin, tMax)}">
        <div class="nombre">${r.id.toUpperCase()} · ${r.nombre}</div>
        <div class="temp">${num(r.temp, 1)}<span class="unidad">°C</span></div>
        <div class="detalle">
          <span>Presión <span class="mono">${num(r.presion, 1)} psi</span></span>
          <span>Carga <span class="mono">${num(r.carga, 0)} N</span></span>
          <span>Slip <span class="mono">${num(r.slip, 3)}</span></span>
          <span>Fricción <span class="mono">${num(r.friccion, 2)} kJ</span></span>
        </div>
      </div>`,
      )
      .join("");
  }

  // --- ciclo de vida ---------------------------------------------------
  function refrescar() {
    cargarEspectro();
    cargarPlanta();
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

    const fisicas = estado.fisicas.filter((c) => /_(fl|fr|rl|rr)$/.test(c));
    const magnitudes = CANALES_MAGNITUD.filter((m) => fisicas.some((c) => c.startsWith(`${m}_`)));
    const previo = ui.canal.value;
    ui.canal.innerHTML = magnitudes.map((m) => `<option value="${m}">${m}</option>`).join("");
    ui.canal.value = magnitudes.includes(previo) ? previo : magnitudes[0] ?? "";

    const laps = estado.laps ?? [];
    const lapPrevio = ui.lap.value;
    ui.lap.innerHTML =
      `<option value="">stint completo</option>` +
      laps.map((l) => `<option value="${l}">vuelta ${l}</option>`).join("");
    ui.lap.value = laps.some((l) => String(l) === lapPrevio) ? lapPrevio : lapPorDefecto();

    refrescar();
  }

  ui.canal.addEventListener("change", refrescar);
  ui.rueda.addEventListener("change", refrescar);
  ui.lap.addEventListener("change", refrescar);
  ui.nperseg.addEventListener("change", cargarEspectro);
  ui.escala.addEventListener("change", cargarEspectro);

  const desuscribir = suscribir((e) => {
    if (e.sesionActiva === sesionPrevia) return;
    sesionPrevia = e.sesionActiva;
    recargar();
  });

  sesionPrevia = estado.sesionActiva;
  recargar();

  return () => {
    activo = false;
    desuscribir();
    panel?.destruir();
  };
}
