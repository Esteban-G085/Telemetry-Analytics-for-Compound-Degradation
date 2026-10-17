# PredicciÃ³n de degradaciÃ³n de neumÃ¡ticos (Etapas 1, 2 y 3)

Proyecto para predecir la degradaciÃ³n de neumÃ¡ticos a partir de telemetrÃ­a,
pensado para Assetto Corsa (AC).

- **Etapa 1 â€” pipeline offline:** limpieza â†’ features â†’ modelos â†’ evaluaciÃ³n â†’
  reporte, trabajando sobre CSV. Valida toda la lÃ³gica antes de aÃ±adir complejidad.
- **Etapa 2 â€” dashboard interactivo:** un backend **FastAPI** (REST + WebSocket)
  que expone el pipeline de la Etapa 1 para inspeccionarlo en vivo y ajustar
  hiperparÃ¡metros sin recargar.
- **Etapa 3 â€” tiempo real:** captura desde la **memoria compartida de AC**, un
  acondicionador **causal** que filtra y decima a 100 Hz, un motor de anÃ¡lisis en
  ventana deslizante y la **Vista 7 Â«En vivoÂ»** (osciloscopio + degradaciÃ³n +
  predicciÃ³n), mÃ¡s la **app de escritorio** (`desktop.py`, `.bat`, spec de
  PyInstaller).

El diseÃ±o estÃ¡ en [`plan_etapa1.md`](plan_etapa1.md),
[`plan_etapa2.md`](plan_etapa2.md) y [`plan_etapa3.md`](plan_etapa3.md).

## Hoja de ruta

| Etapa | QuÃ© es | Estado |
|---|---|---|
| **1 Â· Pipeline offline** | Limpieza, features, Ridge y Kalman sobre CSV (fuente simulada F1). | Implementada |
| **2 Â· Dashboard** | Backend REST + WebSocket que envuelve el pipeline; frontend uPlot (7 vistas) | **Implementada** |
| **3 Â· Tiempo real** | Captura desde AC (memoria compartida) y predicciÃ³n en ventana deslizante; app local en navegador. | **Implementada** |

La Etapa 1 ya estÃ¡ preparada para la 3: las features se calculan **por ventana**,
el filtro es **causal** (guarda su estado) y los parÃ¡metros de escalado quedan en
el modelo. La Etapa 2 deja lista la infraestructura de streaming (WebSocket con
tramas binarias Float32) y la Etapa 3 aÃ±ade el WS de captura viva.

## Requisitos

```bash
python -m pip install -r requirements.txt
```

Probado con Python 3.11, numpy 2.x, scipy 1.15, pandas 3.x, scikit-learn 1.9 y
FastAPI 0.143. El `requirements.txt` **fusiona** las dependencias de las dos
etapas (no reemplaza las de la Etapa 1: `matplotlib` y `joblib` siguen siendo
necesarias).

El **frontend** solo necesita Node 18+ si vas a compilarlo (`cd frontend && npm install`);
el resultado ya compilado (`frontend/dist/`) se sirve sin Node.

La app local se lanza con `desktop.py` (o `ejecutar_app.bat`) y abre la interfaz en
el navegador por defecto.

## Estructura

