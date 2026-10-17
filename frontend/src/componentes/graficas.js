// Envoltorio de uPlot: panel multi-serie con cursor sincronizado,
// marcadores de outliers y sombreado de huecos inválidos.

import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

// --- color de los tokens CSS (una sola fuente de verdad con variables.css) ---
const cacheColores = new Map();
export function color(nombre) {
  if (!cacheColores.has(nombre)) {
    const valor = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
    cacheColores.set(nombre, valor || "#8899aa");
  }
  return cacheColores.get(nombre);
}

const gruposSync = new Map();
function grupoSync(clave) {
  if (!gruposSync.has(clave)) gruposSync.set(clave, uPlot.sync(clave));
  return gruposSync.get(clave);
}

// Definición de una línea de datos.
export function linea({ etiqueta, color: trazo, ancho = 1.6, dash, puntos = false, formateador }) {
  return {
    label: etiqueta,
    stroke: trazo,
    width: ancho,
    dash,
    points: { show: puntos, size: 5, stroke: trazo, fill: trazo },
    ...(formateador ? { value: (_u, valor) => formateador(valor) } : {}),
  };
}

// Nube de puntos (sin trazo): para dispersiones.
export function nube({ etiqueta, color: trazo }) {
  return {
    label: etiqueta,
    stroke: trazo,
    width: 0,
    paths: () => null,
    points: { show: true, size: 6, stroke: trazo, fill: trazo },
  };
}

export class Panel {
  constructor(elemento, { series, altura = 240, sync = "telemetria", banda, ejeX, ejeY, escalaX, leyenda = true } = {}) {
    this.el = elemento;
    this.anot = { huecos: [], marcadores: [], lineas: [], franjas: [] };
    this.u = new uPlot(this._opciones({ series, altura, sync, banda, ejeX, ejeY, escalaX, leyenda }), this._vacio(series.length), elemento);
    this.ro = new ResizeObserver(() => this._redimensionar());
    this.ro.observe(elemento);
  }

  _opciones({ series, altura, sync, banda, ejeX, ejeY, escalaX, leyenda }) {
    grupoSync(sync);
    const eje = (extra) => ({
      stroke: color("--text-mute"),
      grid: { stroke: color("--border"), width: 1 },
      ticks: { stroke: color("--border-2"), width: 1 },
      font: '11px ui-monospace, monospace',
      ...extra,
    });
    const opciones = {
      width: this.el.clientWidth || 720,
      height: altura,
      padding: [10, 14, 0, 2],
      cursor: { sync: { key: sync }, drag: { x: true, y: false }, points: { size: 6 } },
      legend: leyenda ? { live: true } : { show: false },
      scales: { x: { time: false, ...escalaX }, y: { auto: true } },
      axes: [
        eje({ label: ejeX?.label, values: ejeX?.values, size: ejeX?.size ?? 34, ...ejeX?.extra }),
        eje({ label: ejeY?.label, values: ejeY?.values, size: ejeY?.size ?? 52, ...ejeY?.extra }),
      ],
      series: [{ label: ejeX?.label ?? "t", value: (_u, v) => (v == null ? "—" : `${v.toFixed(2)}`) }, ...series],
      hooks: { draw: [() => this._anotar()] },
    };
    if (banda) opciones.bands = [banda];
    return opciones;
  }

  _vacio(nSeries) {
    return Array.from({ length: nSeries + 1 }, () => []);
  }

  // data = [x, ...series]
  datos(data) {
    this.u.setData(data);
  }

  anotaciones({ huecos, marcadores, lineas, franjas }) {
    if (huecos) this.anot.huecos = huecos;
    if (marcadores) this.anot.marcadores = marcadores;
    if (lineas) this.anot.lineas = lineas;
    if (franjas) this.anot.franjas = franjas;
    // redraw(false) = repintar sin recalcular la escala X. Con redraw() a secas,
    // uPlot reenvia scales.x.min/max (que aun no tiene aplicados: setScale los deja
    // pendientes en pendScales hasta el _commit) y sobrescribe el auto-rango que
    // acaba de fijar datos(). Resultado: escala X nula -> valToPos = NaN -> series
    // sin path (se ven ejes y rejilla, pero ninguna linea).
    this.u.redraw(false);
  }

  _anotar() {
    const u = this.u;
    const ctx = u.ctx;
    const caja = u.bbox;
    if (!ctx || !caja) return;
    const { left, top, width, height } = caja;
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, width, height);
    ctx.clip();

    if (this.anot.huecos.length) {
      ctx.fillStyle = "rgba(244, 63, 94, 0.08)";
      for (const [a, b] of this.anot.huecos) {
        const x0 = Math.max(left, u.valToPos(a, "x"));
        const x1 = Math.min(left + width, u.valToPos(b, "x"));
        if (x1 > x0) ctx.fillRect(x0, top, x1 - x0, height);
      }
    }
    if (this.anot.franjas.length) {
      for (const f of this.anot.franjas) {
        const x0 = Math.max(left, u.valToPos(f.a, "x"));
        const x1 = Math.min(left + width, u.valToPos(f.b, "x"));
        if (x1 > x0) {
          ctx.fillStyle = f.color ?? "rgba(34, 211, 238, 0.06)";
          ctx.fillRect(x0, top, x1 - x0, height);
        }
      }
    }
    for (const m of this.anot.marcadores) {
      const px = u.valToPos(m.x, "x");
      const py = u.valToPos(m.y, "y");
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      ctx.beginPath();
      ctx.arc(px, py, m.r ?? 3, 0, Math.PI * 2);
      ctx.fillStyle = m.color ?? color("--bad");
      ctx.fill();
    }
    if (this.anot.lineas.length) {
      ctx.save();
      ctx.setLineDash([5, 4]);
      for (const l of this.anot.lineas) {
        const px = u.valToPos(l.x, "x");
        if (!Number.isFinite(px)) continue;
        ctx.beginPath();
        ctx.moveTo(px, top);
        ctx.lineTo(px, top + height);
        ctx.strokeStyle = l.color ?? color("--text-mute");
        ctx.lineWidth = l.ancho ?? 1.25;
        ctx.stroke();
      }
      ctx.restore();
    }
    ctx.restore();
  }

  _redimensionar() {
    const ancho = this.el.clientWidth;
    if (ancho > 0 && ancho !== this.u.width) this.u.setSize({ width: ancho, height: this.u.height });
  }

  destruir() {
    this.ro.disconnect();
    this.u.destroy();
  }
}

// Huecos: corridas contiguas de `valido === false` expresadas como [t_inicio, t_fin].
export function huecosDe(t, valido) {
  const tramos = [];
  let inicio = -1;
  for (let i = 0; i < valido.length; i += 1) {
    if (!valido[i]) {
      if (inicio < 0) inicio = i;
    } else if (inicio >= 0) {
      tramos.push([t[inicio], t[i - 1]]);
      inicio = -1;
    }
  }
  if (inicio >= 0) tramos.push([t[inicio], t[t.length - 1]]);
  return tramos;
}
