// Test de montaje del frontend: cada vista debe poder insertarse en el DOM,
// rellenar su contenedor y devolver una función de limpieza (o nada), sin
// tocar la red ni lanzar. Se ejecuta con jsdom.

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import * as vTelemetria from "../src/vistas/v_telemetria.js";
import * as vEspectro from "../src/vistas/v_espectro.js";
import * as vPrediccion from "../src/vistas/v_prediccion.js";
import * as vLaboratorio from "../src/vistas/v_laboratorio.js";
import * as vRobustez from "../src/vistas/v_robustez.js";
import * as vReplay from "../src/vistas/v_replay.js";
import * as vVivo from "../src/vistas/v_vivo.js";

// Debe coincidir con VISTAS de main.js (7 vistas).
const VISTAS = [
  { id: "telemetria", num: "1", modulo: vTelemetria },
  { id: "espectro", num: "2", modulo: vEspectro },
  { id: "prediccion", num: "3", modulo: vPrediccion },
  { id: "laboratorio", num: "4", modulo: vLaboratorio },
  { id: "robustez", num: "5", modulo: vRobustez },
  { id: "replay", num: "6", modulo: vReplay },
  { id: "vivo", num: "7", modulo: vVivo },
];

class WebSocketFalso {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSING = 2;
  static CLOSED = 3;
  constructor() {
    this.readyState = WebSocketFalso.CONNECTING;
    this.binaryType = "arraybuffer";
  }
  send() {}
  close() {
    this.readyState = WebSocketFalso.CLOSED;
  }
}

beforeEach(() => {
  // La vista «En vivo» abre un WebSocket al montar; se sustituye por un doble.
  globalThis.WebSocket = WebSocketFalso;
  // Ninguna vista debe salir a la red en un test de montaje.
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("montaje de las vistas", () => {
  it("hay siete vistas con módulo montar()", () => {
    expect(VISTAS).toHaveLength(7);
    for (const v of VISTAS) expect(typeof v.modulo.montar).toBe("function");
  });

  it.each(VISTAS)("la vista $num · $id monta y limpia sin lanzar", ({ modulo }) => {
    const contenedor = document.createElement("div");
    document.body.appendChild(contenedor);

    const limpiar = modulo.montar(contenedor);
    expect(contenedor.innerHTML.length).toBeGreaterThan(0);
    if (limpiar !== undefined && limpiar !== null) {
      expect(typeof limpiar).toBe("function");
    }

    // La limpieza no debe lanzar y debe ser idempotente ante el DOM vacío.
    if (typeof limpiar === "function") limpiar();
    contenedor.remove();
  });
});