```
PROYECTO/
â”œâ”€â”€ config.yaml               # todas las decisiones (secciÃ³n 1 del plan)
â”œâ”€â”€ requirements.txt
â”œâ”€â”€ plan_etapa1.md
â”œâ”€â”€ plan_etapa2.md
â”œâ”€â”€ plan_etapa3.md
â”œâ”€â”€ main.py                   # orquestaciÃ³n de la Etapa 1 (CLI)
â”œâ”€â”€ desktop.py                # lanzador: uvicorn + abre el navegador)
â”œâ”€â”€ ejecutar_app.bat          # doble clic para abrir la app
â”œâ”€â”€ conftest.py               # pytest: raÃ­z en sys.path
â”œâ”€â”€ data/
â”‚   â”œâ”€â”€ raw/                  # CSV crudos + *_verdad.csv (verdad simulada)
â”‚   â”œâ”€â”€ processed/            # seÃ±al limpia (csv.gz), importancias.csv, modelo_ridge.joblib
â”‚   â”œâ”€â”€ vivo/                 # capturas en vivo (crudo + _verdad.csv)
â”‚   â””â”€â”€ reports/              # reporte HTML autocontenido
â”œâ”€â”€ sim/
â”‚   â”œâ”€â”€ generador.py          # fuente F1: genera telemetrÃ­a + degradaciÃ³n real
â”‚   â”œâ”€â”€ ac_info.py            # structs y lectura de la memoria compartida de AC (Win32)
â”‚   â”œâ”€â”€ acondicionador.py     # outliers causales + IIR SOS + decimaciÃ³n a 100 Hz
â”‚   â”œâ”€â”€ fuentes.py            # bus en memoria, FuenteVivo (AC) y FuenteCSV (modo seco)
â”‚   â””â”€â”€ motor_vivo.py         # motor de anÃ¡lisis en ventana deslizante + logger CSV
â”œâ”€â”€ src/                      # ciencia de la Etapa 1 (sin dependencias web)
â”‚   â”œâ”€â”€ config.py             # esquema y carga de config
â”‚   â”œâ”€â”€ limpieza.py           # remuestreo, validaciÃ³n, outliers, filtro
â”‚   â”œâ”€â”€ features.py           # features por ventana
â”‚   â”œâ”€â”€ etiquetas.py          # etiqueta canÃ³nica y proxy
â”‚   â”œâ”€â”€ modelo.py             # Ridge y Kalman
â”‚   â”œâ”€â”€ evaluacion.py         # mÃ©tricas y robustez
â”‚   â””â”€â”€ reporte.py            # figuras + HTML
â”œâ”€â”€ backend/                  # API de las Etapas 2 y 3 (envuelve src/)
â”‚   â”œâ”€â”€ app.py                # instancia FastAPI, CORS, montaje de frontend/dist
â”‚   â”œâ”€â”€ respuestas.py         # respuesta JSON rÃ¡pida (orjson)
â”‚   â”œâ”€â”€ dependencias.py       # inyecciÃ³n de la cachÃ© y de la sesiÃ³n en vivo
â”‚   â”œâ”€â”€ routers/              # sesiones, telemetria, modelos, configuracion, vivo
â”‚   â”œâ”€â”€ ws/                   # stream /ws/telemetria y /api/vivo/stream
â”‚   â””â”€â”€ servicios/
â”‚       â”œâ”€â”€ adaptador_pipeline.py  # envuelve src/ sin I/O innecesario
â”‚       â”œâ”€â”€ cache_memoria.py       # DataFrames procesados en RAM
â”‚       â”œâ”€â”€ vivo.py                # orquesta fuente + bus + motor + logger
â”‚       â”œâ”€â”€ analisis.py            # Ridge, Kalman, espectro, robustez
â”‚       â””â”€â”€ serializacion.py       # numpy -> JSON/Float32
â”œâ”€â”€ frontend/                 # dashboard (Vite + uPlot, sin framework)
â”‚   â”œâ”€â”€ index.html            # shell: barra de sesiÃ³n + pestaÃ±as + favicon inline
â”‚   â”œâ”€â”€ vite.config.js        # proxy /api, /health, /ws hacia el backend en dev
â”‚   â”œâ”€â”€ vitest.config.js      # tests del frontend (jsdom + setup)
â”‚   â”œâ”€â”€ tests/                # montaje de las 7 vistas
â”‚   â””â”€â”€ src/
â”‚       â”œâ”€â”€ main.js           # shell: sesiÃ³n, pestaÃ±as, WebSocket, enrutado
â”‚       â”œâ”€â”€ api.js            # cliente REST + CanalTelemetria / CanalVivo (WS)
â”‚       â”œâ”€â”€ sesion.js         # activar/recargar la sesiÃ³n activa (compartido)
â”‚       â”œâ”€â”€ estado.js         # store mÃ­nimo con pub/sub
â”‚       â”œâ”€â”€ formato.js        # formateo de nÃºmeros/fechas
â”‚       â”œâ”€â”€ componentes/      # graficas.js (uPlot), degradacion.js, tabla_kpis.js
â”‚       â”œâ”€â”€ vistas/           # v_telemetria, v_espectro, v_prediccion,
â”‚       â”‚                     # v_laboratorio, v_robustez, v_replay, v_vivo
â”‚       â””â”€â”€ estilos/          # variables, layout, widgets, uplot_tema
â””â”€â”€ tests/                    # 123 tests de Python
```

## Uso â€” Etapa 1 (pipeline offline)

Genera datos simulados, corre el pipeline completo y escribe el reporte:

```bash
python main.py
```

Procesa un CSV existente (busca `<nombre>_verdad.csv` al lado para validar):

```bash
python main.py --entrada data/raw/sim_42.csv
```

Opciones: `--config`, `--salida`, `--semilla`, `-v`.

## Uso â€” Etapa 2 (backend)

