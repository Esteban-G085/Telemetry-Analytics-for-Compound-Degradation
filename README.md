# Predicción de degradación de neumáticos (Etapas 1, 2 y 3)

Proyecto para predecir la degradación de neumáticos a partir de telemetría,
pensado para Assetto Corsa (AC).

- **Etapa 1 — pipeline offline:** limpieza → features → modelos → evaluación →
  reporte, trabajando sobre CSV. Valida toda la lógica antes de añadir complejidad.
- **Etapa 2 — backend + interfaz:** un backend **FastAPI** (REST + WebSocket)
  que expone el pipeline de la Etapa 1 y una **GUI nativa PySide6** con 8 pestañas
  para inspeccionarlo y ajustar hiperparámetros sin recargar.
- **Etapa 3 — tiempo real:** captura desde la **memoria compartida de AC**, un
  acondicionador **causal** que filtra y decima a 100 Hz, un motor de análisis en
  ventana deslizante y la pestaña **«En vivo»** (osciloscopio + degradación +
  predicción). La app local se abre con `python -m telemetria` o `ejecutar_app.bat`.

El diseño está en [`docs/plan_etapa1.md`](docs/plan_etapa1.md),
[`docs/plan_etapa2.md`](docs/plan_etapa2.md) y [`docs/plan_etapa3.md`](docs/plan_etapa3.md).

## Hoja de ruta

| Etapa | Qué es | Estado |
|---|---|---|
| **1 · Pipeline offline** | Limpieza, features, Ridge y Kalman sobre CSV (fuente simulada F1). | Implementada |
| **2 · Interfaz** | Backend REST + WebSocket que envuelve el pipeline; GUI PySide6 (8 pestañas) | **Implementada** |
| **3 · Tiempo real** | Captura desde AC (memoria compartida) y predicción en ventana deslizante; app local en navegador. | **Implementada** |

La Etapa 1 ya está preparada para la 3: las features se calculan **por ventana**,
el filtro es **causal** (guarda su estado) y los parámetros de escalado quedan en
el modelo. La Etapa 2 deja lista la infraestructura de streaming (WebSocket con
tramas binarias Float32) y la Etapa 3 añade el WS de captura viva.

## Requisitos

```bash
python -m pip install -r requirements.txt
```

Probado con Python 3.11, numpy 2.x, scipy 1.15, pandas 3.x, scikit-learn 1.9 y
FastAPI 0.143. El `requirements.txt` **fusiona** las dependencias de las dos
etapas (no reemplaza las de la Etapa 1: `matplotlib` y `joblib` siguen siendo
necesarias).

La **GUI de escritorio** necesita `PySide6`, `PySide6-Addons` (QtWebSockets) y
`pyqtgraph`, ya incluidos en `requirements.txt`. No se necesita Node: el
frontend Vite/uPlot original fue sustituido por la GUI y ya no está en el
repositorio.

La app local se lanza con `python -m telemetria` (o doble clic en
`ejecutar_app.bat`) y abre la ventana nativa. La guía rápida está en
[`GUI_USO.md`](GUI_USO.md).

## Estructura

