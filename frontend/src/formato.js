// Formateo numérico en español.

export function num(valor, decimales = 2) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return Number(valor).toFixed(decimales);
}

export function entero(valor) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return Math.round(Number(valor)).toLocaleString("es-ES");
}

export function pct(valor, decimales = 1) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return `${(Number(valor) * 100).toFixed(decimales)} %`;
}