Levanta la API en local:

```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

- DocumentaciÃ³n interactiva (Swagger): <http://127.0.0.1:8000/docs>
- Sonda de vida: <http://127.0.0.1:8000/health>

> Cuando exista `frontend/dist`, `backend/app.py` la monta automÃ¡ticamente en `/`
> y la aplicaciÃ³n web queda servida por este mismo proceso.

### Endpoints REST

| MÃ©todo y ruta | Para quÃ© |
|---|---|
| `GET /health` | Sonda de vida (`200` cuando el servidor estÃ¡ listo). |
| `GET /api/sesiones` | Lista los CSV de `data/raw/` con metadatos y la sesiÃ³n activa. |
| `GET /api/sesiones/activa` | Resumen de la sesiÃ³n activa (vueltas, ventanas, registro de calidad). |
| `POST /api/sesiones/cargar` | Carga un CSV de `data/raw/` por nombre (`{"nombre": "sim_42.csv"}`). |
| `POST /api/sesiones/subir` | Carga un CSV subido (drag & drop, multipart `archivo`). |
| `GET /api/telemetria/canales` | Canales disponibles y fÃ­sicos. |
| `GET /api/telemetria/vuelta/{lap}` | Arrays planos `t` + canales de una vuelta (`canales`, `crudo`, `max_puntos`). |
| `GET /api/telemetria/stint` | Stint completo con min-max bucket downsampling. |
| `GET /api/telemetria/espectro` | PSD de Welch (crudo vs. limpio) en dB/Hz (`canal`, `lap`, `nperseg`). |
| `POST /api/modelos/kalman/estimar` | Filtro de Kalman (`q_nivel`, `q_pendiente`, `r`, `monotono`) + bandas. |
| `POST /api/modelos/ridge/ajustar` | Fija `alpha` (o usa CV) y `excluir`; re-entrena y devuelve mÃ©tricas e importancias. |
| `POST /api/modelos/robustez` | MAE de Ridge frente a ruido inyectado (`snr_db`). |
| `POST /api/modelos/sensores` | Simulador de fallo de sensores: MAE de Ridge al desconectar canales (`caidos`). |
| `GET /api/modelos/features` | Lista de features numÃ©ricas del modelo (selectores de Â§3.2). |
| `GET /api/modelos/dispersion` | DispersiÃ³n por vuelta de dos features (o una vs. la degradaciÃ³n) + ajuste. |
| `GET /api/modelos/correlacion` | Matriz de correlaciÃ³n (por vuelta) entre features y la degradaciÃ³n. |
| `GET /api/config` | ConfiguraciÃ³n activa en JSON. |
| `POST /api/config` | Aplica overrides anidados sobre `config.yaml`. |
| `DELETE /api/config` | Restablece a los valores de fÃ¡brica. |
| `GET /api/config/exportar` | Descarga la configuraciÃ³n como YAML interoperable con `main.py`. |

### WebSocket `/ws/telemetria`

Protocolo hÃ­brido (plan D4):

- **Tramas JSON de control** (cliente â†’ servidor):
  - `{"tipo": "ping"}` â†’ `{"tipo": "pong"}`
  - `{"tipo": "ajuste_kalman", "q_nivel", "q_pendiente", "r", "monotono"}` â†’ `{"tipo": "kalman", ...}`
  - `{"tipo": "ajuste_ridge", "alpha", "excluir"}` â†’ `{"tipo": "ridge", ...}`
  - `{"tipo": "trama", "lap", "canales", "inicio", "fin"}` â†’ cabecera JSON + una trama binaria
- **Tramas binarias**: tras una cabecera JSON (`{"tipo": "trama", "canales": [...], "n_muestras": N}`)
  se envÃ­a un `Float32Array` little-endian con forma `[n_canales, n_muestras]`, que el cliente monta
  directo en un `Float32Array` sin parseo JSON.

Los cÃ³mputos pesados se despachan con `asyncio.to_thread` / `run_in_threadpool` para que el event
loop nunca se bloquee.

> El **replay** no vive en el backend: sobre una sesiÃ³n grabada el frontend ya tiene las muestras
> en un `Float32Array` y reproduce avanzando un cursor. El streaming en vivo sÃ­ nace en el
> servidor y se sirve por `/api/vivo/stream` (Etapa 3).

## Uso â€” Etapa 3 (tiempo real)

La captura usa la **memoria compartida de AC** (`Local\acpmf_physics`,
`Local\acpmf_graphics`, `Local\acpmf_static`) vÃ­a la API de Win32 con `ctypes`
(sin dependencias nuevas) y se apoya en `sim/ac_info.py`. Para desarrollar sin AC
en pista estÃ¡ el **modo seco**, que reproduce un CSV por la misma ruta que el
dato real (mismo acondicionador causal), garantizando la coherencia con el batch
(hay un test que la fija: `tests/test_coherencia_live_batch.py`).

Flujo: `Fuente` (memoria de AC o CSV) â†’ `BusTiempoReal` â†’ `AcondicionadorCausal`
(outliers causales + IIR SOS 20 Hz + decimaciÃ³n a 100 Hz) â†’ `MotorVivo` (features
en ventana deslizante + Ridge + Kalman) â†’ `LoggerVivo` (CSV con el esquema del
proyecto + `<nombre>_verdad.csv` si la fuente trae verdad) â†’ WebSocket a ~10 Hz.

### Endpoints REST

| MÃ©todo y ruta | Para quÃ© |
|---|---|
| `POST /api/vivo/iniciar` | Arranca la captura (`fuente`: `ac` o `seco`; `archivo`, `ritmo_hz`, `bucle`). |
| `POST /api/vivo/detener` | Detiene la captura y cierra el CSV. |
| `GET /api/vivo/estado` | Estado del motor: muestras, vuelta, grip, degradaciÃ³n, predicciÃ³n, ruta del CSV. |
| `GET /api/vivo/ventana` | Ventana deslizante para el osciloscopio (`canales`, `n`). |
| `GET /api/vivo/sesiones` | Capturas guardadas en `data/vivo/`. |
| `GET /api/vivo/layout` | DiagnÃ³stico de la memoria compartida (Â¿estÃ¡ AC publicando?). |

### WebSocket `/api/vivo/stream`

El servidor empuja una trama JSON cada ~100 ms con `tipo: "vivo"`: `n`, `lap`,
`grip.<rueda>`, `degradacion.<rueda>`, `degradacion_modo`, `prediccion`, la
`ventana` (t + series) y el `espectro` de la ventana. El cliente puede enviar
`{"canales": [...], "n": 600}` para elegir quÃ© ventana recibe y `{"tipo": "ping"}`.

### App local (navegador)

```bash
python desktop.py                    # abre la app (uvicorn en hilo) y abre el navegador
python desktop.py --modo seco        # arranca el modo seco con el CSV demo
python desktop.py --modo ac          # arranca la captura desde AC
python desktop.py --sin-navegador      # solo el servidor (diagnÃ³stico)
```

`desktop.py` levanta `uvicorn` en un hilo, espera a `/health` y abre la UI en una
ventana nativa con **pywebview**; si no estÃ¡ instalado, cae al **navegador** por
defecto (D10). Doble clic en `ejecutar_app.bat`.

y `sim_test_99.csv` como Ãºnica sesiÃ³n de demo):

```bash
```

(â‰ˆ39 MB el `.exe`, â‰ˆ360 MB la carpeta con todas las dependencias). Se validÃ³
lanzÃ¡ndolo con `--sin-ventana --modo seco` y comprobando `/health`, la captura en
directo (`/api/vivo/estado`) y el frontend servido en `/`.

> `sys.stdout`/`sys.stderr` son `None` y uvicorn no arranca; `desktop.py` los
> redirige a `os.devnull` al importarse y, si el hilo del servidor falla, escribe
> `error_servidor.log` junto al `.exe`.

## Uso â€” Etapa 2 (frontend)

El dashboard es una app **Vite + [uPlot](https://github.com/leeoniya/uPlot)** sin
framework (D8: objeto plano + pub/sub). En desarrollo habla con el backend por el
proxy de Vite (rutas relativas `/api`, `/ws`):

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173  (proxy -> backend en :8000)
```