```
PROYECTO/
├── config.yaml               # todas las decisiones (sección 1 del plan)
├── requirements.txt
├── conftest.py               # pytest: raíz en sys.path
├── ejecutar_app.bat          # doble clic para abrir la app
├── docs/
│   ├── plan_etapa1.md
│   ├── plan_etapa2.md
│   └── plan_etapa3.md
├── telemetria/               # paquete único: TODO el código Python
│   ├── cli.py                # punto de entrada: `python -m telemetria`
│   ├── pipeline/             # Etapa 1: ciencia offline
│   │   ├── config.py         # esquema y carga de config
│   │   ├── limpieza.py       # remuestreo, validación, outliers, filtro
│   │   ├── features.py       # features por ventana
│   │   ├── etiquetas.py      # etiqueta canónica y proxy
│   │   ├── modelo.py         # Ridge y Kalman
│   │   ├── evaluacion.py     # métricas y robustez
│   │   ├── reporte.py        # figuras + HTML
│   │   └── orquestador.py    # orquestación del pipeline (CLI)
│   ├── adquisicion/          # Etapa 3: generador + captura en vivo
│   │   ├── generador.py      # fuente F1: genera telemetría + degradación real
│   │   ├── ac_info.py        # structs y lectura de la memoria compartida de AC (Win32)
│   │   ├── acondicionador.py # outliers causales + IIR SOS + decimación a 100 Hz
│   │   ├── fuentes.py        # bus en memoria, FuenteVivo (AC) y FuenteCSV (modo seco)
│   │   └── motor_vivo.py     # motor de análisis en ventana deslizante + logger CSV
│   └── api/                  # Etapas 2 y 3: backend FastAPI (envuelve el pipeline)
│       ├── app.py            # instancia FastAPI y CORS (la GUI es otro cliente)
│       ├── lanzador.py       # arranca uvicorn en un hilo (y el modo navegador legado)
│       ├── respuestas.py     # respuesta JSON rápida (orjson)
│       ├── dependencias.py   # inyección de la caché y de la sesión en vivo
│       ├── routers/          # sesiones, telemetria, modelos, configuracion, vivo
│       ├── ws/               # stream /ws/telemetria y /api/vivo/stream
│       └── servicios/
│           ├── adaptador_pipeline.py  # envuelve el pipeline sin I/O innecesario
│           ├── cache_memoria.py       # DataFrames procesados en RAM
│           ├── vivo.py                # orquesta fuente + bus + motor + logger
│           ├── analisis.py            # Ridge, Kalman, espectro, robustez
│           └── serializacion.py       # numpy -> JSON/Float32
│   └── gui/                  # interfaz nativa (PySide6): 8 pestañas
│       ├── main.py           # arranca uvicorn en hilo + QApplication
│       ├── ventana_principal.py
│       ├── etiquetas_canales.py  # nombres legibles y columnas de contexto ocultas
│       ├── cliente_api.py    # REST (httpx) + WS (QWebSocket) en hilos de fondo
│       └── vistas/           # sesiones, telemetria, espectro, prediccion,
│                             # laboratorio, robustez, replay, vivo
├── data/
│   ├── raw/                  # CSV crudos + *_verdad.csv (verdad simulada)
│   ├── processed/            # señal limpia (csv.gz), importancias.csv, modelo_ridge.joblib
│   ├── vivo/                 # capturas en vivo (crudo + _verdad.csv)
│   └── reports/              # reporte HTML autocontenido
└── tests/                    # tests de Python (pipeline, API y GUI offscreen)
```

## Uso — Etapa 1 (pipeline offline)

Genera datos simulados, corre el pipeline completo y escribe el reporte:

```bash
python -m telemetria pipeline
```

Procesa un CSV existente (busca `<nombre>_verdad.csv` al lado para validar):

```bash
python -m telemetria pipeline --entrada data/raw/sim_42.csv
```

Opciones: `--config`, `--salida`, `--semilla`, `-v`.

## Uso — Etapa 2 (backend)

Levanta la API en local:

```bash
python -m uvicorn telemetria.api.app:app --host 127.0.0.1 --port 8000
```

- Documentación interactiva (Swagger): <http://127.0.0.1:8000/docs>
- Sonda de vida: <http://127.0.0.1:8000/health>

> El backend ya no sirve archivos estáticos: la GUI de escritorio se conecta a
> estos endpoints como cualquier otro cliente (ver `GUI_USO.md`).

### Endpoints REST

| Método y ruta | Para qué |
|---|---|
| `GET /health` | Sonda de vida (`200` cuando el servidor está listo). |
| `GET /api/sesiones` | Lista los CSV de `data/raw/` con metadatos y la sesión activa. |
| `GET /api/sesiones/activa` | Resumen de la sesión activa (vueltas, ventanas, registro de calidad). |
| `POST /api/sesiones/cargar` | Carga un CSV de `data/raw/` por nombre (`{"nombre": "sim_42.csv"}`). |
| `POST /api/sesiones/subir` | Carga un CSV subido (drag & drop, multipart `archivo`). |
| `GET /api/telemetria/canales` | Canales disponibles y físicos. |
| `GET /api/telemetria/vuelta/{lap}` | Arrays planos `t` + canales de una vuelta (`canales`, `crudo`, `max_puntos`). |
| `GET /api/telemetria/stint` | Stint completo con min-max bucket downsampling. |
| `GET /api/telemetria/espectro` | PSD de Welch (crudo vs. limpio) en dB/Hz (`canal`, `lap`, `nperseg`). |
| `POST /api/modelos/kalman/estimar` | Filtro de Kalman (`q_nivel`, `q_pendiente`, `r`, `monotono`) + bandas. |
| `POST /api/modelos/ridge/ajustar` | Fija `alpha` (o usa CV) y `excluir`; re-entrena y devuelve métricas e importancias. |
| `POST /api/modelos/robustez` | MAE de Ridge frente a ruido inyectado (`snr_db`). |
| `POST /api/modelos/sensores` | Simulador de fallo de sensores: MAE de Ridge al desconectar canales (`caidos`). |
| `GET /api/modelos/features` | Lista de features numéricas del modelo (selectores de §3.2). |
| `GET /api/modelos/dispersion` | Dispersión por vuelta de dos features (o una vs. la degradación) + ajuste. |
| `GET /api/modelos/correlacion` | Matriz de correlación (por vuelta) entre features y la degradación. |
| `GET /api/config` | Configuración activa en JSON. |
| `POST /api/config` | Aplica overrides anidados sobre `config.yaml`. |
| `DELETE /api/config` | Restablece a los valores de fábrica. |
| `GET /api/config/exportar` | Descarga la configuración como YAML interoperable con `python -m telemetria pipeline`. |

