// Vista 5 — Robustez: MAE de Ridge frente a ruido inyectado (SNR) e importancia
// de features con verificación de signo físico (plan §3.5).

import { api } from "../api.js";
import { estado, suscribir } from "../estado.js";
import { Panel, color, linea } from "../componentes/graficas.js";
import { pintarKpis, kpi } from "../componentes/tabla_kpis.js";
import { num } from "../formato.js";

// Curva de SNR (dB). Se pide explícita para tener más resolución que el defecto.
const SNR = [];
for (let s = 40; s >= 0; s -= 2.5) SNR.push(s);

// Signo físico esperado del coeficiente (features estandarizadas).
// +1: al crecer la feature sube la degradación; null: sin hipótesis fuerte.
const FAMILIAS = [
  { prefijo: "grados_segundo", nombre: "grados·segundo", signo: 1 },
  { prefijo: "trabajo_friccion", nombre: "trabajo de fricción", signo: 1 },
  { prefijo: "temp", nombre: "temperatura", signo: 1 },
  { prefijo: "carga", nombre: "carga", signo: 1 },
  { prefijo: "slip", nombre: "deslizamiento", signo: 1 },
  { prefijo: "psd", nombre: "energía espectral", signo: 1 },
  { prefijo: "speed", nombre: "velocidad", signo: null },
  { prefijo: "throttle", nombre: "acelerador", signo: null },
  { prefijo: "brake", nombre: "freno", signo: null },
  { prefijo: "steering", nombre: "dirección", signo: null },
];

function familiaDe(feature) {
  return FAMILIAS.find((f) => feature.startsWith(f.prefijo)) ?? { nombre: "otros", signo: null };
}

const PLANTILLA = `
  <div class="aviso" id="v5-aviso">
    <strong>Sin sesión activa.</strong><br />Carga un CSV para evaluar la robustez.
  </div>
  <div id="v5-contenido" class="oculto">
    <div class="barra-controles">
      <div class="grupo"><label>SNR</label>
        <input type="range" id="v5-snr" min="0" max="40" step="1" value="20" style="width:220px" />
        <span class="pill accent" id="v5-snr-valor">20 dB</span>
      </div>
      <div class="separador"></div>
      <span class="pill" id="v5-sesion"></span>
    </div>
    <div class="kpis" id="v5-kpis"></div>
    <section class="panel">
      <h3>MAE frente al ruido <span class="texto-dim mono">SNR creciente = menos ruido</span></h3>
      <div class="grafica" id="v5-grafica"></div>
    </section>
    <section class="panel">
      <h3>Importancia de features <span class="texto-dim mono">coeficientes estandarizados</span>
        <label class="switch" style="margin-left:auto">
          <input type="checkbox" id="v5-agrupar" /> agrupar por familia
        </label>
      </h3>
      <div class="importancias" id="v5-importancias"></div>
    </section>
  </div>
`;