Para producciÃ³n, compila y deja que FastAPI sirva el resultado en `/`:

```bash
npm run build        # genera frontend/dist/ (lo monta backend/app.py)
```

Tests de montaje (jsdom, sin navegador):

```bash
npm test             # vitest: cada vista monta y limpia sin lanzar
```

### Las siete vistas

| # | Vista | QuÃ© muestra |
|---|---|---|
| 1 | **TelemetrÃ­a** | SeÃ±al cruda vs. limpia de una vuelta, marcadores de outliers, huecos invÃ¡lidos y KPIs de calidad. |
| 2 | **Espectro** | PSD de Welch (crudo vs. limpio) con las bandas sombreadas y la atenuaciÃ³n por banda; planta 2Ã—2 con la media por rueda y dispersiÃ³n de features (Â§3.2). |
| 3 | **PredicciÃ³n** | Verdad/proxy, Ridge y Kalman por vuelta, bandas de confianza, lÃ­neas de caÃ­da y tabla de mÃ©tricas. |
| 4 | **Laboratorio** | Sliders de Î±/Q/R y ablaciÃ³n (reactivos por WebSocket) + limpieza y `k_fuel` (reprocesan la sesiÃ³n); guardar / descargar / restablecer config. |
| 5 | **Robustez** | MAE de Ridge frente a ruido inyectado (con cursor de SNR), importancias con verificaciÃ³n de signo fÃ­sico y simulador de fallo de sensores (Â§3.5). |
| 6 | **Replay** | ReproducciÃ³n local del stint con ventana deslizante, control de velocidad y degradaciÃ³n estimada de la vuelta en curso. |
| 7 | **En vivo** | Captura desde AC (o modo seco): osciloscopio de la ventana reciente, espectro, planta 2Ã—2 con el semÃ¡foro de degradaciÃ³n y predicciÃ³n Kalman; control de iniciar/detener. |