### WebSocket `/ws/telemetria`

Protocolo híbrido (plan D4):

- **Tramas JSON de control** (cliente → servidor):
  - `{"tipo": "ping"}` → `{"tipo": "pong"}`
  - `{"tipo": "ajuste_kalman", "q_nivel", "q_pendiente", "r", "monotono"}` → `{"tipo": "kalman", ...}`
  - `{"tipo": "ajuste_ridge", "alpha", "excluir"}` → `{"tipo": "ridge", ...}`
  - `{"tipo": "trama", "lap", "canales", "inicio", "fin"}` → cabecera JSON + una trama binaria
- **Tramas binarias**: tras una cabecera JSON (`{"tipo": "trama", "canales": [...], "n_muestras": N}`)
  se envía un `Float32Array` little-endian con forma `[n_canales, n_muestras]`, que el cliente monta
  directo en un `Float32Array` sin parseo JSON.

Los cómputos pesados se despachan con `asyncio.to_thread` / `run_in_threadpool` para que el event
loop nunca se bloquee.

> El **replay** no vive en el backend: sobre una sesión grabada la GUI pide cada vuelta
> por `/api/telemetria/vuelta/{lap}` y la dibuja. El streaming en vivo sí nace en el
> servidor y se sirve por `/api/vivo/stream` (Etapa 3).

## Uso — Etapa 3 (tiempo real)

La captura usa la **memoria compartida de AC** (`Local\acpmf_physics`,
`Local\acpmf_graphics`, `Local\acpmf_static`) vía la API de Win32 con `ctypes`
(sin dependencias nuevas) y se apoya en `telemetria/adquisicion/ac_info.py`. Para desarrollar sin AC
en pista está el **modo seco**, que reproduce un CSV por la misma ruta que el
dato real (mismo acondicionador causal), garantizando la coherencia con el batch
(hay un test que la fija: `tests/test_coherencia_live_batch.py`).

Flujo: `Fuente` (memoria de AC o CSV) → `BusTiempoReal` → `AcondicionadorCausal`
(outliers causales + IIR SOS 20 Hz + decimación a 100 Hz) → `MotorVivo` (features
en ventana deslizante + Kalman; **Ridge no interviene en vivo**) → `LoggerVivo`
(CSV **crudo**, antes del acondicionador, con el esquema del proyecto + columnas
extra `packetId`, `grip_*` y `degradacion`, y `<nombre>_verdad.csv` si hay
etiqueta) → WebSocket a ~10 Hz.

Robustez operativa: los suscriptores del bus y de la fuente se aíslan con
`try/except` (un fallo no tumba la captura), `FuenteVivo` cuenta los `packetId`
**salteados** y mide la frecuencia real de captura, el CSV se crea **perezosamente**
en el primer registro (una fuente que no arranca no deja un archivo vacío) y
`POST /api/vivo/iniciar` no responde "activo" hasta confirmar que la fuente preparó
bien.

### Endpoints REST

