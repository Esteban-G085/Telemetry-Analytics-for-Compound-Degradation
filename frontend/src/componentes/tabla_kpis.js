// Tarjetas de indicadores.

export function pintarKpis(contenedor, tarjetas) {
  contenedor.innerHTML = tarjetas
    .map(
      (t) => `
      <div class="kpi ${t.tono ?? ""}">
        <div class="etiqueta">${t.etiqueta}</div>
        <div class="valor">${t.valor}${t.unidad ? `<span class="unidad">${t.unidad}</span>` : ""}</div>
        ${t.pie ? `<div class="pie">${t.pie}</div>` : ""}
      </div>`,
    )
    .join("");
}

export function kpi(etiqueta, valor, { unidad, pie, tono } = {}) {
  return { etiqueta, valor, unidad, pie, tono };
}