> La **Vista 4** separa los controles en dos familias: los del **modelo** (Ridge Î±,
> Kalman Q/R, monotonicidad, ablaciÃ³n) viajan por el WebSocket y recalculan la curva
> sin recargar; los de **limpieza/features** (corte, MAD, gradosÂ·segundo, `k_fuel`)
> se guardan como overrides y **reprocesan** el CSV (`POST /api/config` +
> `POST /api/sesiones/cargar`), que es la operaciÃ³n lenta.

### Trampa de uPlot: nunca llames a `redraw()` sin argumentos

Todas las grÃ¡ficas pasan por el envoltorio `Panel` de
`frontend/src/componentes/graficas.js`. AhÃ­ vive una trampa que dejÃ³ el dashboard
**entero sin lÃ­neas** (se veÃ­an ejes y rejilla, pero ninguna serie) y conviene no
reintroducir:

- `uPlot.redraw()` **sin argumentos** ejecuta `_setScale("x", scales.x.min, scales.x.max)`.
- Pero `uPlot.setScale()` **no aplica el rango de inmediato**: lo deja *pendiente* en
  `pendScales` y lo aplica `setScales()` dentro del `_commit`, que corre en un microtask.
- Los paneles se crean y se rellenan en el mismo tick (`new Panel(...)` â†’ `datos()` â†’
  `anotaciones()`). Cuando `anotaciones()` llama a `redraw()`, el auto-rango que acaba de
  fijar `datos()` **aÃºn no se ha aplicado**, asÃ­ que `scales.x.min/max` siguen valiendo
  `null`; `redraw()` reenvÃ­a ese `null` y **sobrescribe** el rango pendiente.
- Resultado: escala X nula â†’ `valToPos(x, "x")` devuelve `NaN` para todos los puntos â†’
  el *path* de cada serie sale vacÃ­o â†’ ejes sÃ­, lÃ­neas no.

Por eso `Panel.anotaciones()` llama a **`this.u.redraw(false)`**: repinta vÃ­a `commit()`
(el hook `_anotar` se ejecuta igual) **sin tocar la escala X**. Regla prÃ¡ctica: para
repintar anotaciones usa `redraw(false)` o `commit()`, **nunca `redraw()` a secas**.

CÃ³mo detectar un fallo asÃ­: **contar pÃ­xeles de serie** dentro del Ã¡rea de trazado
(color saturado distinto de la rejilla). Mirar solo el tamaÃ±o del `<canvas>`, que exista
`.uplot` o que no haya errores de consola **no demuestra que se dibuje nada**. En tests
headless con Edge/Chrome, `document.hidden` es `true` y `requestAnimationFrame` no
dispara; uPlot no usa `rAF` (dibuja por `queueMicrotask`), pero conviene recordarlo.

## Pruebas

```bash
python -m pytest -q
```

**123 tests** de Python en verde. Cobertura por Ã¡rea:

