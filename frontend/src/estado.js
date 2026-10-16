// Almacén mínimo con pub/sub. ponytail: objeto plano + Set, sin framework.

const oyentes = new Set();

export const estado = {
  sesionActiva: null, // resumen devuelto por /api/sesiones/activa
  vueltas: [], //      [{lap, duracion_s, ...}]
  laps: [],
  canales: [], //     columnas disponibles en la sesión
  fisicas: [], //     columnas con interpretación física
  canal: "wheel_slip",
  rueda: "fl",
  lap: null,
  stint: false, //    vista de stint completo vs. vuelta suelta
  wsEstado: "desconectado",
  ultimoKalman: null, // último mensaje {tipo:"kalman"} del WebSocket
  ultimoRidge: null, //  último mensaje {tipo:"ridge"} del WebSocket
};

export function suscribir(fn) {
  oyentes.add(fn);
  return () => oyentes.delete(fn);
}

export function actualizar(cambios) {
  Object.assign(estado, cambios);
  for (const fn of oyentes) fn(estado);
}

export function haySesion() {
  return Boolean(estado.sesionActiva);
}
