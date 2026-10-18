// Serie de degradación por vuelta compartida por la Vista 3 (predicción) y la
// Vista 4 (laboratorio). Aquí viven series, datos, anotaciones y la tabla; el
// lienzo lo gestiona `Panel` de `graficas.js`.

import { Panel, color, linea } from "./graficas.js";
import { num } from "../formato.js";

// Alinea valores indexados por vuelta sobre el eje x común (rellena con null).
export function alinear(laps, valores, x) {
  const mapa = new Map();
  laps.forEach((l, i) => mapa.set(l, valores[i]));
  return x.map((l) => (mapa.has(l) ? mapa.get(l) : null));
}

// Primera vuelta cuyo valor alcanza el umbral (null si no se cruza).
export function cruce(laps, valores, umbral) {
  for (let i = 0; i < valores.length; i += 1) {
    if (valores[i] !== null && valores[i] >= umbral) return laps[i];
  }
  return null;
}

const media = (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : null);

// Definición fija de las series (mismos colores en ambas vistas).
export function seriesDegradacion() {
  return [
    linea({ etiqueta: "verdad", color: color("--text"), ancho: 2.2, formateador: (v) => num(v, 4) }),
    linea({ etiqueta: "proxy", color: color("--warn"), ancho: 1.3 }),
    linea({ etiqueta: "Ridge", color: color("--ok"), ancho: 1.8 }),
    linea({ etiqueta: "Kalman", color: color("--accent"), ancho: 1.8 }),
    linea({ etiqueta: "IC inf", color: "rgba(34, 211, 238, 0.45)", ancho: 1, dash: [3, 3] }),
    linea({ etiqueta: "IC sup", color: "rgba(34, 211, 238, 0.45)", ancho: 1, dash: [3, 3] }),
    linea({ etiqueta: "baseline media", color: color("--text-mute"), ancho: 1.2, dash: [6, 4] }),
    linea({ etiqueta: "baseline último", color: color("--text-mute"), ancho: 1.2, dash: [2, 4] }),
  ];
}

export const OPCIONES_DEGRADACION = {
  altura: 320,
  banda: { series: [5, 6], fill: "rgba(34, 211, 238, 0.12)" },
  ejeX: { label: "vuelta", values: (_u, t) => t.map((v) => (Number.isInteger(v) ? String(v) : "")) },
  ejeY: { label: "degradación" },
};

// Series, datos y anotaciones de la gráfica de degradación. Puro: sin DOM.
export function datosDegradacion(ridge, kalman, umbral) {
  const x = ridge.laps_all;
  const cruces = {
    verdad: cruce(ridge.verdad_laps, ridge.verdad, umbral),
    ridge: cruce(ridge.laps_all, ridge.pred_all, umbral),
    kalman: cruce(kalman.laps_test, kalman.pred, umbral),
  };

  // Baselines ingenuas: media y último valor de la verdad en el tramo de train.
  const verdadPorLap = new Map(ridge.verdad_laps.map((l, i) => [l, ridge.verdad[i]]));
  const yTrain = kalman.laps_train.map((l) => verdadPorLap.get(l)).filter((v) => v != null);
  const m = media(yTrain);
  const ultimo = yTrain.length ? yTrain[yTrain.length - 1] : null;
  const enTest = new Set(kalman.laps_test);

  const data = [
    x,
    alinear(ridge.verdad_laps, ridge.verdad, x),
    alinear(ridge.proxy_laps, ridge.proxy, x),
    ridge.pred_all,
    alinear(kalman.laps_test, kalman.pred, x),
    alinear(kalman.laps_test, kalman.banda_inf, x),
    alinear(kalman.laps_test, kalman.banda_sup, x),
    x.map((l) => (enTest.has(l) ? m : null)),
    x.map((l) => (enTest.has(l) ? ultimo : null)),
  ];

  const lineas = [
    cruces.verdad != null && { x: cruces.verdad, color: "rgba(230,235,242,0.6)" },
    cruces.ridge != null && { x: cruces.ridge, color: color("--ok") },
    cruces.kalman != null && { x: cruces.kalman, color: color("--accent") },
  ].filter(Boolean);

  return { data, lineas, cruces };
}

// Crea el panel (series fijas) listo para recibir datos con `pintarDegradacion`.
export function crearPanelDegradacion(elemento) {
  return new Panel(elemento, { series: seriesDegradacion(), ...OPCIONES_DEGRADACION });
}

// Vuelca una estimación nueva sobre un panel ya creado.
export function pintarDegradacion(panel, ridge, kalman, umbral) {
  const { data, lineas, cruces } = datosDegradacion(ridge, kalman, umbral);
  panel.datos(data);
  panel.anotaciones({ lineas });
  return cruces;
}

// Atajo: crea el panel y lo pinta de una vez (Vista 3).
export function dibujarDegradacion(elemento, ridge, kalman, umbral) {
  const panel = crearPanelDegradacion(elemento);
  const cruces = pintarDegradacion(panel, ridge, kalman, umbral);
  return { panel, cruces };
}

// Tabla HTML de métricas de precisión (Ridge vs. Kalman).
export function tablaMetricas(ridge, kalman) {
  const filas = [
    ["Ridge", ridge.metricas, null, ridge.error_caida],
    ["Kalman", kalman.metricas, kalman.cobertura, kalman.error_caida],
  ];
  return `
    <table class="tabla">
      <thead><tr><th>Modelo</th><th>MAE</th><th>RMSE</th><th>R²</th><th>Cobertura IC</th><th>Δ caída (vueltas)</th></tr></thead>
      <tbody>
        ${filas
          .map(
            ([nombre, m, cob, err]) => `
          <tr>
            <td class="mono">${nombre}</td>
            <td class="mono">${num(m.mae, 4)}</td>
            <td class="mono">${num(m.rmse, 4)}</td>
            <td class="mono">${num(m.r2, 3)}</td>
            <td class="mono">${cob == null ? "—" : `${(cob * 100).toFixed(1)} %`}</td>
            <td class="mono">${Number.isNaN(err) ? "—" : num(err, 0)}</td>
          </tr>`,
          )
          .join("")}
      </tbody>
    </table>`;
}