| Método y ruta | Para qué |
|---|---|
| `POST /api/vivo/iniciar` | Arranca la captura (`fuente`: `ac` o `seco`; `archivo`, `ritmo_hz`, `bucle`). `ritmo_hz` es un **interruptor**: `0` = máxima velocidad, ausente/`>0` = tiempo real según los timestamps del CSV. |
| `POST /api/vivo/detener` | Detiene la captura y cierra el CSV. |
| `GET /api/vivo/estado` | Estado del motor (muestras, vuelta, grip, degradación, predicción, ruta del CSV) + diagnóstico de captura (`paquetes_perdidos`, `fs_medida`, `errores_subs`). |
| `GET /api/vivo/ventana` | Ventana deslizante para el osciloscopio (`canales`, `n`). |
| `GET /api/vivo/sesiones` | Capturas guardadas en `data/vivo/`. |
| `GET /api/vivo/layout` | Diagnóstico de la memoria compartida (¿está AC publicando?). |

### WebSocket `/api/vivo/stream`

El servidor empuja una trama JSON cada ~100 ms con `tipo: "vivo"`: `n`, `lap`,
`grip.<rueda>`, `degradacion.<rueda>`, `degradacion_modo`, `prediccion` (agregada +
`por_rueda`), la `ventana` (t + series) y el `espectro` de la ventana. El cliente
puede enviar `{"canales": [...], "n": 200}` para elegir qué ventana recibe y
`{"tipo": "ping"}`.

### App local (GUI de escritorio)

```bash
python -m telemetria                    # abre la GUI (uvicorn en hilo + ventana nativa)
python -m telemetria gui                # equivalente, explicito
python -m telemetria pipeline           # solo el pipeline offline
python -m telemetria app --sin-navegador  # legado: solo el servidor (diagnóstico)
```

`telemetria/gui/main.py` levanta `uvicorn` en un hilo, espera a `/health` y abre
la ventana PySide6. Doble clic en `ejecutar_app.bat` hace lo mismo sin escribir
comandos. El subcomando `app` es el antiguo lanzador de navegador y queda como
diagnóstico; no abre interfaz porque el frontend Vite/uPlot ya no está incluido.

## Uso — Interfaz de escritorio (GUI)

La GUI es una app **PySide6 + pyqtgraph**. No necesita Node ni navegador: habla
con el backend por las mismas rutas REST `/api` y WebSocket `/ws`, `/api/vivo/stream`.

```bash
python -m telemetria          # o doble clic en ejecutar_app.bat
```

Flujo normal: abrir la pestaña **Sesiones**, elegir un CSV de `data/raw/` y pulsar
**Cargar sesión seleccionada**. Al cargar, las demás pestañas se recargan solas.
Antes de cargar una sesión muestran «Sin sesión activa» en lugar de errores HTTP.

### Las ocho pestañas

| # | Pestaña | Qué muestra |
|---|---|---|
| 1 | **Sesiones** | Lista de CSV, carga de sesión y resumen (vueltas, muestras). |
| 2 | **Telemetría** | Canales disponibles, gráfico de tramas binarias del WS y mensajes de control. |
| 3 | **Espectro** | PSD de Welch (crudo vs. limpio) del canal y vuelta elegidos. |
| 4 | **Predicción** | Verdad/proxy, Ridge y Kalman por vuelta, tabla de MAE/RMSE y recálculo de α y Q/R. |
| 5 | **Laboratorio** | Q/R de Kalman, configuración activa y features; guardar/restablecer config. |
| 6 | **Robustez** | MAE frente a ruido inyectado (SNR) y simulador de fallo de sensores. |
| 7 | **Replay** | Comparador de varias señales de una vuelta + detalle crudo/limpio, outliers y KPIs. |
| 8 | **En vivo** | Captura AC/modo seco, estado del motor y osciloscopio del WS de vivo. |

Cada pestaña lleva arriba un bloque «Qué estás viendo» siempre visible. Los
selectores muestran nombres como «Acelerador» o «Deslizamiento FL (delantera
izquierda)» en lugar de claves internas; `timestamp_s` y `lap` no se ofrecen como
señales porque son el eje temporal y el agrupador de vueltas. En **Replay** se
pueden comparar varias señales de la misma vuelta (atajos preparados, selección
manual y normalización 0–1) sin perder el panel de detalle de una sola señal.

El panel superior permite conectar/desconectar el WebSocket `/ws/telemetria`.
En la pestaña **En vivo**, al iniciar una captura se abre automáticamente
`/api/vivo/stream` (~10 Hz) para el osciloscopio. Detalles en `GUI_USO.md`.

> Las gráficas usan **pyqtgraph**. Al actualizar una curva conviene pasar siempre
> `x` e `y` a `setData()`: un `setData(valores)` solo interpreta el array como
> valores de entrada y deja el eje X en su índice, que no es el tiempo de muestreo.

