// Vista 6 — Replay local sobre el stint grabado.
//
// El servidor no reproduce: entrega las muestras una vez y el navegador avanza
// un cursor. Se muestra una ventana deslizante de N segundos y la degradación
// estimada (Ridge/Kalman) de la vuelta en curso.

import { api } from "../api.js";
import { estado, suscribir } from "../estado.js";
import { Panel, color, linea } from "../componentes/graficas.js";
import { pintarKpis, kpi } from "../componentes/tabla_kpis.js";
import { num } from "../formato.js";

const VELOCIDADES = [1, 2, 5];
const CANALES_FIJOS = ["wheel_slip", "temp_core_c", "wheel_load_n"];

const PLANTILLA = `
  <div class="aviso" id="v6-aviso">
    <strong>Sin sesión activa.</strong><br />Carga un CSV para reproducirlo.
  </div>
  <div id="v6-contenido" class="oculto">
    <div class="barra-controles">
      <button class="btn" id="v6-play">▶ Reproducir</button>
      <div class="velocidades" id="v6-velocidades"></div>
      <div class="grupo"><label>Ventana</label>
        <input type="range" id="v6-ventana" min="5" max="30" step="1" value="15" style="width:160px" />
        <span class="pill" id="v6-ventana-valor">15 s</span>
      </div>
      <div class="separador"></div>
      <span class="pill accent" id="v6-tiempo">0.0 s</span>
      <span class="pill" id="v6-sesion"></span>
    </div>
    <input type="range" class="replay-scrub" id="v6-scrub" min="0" max="100" step="0.05" value="0" />
    <div class="kpis" id="v6-kpis"></div>
    <section class="panel">
      <h3>Ventana deslizante <span class="texto-dim mono">señal limpia</span></h3>
      <div class="grafica" id="v6-grafica"></div>
    </section>
  </div>
`;

