// Cliente de la API (REST + WebSocket).
// En dev Vite hace de proxy, así que siempre se usan rutas relativas.

async function pedir(ruta, opciones) {
  const res = await fetch(ruta, opciones);
  if (!res.ok) {
    let detalle = `${res.status} ${res.statusText}`;
    try {
      const cuerpo = await res.json();
      if (cuerpo && cuerpo.detail) detalle = typeof cuerpo.detail === "string" ? cuerpo.detail : JSON.stringify(cuerpo.detail);
    } catch {
      /* respuesta sin JSON */
    }
    throw new Error(detalle);
  }
  return res.json();
}

const enviar = (cuerpo) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cuerpo ?? {}),
});

function qs(params) {
  const sp = new URLSearchParams();
  for (const [clave, valor] of Object.entries(params)) {
    if (valor === undefined || valor === null || valor === "") continue;
    sp.set(clave, Array.isArray(valor) ? valor.join(",") : String(valor));
  }
  const texto = sp.toString();
  return texto ? `?${texto}` : "";
}

export const api = {
  sesiones: () => pedir("/api/sesiones"),
  sesionActiva: () => pedir("/api/sesiones/activa"),
  cargar: (nombre) => pedir("/api/sesiones/cargar", enviar({ nombre })),
  subir: (archivo) => {
    const datos = new FormData();
    datos.append("archivo", archivo);
    return pedir("/api/sesiones/subir", { method: "POST", body: datos });
  },

  canales: () => pedir("/api/telemetria/canales"),
  vuelta: (lap, { canales, crudo = true, maxPuntos = 20000 } = {}) =>
    pedir(`/api/telemetria/vuelta/${lap}${qs({ canales, crudo, max_puntos: maxPuntos })}`),
  stint: ({ canales, crudo = true, maxPuntos = 20000 } = {}) =>
    pedir(`/api/telemetria/stint${qs({ canales, crudo, max_puntos: maxPuntos })}`),
  espectro: ({ canal, lap, nperseg } = {}) =>
    pedir(`/api/telemetria/espectro${qs({ canal, lap, nperseg })}`),

  kalman: (params) => pedir("/api/modelos/kalman/estimar", enviar(params)),
  ridge: (params) => pedir("/api/modelos/ridge/ajustar", enviar(params)),
  robustez: (params) => pedir("/api/modelos/robustez", enviar(params)),
  sensores: (params) => pedir("/api/modelos/sensores", enviar(params)),
  features: () => pedir("/api/modelos/features"),
  dispersion: ({ x, y = "degradacion" } = {}) =>
    pedir(`/api/modelos/dispersion${qs({ x, y })}`),
  correlacion: ({ features } = {}) => pedir(`/api/modelos/correlacion${qs({ features })}`),

  // --- Etapa 3: captura en vivo ---
  vivoSesiones: () => pedir("/api/vivo/sesiones"),
  vivoLayout: () => pedir("/api/vivo/layout"),
  vivoEstado: () => pedir("/api/vivo/estado"),
  vivoIniciar: ({ fuente = "ac", archivo, ritmoHz, bucle } = {}) =>
    pedir("/api/vivo/iniciar", enviar({ fuente, archivo, ritmo_hz: ritmoHz ?? null, bucle: !!bucle })),
  vivoDetener: () => pedir("/api/vivo/detener", enviar({})),
  vivoVentana: ({ n, canales } = {}) => pedir(`/api/vivo/ventana${qs({ n, canales })}`),

  config: () => pedir("/api/config"),
  guardarConfig: (overrides) => pedir("/api/config", enviar(overrides)),
  reiniciarConfig: () => pedir("/api/config", { method: "DELETE" }),
  urlExportarConfig: "/api/config/exportar",
};

// --------------------------------------------------------------------------
// WebSocket de telemetría (D3). Reconexión con retroceso exponencial.
// --------------------------------------------------------------------------
export class CanalTelemetria {
  constructor({ onMensaje, onBinario, onEstado, ruta = "/ws/telemetria" } = {}) {
    this.onMensaje = onMensaje ?? (() => {});
    this.onBinario = onBinario ?? (() => {});
    this.onEstado = onEstado ?? (() => {});
    this.ruta = ruta;
    this.socket = null;
    this.reintento = 0;
    this.cerrado = false;
    this._conectar();
  }

  _url() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}${this.ruta}`;
  }

  _conectar() {
    this.onEstado("conectando");
    const socket = new WebSocket(this._url());
    socket.binaryType = "arraybuffer";
    this.socket = socket;

    socket.onopen = () => {
      this.reintento = 0;
      this.onEstado("conectado");
    };
    socket.onmessage = (evento) => {
      if (typeof evento.data === "string") {
        try {
          this.onMensaje(JSON.parse(evento.data));
        } catch {
          /* mensaje no-JSON */
        }
      } else {
        this.onBinario(evento.data);
      }
    };
    socket.onclose = () => {
      this.onEstado("desconectado");
      if (this.cerrado) return;
      const espera = Math.min(8000, 500 * 2 ** this.reintento++);
      setTimeout(() => this._conectar(), espera);
    };
    socket.onerror = () => socket.close();
  }

  get abierto() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  enviar(mensaje) {
    if (this.abierto) this.socket.send(JSON.stringify(mensaje));
  }

  cerrar() {
    this.cerrado = true;
    this.socket?.close();
  }
}

// Canal de captura en vivo (Etapa 3): mismas garantías de reconexión que el
// de telemetría, pero apuntando al stream que el servidor empuja.
export class CanalVivo extends CanalTelemetria {
  constructor(opciones = {}) {
    super({ ...opciones, ruta: "/api/vivo/stream" });
  }
}

// Decodifica una trama binaria Float32 little-endian con cabecera JSON.
// cabecera: { canales: [...], n_muestras, dtype }
export function decodificarTrama(buffer, cabecera) {
  const flotantes = new Float32Array(buffer);
  const n = cabecera.n_muestras;
  const filas = cabecera.canales.map((canal, i) => ({
    canal,
    valores: flotantes.subarray(i * n, (i + 1) * n),
  }));
  return filas;
}