| Fichero | QuÃ© cubre |
|---|---|
| `tests/test_limpieza.py`, `test_features.py`, `test_etiquetas.py`, `test_modelo.py`, `test_evaluacion.py`, `test_generador.py`, `test_reporte.py`, `test_pipeline.py` | Etapa 1 (53 tests). |
| `tests/test_api_rest.py` | Endpoints REST: arrays alineados, downsampling, crudo vs. limpio, 404/400/422, subida de CSV, robustez, stint, reset de config. |
| `tests/test_api_ws.py` | WebSocket: control, tramas binarias. |
| `tests/test_coherencia_api.py` | La API reproduce **exactamente** el pipeline de `main.py` (Ridge por CV y Kalman con los Q/R de `config.yaml`), el PSD de Welch y los MAE de referencia de `sim_42.csv`. |
| `tests/test_rendimiento.py` | Latencia y tramas contra un servidor **`uvicorn` real** (el `TestClient` no mide red). |
| `tests/test_api_modelos_extra.py` | Extras Â§3.2/Â§3.5: features, dispersiÃ³n, correlaciÃ³n y simulador de fallo de sensores. |
| `tests/test_ac_info.py` | Offsets/tamaÃ±os de los structs de AC y el camino Â«AC no estÃ¡ publicandoÂ». |
| `tests/test_acondicionador.py` | DecimaciÃ³n a la frecuencia objetivo, atenuaciÃ³n del filtro y outliers causales. |
| `tests/test_fuentes.py` | `BusTiempoReal` y `FuenteCSV` (decimaciÃ³n, esquema y verdad inyectada). |
| `tests/test_motor_vivo.py` | DegradaciÃ³n desde grip auto-calibrado, predicciÃ³n Kalman y logger CSV. |
| `tests/test_vivo_api.py` | Endpoints `/api/vivo/*` y el WebSocket `/api/vivo/stream`. |
| `tests/test_coherencia_live_batch.py` | **D14**: la ruta en vivo (outliers causales + filtro + decimaciÃ³n) reproduce la seÃ±al del pipeline batch con correlaciÃ³n > 0.97. |