## Pruebas

```bash
python -m pytest -q
```

**156 tests** de Python en verde (incluidos 13 de humo de la GUI en modo `offscreen`).
Cobertura por área:

| Fichero | Qué cubre |
|---|---|
| `tests/test_limpieza.py`, `test_features.py`, `test_etiquetas.py`, `test_modelo.py`, `test_evaluacion.py`, `test_generador.py`, `test_reporte.py`, `test_pipeline.py` | Etapa 1 (53 tests). |
| `tests/test_api_rest.py` | Endpoints REST: arrays alineados, downsampling, crudo vs. limpio, 404/400/422, subida de CSV, robustez, stint, reset de config. |
| `tests/test_api_ws.py` | WebSocket: control, tramas binarias. |
| `tests/test_coherencia_api.py` | La API reproduce **exactamente** el pipeline de `telemetria.pipeline` (Ridge por CV y Kalman con los Q/R de `config.yaml`), el PSD de Welch y los MAE de referencia de `sim_42.csv`. |
| `tests/test_rendimiento.py` | Latencia y tramas contra un servidor **`uvicorn` real** (el `TestClient` no mide red). |
| `tests/test_api_modelos_extra.py` | Extras §3.2/§3.5: features, dispersión, correlación y simulador de fallo de sensores. |
| `tests/test_ac_info.py` | Offsets/tamaños de los structs de AC y el camino «AC no está publicando». |
| `tests/test_acondicionador.py` | Decimación a la frecuencia objetivo, atenuación del filtro y outliers causales. |
| `tests/test_fuentes.py` | `BusTiempoReal` y `FuenteCSV` (decimación, esquema y verdad inyectada). |
| `tests/test_motor_vivo.py` | Degradación desde grip auto-calibrado, predicción Kalman (agregada y **por rueda**) y logger CSV. |
| `tests/test_vivo_api.py` | Endpoints `/api/vivo/*` y el WebSocket `/api/vivo/stream` (incluye detener bajo carga). |
| `tests/test_coherencia_live_batch.py` | **D14**: la ruta en vivo (outliers causales + filtro + decimación) reproduce la señal del pipeline batch con correlación > 0.97. Incluye el reprocesado del **CSV crudo** del logger en batch (logger → batch, A1/C/D4). |
| `tests/test_gui.py` | GUI PySide6 sin red: arranca sin sesión, se refresca al cargarla, usa nombres amables, ayuda visible y un comparador multi-señal en Replay; gráficos/tablas usan el formato real de la API. |

Latencia medida contra `uvicorn` real (caché caliente): REST ≈ 13 ms, Kalman por WS ≈ 3 ms,
re-fit de Ridge por WS ≈ 16 ms.

## Parámetros ajustables (`config.yaml`)

| Clave | Para qué sirve |
|---|---|
| `sim.vueltas`, `sim.fs_original` | tamaño de la sesión simulada y frecuencia de captura |
| `sim.acople` | fuerza del acoplamiento degradación ↔ slip/temperatura (0 = desacoplado) |
| `sim.tasa_degradacion` | cuánto se acelera el desgaste al final del stint (0 = lineal, alto = caída marcada) |
| `etiquetas.k_fuel_s_kg` | corrección del proxy por combustible; con `calibrar_k_fuel: true` se estima por regresión |
| `modelo.ridge_alphas`, `modelo.ridge_clip` | regularización de Ridge y recorte de features extremas |
| `modelo.kalman.*` | Q/R fijos del filtro (`monotono: true` impone no-decrecimiento) |
| `limpieza.filtro.corte_hz` | corte del Butterworth causal |
| `features.welch_nperseg` | resolución del PSD de Welch (`128` → Δf ≈ 0.78 Hz a 100 Hz) |

> **Nota (B8):** la banda «alta» (15–40 Hz) cae en la zona de transición del
> Butterworth a 20 Hz. Su potencia depende de `corte_hz`, así que no conviene cambiar
> el corte sin reinterpretar esa banda (ni al revés).

Los sliders del dashboard se inicializan con estos valores y `DELETE /api/config` los restablece.

## Verificación física de los coeficientes

