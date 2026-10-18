// Ciclo de vida de la sesión activa. Lo comparten el shell (`main.js`) y las
// vistas que necesitan reprocesar (Vista 4 · Laboratorio).

import { api } from "./api.js";
import { actualizar } from "./estado.js";

// Pinta el indicador de sesión de la barra superior.
export function ponerPill(texto, tono) {
  const pill = document.getElementById("estado-sesion");
  if (!pill) return;
  pill.textContent = texto;
  pill.className = `pill ${tono ?? ""}`;
}

// Publica una sesión ya procesada en el estado global.
export async function activarSesion(resumen) {
  const { canales, fisicas } = await api.canales();
  actualizar({
    sesionActiva: resumen,
    vueltas: resumen.vueltas ?? [],
    laps: resumen.laps ?? [],
    canales,
    fisicas,
    lap: (resumen.laps ?? [])[0] ?? null,
    stint: false,
  });
  return resumen;
}

// Reprocesa un CSV de `data/raw` (tras cambiar la config) y lo deja activo.
export async function recargarSesion(nombre) {
  const resumen = await api.cargar(nombre);
  await activarSesion(resumen);
  return resumen;
}