Y **8 tests del frontend** con [Vitest](https://vitest.dev/) + jsdom (`cd frontend && npm test`):

| Fichero | QuÃ© cubre |
|---|---|
| `frontend/tests/montaje.test.js` | Cada una de las 7 vistas monta en el DOM, rellena su contenedor y devuelve una limpieza vÃ¡lida sin tocar la red. |

Latencia medida contra `uvicorn` real (cachÃ© caliente): REST â‰ˆ 13 ms, Kalman por WS â‰ˆ 3 ms,
re-fit de Ridge por WS â‰ˆ 16 ms.

## ParÃ¡metros ajustables (`config.yaml`)

| Clave | Para quÃ© sirve |
|---|---|
| `sim.vueltas`, `sim.fs_original` | tamaÃ±o de la sesiÃ³n simulada y frecuencia de captura |
| `sim.acople` | fuerza del acoplamiento degradaciÃ³n â†” slip/temperatura (0 = desacoplado) |
| `sim.tasa_degradacion` | cuÃ¡nto se acelera el desgaste al final del stint (0 = lineal, alto = caÃ­da marcada) |
| `etiquetas.k_fuel_s_kg` | correcciÃ³n del proxy por combustible; con `calibrar_k_fuel: true` se estima por regresiÃ³n |
| `modelo.ridge_alphas`, `modelo.ridge_clip` | regularizaciÃ³n de Ridge y recorte de features extremas |
| `modelo.kalman.*` | Q/R fijos del filtro (`monotono: true` impone no-decrecimiento) |
| `limpieza.filtro.corte_hz` | corte del Butterworth causal |
| `features.welch_nperseg` | resoluciÃ³n del PSD de Welch (`128` â†’ Î”f â‰ˆ 0.78 Hz a 100 Hz) |

Los sliders del dashboard se inicializan con estos valores y `DELETE /api/config` los restablece.

## VerificaciÃ³n fÃ­sica de los coeficientes

El reporte incluye el signo de cada coeficiente estandarizado. Se espera signo
positivo en los grupos ligados al desgaste (grados-segundo, temperatura, slip,
carga, trabajo de fricciÃ³n, PSD). En la corrida de referencia los grupos
`grados_segundo`, `temp`, `carga` y `psd` salen mayoritariamente positivos, pero
**slip** queda repartido: como las features estÃ¡n muy correlacionadas, los signos
individuales no son concluyentes. Por eso la verificaciÃ³n es un **diagnÃ³stico
reportado**, no una condiciÃ³n de aprobaciÃ³n.

## Fuentes de datos

| Fuente | QuÃ© es | Desgaste real | Estado |
|---|---|---|---|
| **F1. Simulada** | `sim/generador.py` (cÃ³digo propio) | SÃ­, por construcciÃ³n | Usada en Etapa 1, 2 y 3 (modo seco) |
| **F2. Live Telemetry** | App de AC que guarda logs CSV por rueda | SÃ­ (`Tire wear %`) | ExtensiÃ³n opcional (Etapa 2) |
| **F3. Logger propio** | `sim/` + `backend/servicios/vivo.py` sobre la memoria compartida de AC | Parcial (`tyreWear` como grip) | **Etapa 3** |
| **F4. Datasets pÃºblicos** | Vueltas de AC en Hugging Face (parquet) | No | Pruebas de limpieza |

En las Etapas 1 y 2 se usa **solo F1** (datos propios, sin licencia externa). El
alcance obligatorio de la Etapa 2 es F1 + drag & drop de CSV; F2 y F4 requieren un
**adaptador de esquema** (mapeo de columnas al contrato) y quedan como extensiÃ³n
opcional. La Etapa 3 gira en torno a **F3**: el logger propio lee la memoria
compartida de AC y deriva la degradaciÃ³n del `tyreWear` (grip) auto-calibrado
contra su pico. Hay que **revisar la licencia de cada dataset** antes de publicar
resultados (el dataset de Silverstone GP es MIT). Detalle en `plan_etapa1.md`, Â§2.

## Esquema de datos

Cualquier fuente (F1â€¦F4) debe producir estas columnas (el contrato estÃ¡ en
`src/config.py`; el backend lo **valida** al cargar):

- Base: `timestamp_s`, `lap`, `speed_kmh`, `throttle`, `brake`, `steering`, `fuel_kg`.
- Por rueda `fl`, `fr`, `rl`, `rr`: `temp_core_c_*`, `pressure_psi_*`,
  `wheel_slip_*`, `wheel_load_n_*`, `dirty_level_*`.

| Canal | Unidad | Rango esperado |
|---|---|---|
| `temp_core_c` | Â°C | 60 â€“ 120 |
| `pressure_psi` | psi | 20 â€“ 35 |
| `wheel_load_n` | N | 0 â€“ 15000 |
| `wheel_slip` | adimensional | 0 â€“ ~0.5 (con picos) |
| `dirty_level` | adimensional | 0 â€“ 1 |
| `speed_kmh` | km/h | 0 â€“ ~350 |

## Pipeline

1. **Remuestreo** a 100 Hz con `resample_poly` (antialias) sobre rejilla uniforme.
2. **ValidaciÃ³n** de esquema y marcado de valores fuera de rango fÃ­sico.
3. **Outliers** por mediana/MAD en ventana causal (0.5 s, 12Â·MAD, con piso de Ïƒ global).
   El backend expone las mÃ¡scaras para poder marcar los picos en el dashboard.
4. **Huecos cortos** interpolados sin cruzar vueltas; los largos quedan marcados
   como invÃ¡lidos (`valido = False`).
5. **Filtro** Butterworth orden 4, 20 Hz, causal (`sosfilt`), guardando el estado.
6. **Features por ventana** W = 2.0 s, hop = 1.0 s (estadÃ­sticos de slip, carga y
   temperatura, trabajo de fricciÃ³n, grados-segundo y potencia espectral por bandas).
7. **Etiquetas**: verdad simulada (F1) o proxy por tiempo de vuelta corregido por
   combustible, suavizado y monÃ³tono.
8. **Modelos** comparados a nivel de vuelta: Ridge (entrenado por ventana y agregado)
   y Kalman (nivel + tendencia).
9. **Reporte** HTML con seÃ±al cruda vs. limpia, espectro, features, predicciÃ³n,
   robustez frente al ruido, tabla de importancias, verificaciÃ³n fÃ­sica de signos,
   cobertura y error de la vuelta de caÃ­da, sensibilidad de Kalman a R
   y **trazabilidad** (config usado + sha256 del CSV de entrada).

Los artefactos reutilizables quedan en `data/processed/`:
`senal_limpia.csv.gz`, `importancias.csv` y `modelo_ridge.joblib` (este Ãºltimo sirve
para la Etapa 3).

## Resultados de referencia (semilla 42, 40 vueltas)

| Modelo | MAE |
|---|---|
| Ridge (ventana â†’ vuelta) | **0.0023** |
| Kalman (vuelta) | **0.0197** |
| Ridge ablacionado (sin slip/temp/trabajo) | 0.354 |
| Baseline (media) | 0.5244 |
| Baseline (persistencia: Ãºltima vuelta de train) | 0.1623 |

La API reproduce estos MAE con `POST /api/modelos/ridge/ajustar` (Î± por CV) y
`POST /api/modelos/kalman/estimar` (Q/R de `config.yaml`); hay un test que lo fija
(`tests/test_coherencia_api.py`).

Proxy vs. verdad: correlaciÃ³n **0.998**, MAE 0.027. Error en la vuelta de caÃ­da: **0**.
El Kalman lineal queda por detrÃ¡s de Ridge porque la degradaciÃ³n simulada se acelera
al final del stint (curva de caÃ­da no lineal); aun asÃ­ se mantiene en ~0.02 subiendo
`q_pendiente` (1e-5) para que la pendiente siga esa aceleraciÃ³n. La cobertura de las
bandas al 95 % da 1.00 (bandas conservadoras: la observaciÃ³n es la degradaciÃ³n
verdadera, casi sin ruido) y se reporta la sensibilidad a R en el HTML.

## Pendiente de la Etapa 2

El backend, el frontend y la distribuciÃ³n estÃ¡n completos:

- [x] **Backend** (`backend/`, FastAPI REST + WebSocket).
- [x] **Frontend** (`frontend/`, Vite + uPlot): las **siete vistas** â€” 1 telemetrÃ­a,
      2 espectro, 3 predicciÃ³n, 4 laboratorio, 5 robustez, 6 replay, 7 en vivo.
- [x] **App local (`desktop.py` + `ejecutar_app.bat`) que abre el navegador por defecto) y scripts `.bat`.
      validado en Windows (`dist\TelemetryAnalytics\TelemetryAnalytics.exe`).