El reporte incluye el signo de cada coeficiente estandarizado. Se espera signo
positivo en los grupos ligados al desgaste (grados-segundo, temperatura, slip,
carga, trabajo de fricción, PSD). En la corrida de referencia los grupos
`grados_segundo`, `temp`, `carga` y `psd` salen mayoritariamente positivos, pero
**slip** queda repartido: como las features están muy correlacionadas, los signos
individuales no son concluyentes. Por eso la verificación es un **diagnóstico
reportado**, no una condición de aprobación.

## Fuentes de datos

| Fuente | Qué es | Desgaste real | Estado |
|---|---|---|---|
| **F1. Simulada** | `telemetria/adquisicion/generador.py` (código propio) | Sí, por construcción | Usada en Etapa 1, 2 y 3 (modo seco) |
| **F2. Live Telemetry** | App de AC que guarda logs CSV por rueda | Sí (`Tire wear %`) | Extensión opcional (Etapa 2) |
| **F3. Logger propio** | `telemetria/adquisicion/` + `telemetria/api/servicios/vivo.py` sobre la memoria compartida de AC | Parcial (`tyreWear` como grip) | **Etapa 3** |
| **F4. Datasets públicos** | Vueltas de AC en Hugging Face (parquet) | No | Pruebas de limpieza |

En las Etapas 1 y 2 se usa **solo F1** (datos propios, sin licencia externa). El
alcance obligatorio de la Etapa 2 es F1 + drag & drop de CSV; F2 y F4 requieren un
**adaptador de esquema** (mapeo de columnas al contrato) y quedan como extensión
opcional. La Etapa 3 gira en torno a **F3**: el logger propio lee la memoria
compartida de AC y deriva la degradación del `tyreWear` (grip) auto-calibrado
contra su pico. Hay que **revisar la licencia de cada dataset** antes de publicar
resultados (el dataset de Silverstone GP es MIT). Detalle en `docs/plan_etapa1.md`, §2.

## Esquema de datos

Cualquier fuente (F1…F4) debe producir estas columnas (el contrato está en
`telemetria/pipeline/config.py`; el backend lo **valida** al cargar):

- Base: `timestamp_s`, `lap`, `speed_kmh`, `throttle`, `brake`, `steering`, `fuel_kg`.
- Por rueda `fl`, `fr`, `rl`, `rr`: `temp_core_c_*`, `pressure_psi_*`,
  `wheel_slip_*`, `wheel_load_n_*`, `dirty_level_*`.

| Canal | Unidad | Rango esperado |
|---|---|---|
| `temp_core_c` | °C | 60 – 120 |
| `pressure_psi` | psi | 20 – 35 |
| `wheel_load_n` | N | 0 – 15000 |
| `wheel_slip` | adimensional | 0 – ~0.5 (con picos) |
| `dirty_level` | adimensional | 0 – 1 |
| `speed_kmh` | km/h | 0 – ~350 |

## Pipeline

1. **Remuestreo** a 100 Hz con `resample_poly` (antialias) sobre rejilla uniforme.
2. **Validación** de esquema y marcado de valores fuera de rango físico.
3. **Outliers** por mediana/MAD en ventana causal (0.5 s, 12·MAD, con piso de σ global).
   El backend expone las máscaras para poder marcar los picos en el dashboard.
4. **Huecos cortos** interpolados sin cruzar vueltas; los largos quedan marcados
   como inválidos (`valido = False`).
5. **Filtro** Butterworth orden 4, 20 Hz, causal (`sosfilt`), guardando el estado.
6. **Features por ventana** W = 2.0 s, hop = 1.0 s (estadísticos de slip, carga y
   temperatura, trabajo de fricción, grados-segundo y potencia espectral por bandas).
7. **Etiquetas**: verdad simulada (F1) o proxy por tiempo de vuelta corregido por
   combustible, suavizado y monótono.
8. **Modelos** comparados a nivel de vuelta: Ridge (entrenado por ventana y agregado)
   y Kalman (nivel + tendencia).
9. **Reporte** HTML con señal cruda vs. limpia, espectro, features, predicción,
   robustez frente al ruido, tabla de importancias, verificación física de signos,
   cobertura y error de la vuelta de caída, sensibilidad de Kalman a R
   y **trazabilidad** (config usado + sha256 del CSV de entrada).

Los artefactos reutilizables quedan en `data/processed/`:
`senal_limpia.csv.gz`, `importancias.csv` y `modelo_ridge.joblib` (este último sirve
para la Etapa 3).

## Resultados de referencia (semilla 42, 40 vueltas)