export function montar(contenedor) {
  contenedor.innerHTML = PLANTILLA;
  const q = (sel) => contenedor.querySelector(sel);
  const ui = {
    aviso: q("#v5-aviso"),
    contenido: q("#v5-contenido"),
    snr: q("#v5-snr"),
    snrValor: q("#v5-snr-valor"),
    sesion: q("#v5-sesion"),
    kpis: q("#v5-kpis"),
    grafica: q("#v5-grafica"),
    importancias: q("#v5-importancias"),
    agrupar: q("#v5-agrupar"),
  };

  let panel = null;
  let curva = null; // { snr_db, mae }
  let importancias = [];
  let sesionPrevia;
  let activo = true;

  function interpolar(snr) {
    if (!curva) return null;
    const xs = curva.snr_db;
    const ys = curva.mae;
    if (snr <= xs[0]) return ys[0];
    if (snr >= xs[xs.length - 1]) return ys[ys.length - 1];
    for (let i = 1; i < xs.length; i += 1) {
      if (snr <= xs[i]) {
        const f = (snr - xs[i - 1]) / (xs[i] - xs[i - 1]);
        return ys[i - 1] + f * (ys[i] - ys[i - 1]);
      }
    }
    return null;
  }

  function dibujarCurva() {
    const snr = Number(ui.snr.value);
    const snrMax = curva.snr_db[curva.snr_db.length - 1];
    const maeSinRuido = curva.mae[curva.mae.length - 1];
    const maeSnr = interpolar(snr);

    if (panel) panel.destruir();
    panel = new Panel(ui.grafica, {
      series: [
        linea({ etiqueta: "MAE Ridge", color: color("--accent"), ancho: 1.8, puntos: true }),
      ],
      altura: 300,
      sync: "robustez",
      ejeX: { label: "SNR [dB]" },
      ejeY: { label: "MAE" },
    });
    panel.datos([curva.snr_db, curva.mae]);
    panel.anotaciones({ marcadores: maeSnr == null ? [] : [{ x: snr, y: maeSnr, color: color("--warn"), r: 5 }] });

    const relativa = maeSinRuido > 0 && maeSnr != null ? (maeSnr / maeSinRuido - 1) * 100 : null;
    pintarKpis(ui.kpis, [
      kpi("MAE @ SNR", maeSnr == null ? "—" : num(maeSnr, 4), { pie: `${snr} dB`, tono: "accent" }),
      kpi("MAE sin ruido", num(maeSinRuido, 4), { pie: `SNR ${snrMax} dB`, tono: "ok" }),
      kpi(
        "Degradación relativa",
        relativa == null ? "—" : `${relativa >= 0 ? "+" : ""}${num(relativa, 1)} %`,
        { pie: `respecto a SNR ${snrMax} dB`, tono: relativa != null && relativa > 25 ? "bad" : "warn" },
      ),
      kpi("Puntos", String(curva.snr_db.length), { pie: "barrido de SNR" }),
    ]);
  }

  function pintarImportancias() {
    const agrupar = ui.agrupar.checked;
    let items;
    if (agrupar) {
      const acumulado = new Map();
      for (const it of importancias) {
        const fam = familiaDe(it.feature);
        const prev = acumulado.get(fam.nombre) ?? { nombre: fam.nombre, signo: fam.signo, suma: 0, n: 0 };
        prev.suma += it.coeficiente;
        prev.n += 1;
        acumulado.set(fam.nombre, prev);
      }
      items = [...acumulado.values()].map((f) => ({ feature: f.nombre, coeficiente: f.suma / f.n, signo: f.signo }));
    } else {
      items = importancias.map((it) => ({ ...it, signo: familiaDe(it.feature).signo }));
    }
    items.sort((a, b) => Math.abs(b.coeficiente) - Math.abs(a.coeficiente));

    const max = Math.max(...items.map((it) => Math.abs(it.coeficiente)), 1e-9);
    ui.importancias.innerHTML = items
      .slice(0, 24)
      .map((it) => {
        const positivo = it.coeficiente >= 0;
        const ancho = (Math.abs(it.coeficiente) / max) * 50;
        const clase = it.signo == null ? "neutral" : Math.sign(it.coeficiente) === it.signo ? "ok" : "mal";
        const posicion = positivo ? `left:50%;width:${ancho}%` : `right:50%;width:${ancho}%`;
        return `
          <div class="barra-fila ${clase}">
            <span class="feature" title="${it.feature}">${it.feature}</span>
            <span class="barra-pista"><span class="barra" style="${posicion}"></span></span>
            <span class="coef">${it.coeficiente >= 0 ? "+" : ""}${num(it.coeficiente, 3)}</span>
          </div>`;
      })
      .join("");
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
      const [robustez, ridge] = await Promise.all([api.robustez({ snr_db: SNR }), api.ridge({})]);
      if (!activo) return;
      // Orden ascendente en SNR para poder interpolar y dibujar de izq. a der.
      const pares = robustez.snr_db
        .map((s, i) => [s, robustez.mae[i]])
        .sort((a, b) => a[0] - b[0]);
      curva = { snr_db: pares.map((p) => p[0]), mae: pares.map((p) => p[1]) };
      importancias = ridge.importancias ?? [];
      dibujarCurva();
      pintarImportancias();
    } catch (error) {
      if (!activo) return;
      pintarKpis(ui.kpis, [kpi("Error", "—", { pie: error.message, tono: "bad" })]);
    }
  }

  ui.snr.addEventListener("input", () => {
    ui.snrValor.textContent = `${ui.snr.value} dB`;
    if (curva) dibujarCurva();
  });
  ui.agrupar.addEventListener("change", pintarImportancias);

  const desuscribir = suscribir((e) => {
    if (e.sesionActiva === sesionPrevia) return;
    sesionPrevia = e.sesionActiva;
    curva = null;
    importancias = [];
    recargar();
  });

  sesionPrevia = estado.sesionActiva;
  ui.snrValor.textContent = `${ui.snr.value} dB`;
  recargar();

  return () => {
    activo = false;
    desuscribir();
    panel?.destruir();
  };
}