- [x] **Streaming** servidorâ†’cliente: implementado en la Etapa 3 (`/api/vivo/stream`).

Quedan dos extras de la Etapa 2 (mÃ³dulos Â§3.2 y Â§3.5 del plan), ya implementados:

- [x] **DispersiÃ³n de features** (Â§3.2): panel en la Vista 2 con selectores X/Y (una
      feature vs. la degradaciÃ³n u otra feature), nube de puntos por vuelta, recta
      de ajuste y coeficiente de correlaciÃ³n; endpoint `GET /api/modelos/dispersion`
      (y `GET /api/modelos/correlacion` para la matriz).
- [x] **Simulador de fallo de sensores** (Â§3.5): panel en la Vista 5 con
      interruptores por canal Ã— rueda (slip, temperatura, carga, presiÃ³n) y globales
      (velocidad, acelerador, freno, direcciÃ³n); muestra el MAE de Ridge con y sin
      cada canal y el mismo MAE tras el suavizado de Kalman; endpoint
      `POST /api/modelos/sensores`.

Solo queda la **validaciÃ³n visual a 60 FPS con 360k muestras**, que requiere un
navegador real (no se puede medir con jsdom).

## Limitaciones conocidas

- **Circularidad de la simulaciÃ³n.** El generador acopla la degradaciÃ³n con el slip y
  la temperatura. Por eso el modelo recupera la degradaciÃ³n casi perfecto *y* el
  modelo ablacionado (sin features derivadas de slip/temperatura/trabajo de fricciÃ³n)
  no logra batir al baseline de persistencia. La evidencia cuantitativa de la
  simulaciÃ³n es dÃ©bil para afirmar generalizaciÃ³n a datos reales; hay que repetir con
  las fuentes F2/F3 (desgaste real) y con un generador menos acoplado.
  Nota: `trabajo_friccion = Î£|slip|Â·cargaÂ·vÂ·dt` **deriva del slip**, por eso se excluye
  de la ablaciÃ³n aunque su nombre no contenga "slip".
- **Split temporal.** Se entrena con vueltas tempranas y se predice con tardÃ­as: es el
  escenario realista, pero exige defensas contra la extrapolaciÃ³n (D12/D13).
- **Filtro y outliers.** El detector es causal y conservador; con pocas vueltas el
  `--entrada` de un CSV sin verdad usa el proxy como etiqueta.
- **`k_fuel` en la simulaciÃ³n.** El generador F1 **sÃ­** modela la masa de combustible
  sobre el tiempo de vuelta (auto mÃ¡s liviano â‡’ mÃ¡s rÃ¡pido) y la degradaciÃ³n tambiÃ©n
  lo afecta (menos agarre en curva â‡’ mÃ¡s lento). Aun asÃ­ `calibrar_k_fuel` cae al
  valor fijo de config: en las primeras vueltas la degradaciÃ³n ya crece con fuerza y
  enmascara la tendencia del combustible (pendiente con signo confundido). El proxy
  sigue funcionando porque ahora su mecanismo principal es la pÃ©rdida de agarre, no
  la monotonÃ­a del combustible. En datos reales (F2) la calibraciÃ³n deberÃ­a activarse.