| Modelo | MAE |
|---|---|
| Ridge (ventana → vuelta) | **0.0023** |
| Kalman (vuelta) | **0.0197** |
| Ridge ablacionado (sin slip/temp/trabajo) | 0.354 |
| Baseline (media) | 0.5244 |
| Baseline (persistencia: última vuelta de train) | 0.1623 |

La API reproduce estos MAE con `POST /api/modelos/ridge/ajustar` (α por CV) y
`POST /api/modelos/kalman/estimar` (Q/R de `config.yaml`); hay un test que lo fija
(`tests/test_coherencia_api.py`).

Proxy vs. verdad: correlación **0.998**, MAE 0.027. Error en la vuelta de caída: **0**.
El Kalman lineal queda por detrás de Ridge porque la degradación simulada se acelera
al final del stint (curva de caída no lineal); aun así se mantiene en ~0.02 subiendo
`q_pendiente` (1e-5) para que la pendiente siga esa aceleración. La cobertura de las
bandas al 95 % da 1.00 (bandas conservadoras: la observación es la degradación
verdadera, casi sin ruido) y se reporta la sensibilidad a R en el HTML. Ese 1.00 no
debe leerse como logro: con la etiqueta simulada casi sin ruido las bandas no se
ponen a prueba. En pista conviene **calibrar `R` con el error del proxy** (MAE 0.027)
para que reflejen incertidumbre real.

## Estado de la Etapa 2

El backend, la GUI de escritorio y el lanzador están completos:

- [x] **Backend** (`telemetria/api/`, FastAPI REST + WebSocket).
- [x] **GUI** (`telemetria/gui/`, PySide6 + pyqtgraph): las **ocho pestañas** —
      1 sesiones, 2 telemetría, 3 espectro, 4 predicción, 5 laboratorio,
      6 robustez, 7 replay, 8 en vivo.
- [x] **App local** (`python -m telemetria` + `ejecutar_app.bat`) que abre la
      ventana nativa. No se necesita Node ni navegador.
- [x] **Streaming** servidor→cliente: implementado en la Etapa 3
      (`/api/vivo/stream`), conectado al osciloscopio de la pestaña «En vivo».

Extras del plan §3.2 y §3.5:

- [x] **Dispersión/correlación de features** (§3.2): disponible en la API
      (`GET /api/modelos/dispersion` y `GET /api/modelos/correlacion`). La GUI
      actual no tiene un panel dedicado para esta nube de puntos.
- [x] **Simulador de fallo de sensores** (§3.5): pestaña **Robustez**, con
      canales × rueda y el MAE de Ridge con/sin cada fallo; endpoint
      `POST /api/modelos/sensores`.

Queda como mejora opcional la **validación visual a 60 FPS con 360k muestras**;
el pipeline y la API ya están cubiertos por tests de rendimiento y coherencia.

## Limitaciones conocidas

- **Circularidad de la simulación.** El generador acopla la degradación con el slip y
  la temperatura. Por eso el modelo recupera la degradación casi perfecto *y* el
  modelo ablacionado (sin features derivadas de slip/temperatura/trabajo de fricción)
  no logra batir al baseline de persistencia. La evidencia cuantitativa de la
  simulación es débil para afirmar generalización a datos reales; hay que repetir con
  las fuentes F2/F3 (desgaste real) y con un generador menos acoplado.
  Nota: `trabajo_friccion = Σ|slip|·carga·v·dt` **deriva del slip**, por eso se excluye
  de la ablación aunque su nombre no contenga "slip".
- **Split temporal.** Se entrena con vueltas tempranas y se predice con tardías: es el
  escenario realista, pero exige defensas contra la extrapolación (D12/D13).
- **Filtro y outliers.** El detector es causal y conservador; con pocas vueltas el
  `--entrada` de un CSV sin verdad usa el proxy como etiqueta.
- **`k_fuel` en la simulación.** El generador F1 **sí** modela la masa de combustible
  sobre el tiempo de vuelta (auto más liviano ⇒ más rápido) y la degradación también
  lo afecta (menos agarre en curva ⇒ más lento). Aun así `calibrar_k_fuel` cae al
  valor fijo de config: en las primeras vueltas la degradación ya crece con fuerza y
  enmascara la tendencia del combustible (pendiente con signo confundido). El proxy
  sigue funcionando porque ahora su mecanismo principal es la pérdida de agarre, no
  la monotonía del combustible. En datos reales (F2) la calibración debería activarse.