export function montar(contenedor) {
  contenedor.innerHTML = PLANTILLA;
  const q = (sel) => contenedor.querySelector(sel);
  const ui = {
    aviso: q("#v6-aviso"),
    contenido: q("#v6-contenido"),
    play: q("#v6-play"),
    velocidades: q("#v6-velocidades"),
    ventana: q("#v6-ventana"),
    ventanaValor: q("#v6-ventana-valor"),
    tiempo: q("#v6-tiempo"),
    sesion: q("#v6-sesion"),
    scrub: q("#v6-scrub"),
    kpis: q("#v6-kpis"),
    grafica: q("#v6-grafica"),
  };

  let panel = null;
  let buffer = null; // { t, lap, series, canales }
  let predicciones = null; // Map lap -> { verdad, ridge, kalman }
  let duracion = 0;
  let cursor = 0;
  let ventana = Number(ui.ventana.value);
  let velocidad = 1;
  let reproduciendo = false;
  let temporizador = null;
  let ultimoTs = 0;
  let sesionPrevia;
  let activo = true;

  ui.velocidades.innerHTML = VELOCIDADES.map(
    (v) => `<button class="pastilla${v === 1 ? " activa" : ""}" data-vel="${v}">${v}×</button>`,
  ).join("");

  // --- utilidades ------------------------------------------------------
  function indiceEn(t, valor) {
    let lo = 0;
    let hi = t.length - 1;
    while (lo < hi) {
      const medio = (lo + hi) >> 1;
      if (t[medio] < valor) lo = medio + 1;
      else hi = medio;
    }
    return lo;
  }

  function degradacionDeLap(lap) {
    if (!predicciones) return null;
    return predicciones.get(lap) ?? null;
  }

  // --- dibujo ----------------------------------------------------------
  function dibujar() {
    if (!buffer) return;
    const { t, lap, series, canales } = buffer;
    const iFin = indiceEn(t, cursor);
    const iIni = indiceEn(t, cursor - ventana);
    const x = t.slice(iIni, iFin + 1);

    const datos = [x];
    for (const c of canales) datos.push(series[c].slice(iIni, iFin + 1));

    if (!panel) {
      const paleta = ["--slip", "--temp", "--carga", "--speed"];
      panel = new Panel(ui.grafica, {
        series: canales.map((c, i) => linea({ etiqueta: c, color: color(paleta[i % paleta.length]), ancho: 1.5 })),
        altura: 300,
        sync: "replay",
        ejeX: { label: "s" },
      });
    }
    panel.datos(datos);

    const lapActual = lap[Math.min(iFin, lap.length - 1)] ?? null;
    const deg = lapActual == null ? null : degradacionDeLap(lapActual);
    ui.tiempo.textContent = `${num(cursor, 1)} s`;
    ui.scrub.value = String(cursor);
    pintarKpis(ui.kpis, [
      kpi("Tiempo", `${num(cursor, 1)} s`, { pie: `de ${num(duracion, 1)} s` }),
      kpi("Vuelta", lapActual == null ? "—" : String(lapActual), { tono: "accent" }),
      kpi("Muestras en ventana", String(x.length), { pie: `${ventana} s` }),
      kpi("Degradación est.", deg ? num(deg.verdad, 4) : "—", { pie: deg ? "verdad/proxy" : "sin datos" }),
      kpi("Ridge", deg ? num(deg.ridge, 4) : "—", { tono: "ok" }),
      kpi("Kalman", deg ? num(deg.kalman, 4) : "—", {}),
    ]);
  }

  // --- reproducción ----------------------------------------------------
  // Temporizador con reloj real (no rAF): sigue avanzando aunque la pestaña
  // esté oculta o el compositor no pinte.
  function paso() {
    if (!reproduciendo) return;
    const ahora = performance.now();
    const dt = Math.min(0.25, (ahora - ultimoTs) / 1000);
    ultimoTs = ahora;
    cursor = Math.min(duracion, cursor + dt * velocidad);
    dibujar();
    if (cursor >= duracion) pausar();
  }

  function reproducir() {
    if (!buffer) return;
    if (cursor >= duracion) cursor = 0;
    reproduciendo = true;
    ultimoTs = performance.now();
    ui.play.textContent = "❚❚ Pausa";
    temporizador = setInterval(paso, 33);
  }

  function pausar() {
    reproduciendo = false;
    if (temporizador) clearInterval(temporizador);
    temporizador = null;
    ui.play.textContent = "▶ Reproducir";
  }

  // --- carga -----------------------------------------------------------
  function construirPredicciones(ridge, kalman) {
    const mapa = new Map();
    const verdad = new Map(ridge.verdad_laps.map((l, i) => [l, ridge.verdad[i]]));
    const proxi = new Map(ridge.proxy_laps.map((l, i) => [l, ridge.proxy[i]]));
    const ridgeLap = new Map(ridge.laps_all.map((l, i) => [l, ridge.pred_all[i]]));
    const kalmanLap = new Map(kalman.laps_test.map((l, i) => [l, kalman.pred[i]]));
    for (const l of ridge.laps_all) {
      mapa.set(l, {
        verdad: verdad.get(l) ?? proxi.get(l) ?? null,
        ridge: ridgeLap.get(l) ?? null,
        kalman: kalmanLap.get(l) ?? null,
      });
    }
    return mapa;
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
    pausar();
    panel?.destruir();
    panel = null;
    buffer = null;

    const rueda = estado.rueda ?? "fl";
    const canales = [...CANALES_FIJOS.map((c) => `${c}_${rueda}`), "speed_kmh"];
    try {
      // `lap` va último: el downsampling min/max usa el primer canal (señal real).
      const [trama, ridge, kalman] = await Promise.all([
        api.stint({ canales: [...canales, "lap"], crudo: false, maxPuntos: 20000 }),
        api.ridge({}),
        api.kalman({}),
      ]);
      if (!activo) return;
      buffer = { t: trama.t, lap: trama.series.lap, series: trama.series, canales };
      predicciones = construirPredicciones(ridge, kalman);
      duracion = trama.t[trama.t.length - 1] ?? 0;
      cursor = Math.min(ventana, duracion);
      ui.scrub.max = String(duracion);
      dibujar();
    } catch (error) {
      if (!activo) return;
      pintarKpis(ui.kpis, [kpi("Error", "—", { pie: error.message, tono: "bad" })]);
    }
  }

  // --- eventos ---------------------------------------------------------
  ui.play.addEventListener("click", () => (reproduciendo ? pausar() : reproducir()));
  ui.ventana.addEventListener("input", () => {
    ventana = Number(ui.ventana.value);
    ui.ventanaValor.textContent = `${ventana} s`;
    dibujar();
  });
  ui.scrub.addEventListener("input", () => {
    cursor = Number(ui.scrub.value);
    dibujar();
  });
  ui.velocidades.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-vel]");
    if (!b) return;
    velocidad = Number(b.dataset.vel);
    for (const x of ui.velocidades.children) x.classList.toggle("activa", x === b);
  });

  const desuscribir = suscribir((e) => {
    if (e.sesionActiva === sesionPrevia) return;
    sesionPrevia = e.sesionActiva;
    recargar();
  });

  sesionPrevia = estado.sesionActiva;
  recargar();

  return () => {
    activo = false;
    pausar();
    desuscribir();
    panel?.destruir();
  };
}
