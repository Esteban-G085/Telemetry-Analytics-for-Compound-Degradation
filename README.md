# Predicción de degradación de neumáticos (Etapas 1 y 2)

Proyecto para predecir la degradación de neumáticos a partir de telemetría,
pensado para Assetto Corsa (AC).

- **Etapa 1 — pipeline offline:** limpieza → features → modelos → evaluación →
  reporte, trabajando sobre CSV. Valida toda la lógica antes de añadir complejidad.
- **Etapa 2 — dashboard interactivo:** un backend **FastAPI** (REST + WebSocket)
  que expone el pipeline de la Etapa 1 para inspeccionarlo en vivo, ajustar
  hiperparámetros sin recargar y preparar la Etapa 3 (tiempo real).

El diseño está en [`plan_etapa1.md`](plan_etapa1.md) y
[`plan_etapa2.md`](plan_etapa2.md).

## Hoja de ruta

| Etapa | Qué es | Estado |
|---|---|---|
| **1 · Pipeline offline** | Limpieza, features, Ridge y Kalman sobre CSV (fuente simulada F1). | Implementada |
| **2 · Dashboard** | Backend REST + WebSocket que envuelve el pipeline; frontend uPlot y app de escritorio. | **Backend implementado y probado** (frontend y `.exe` pendientes) |
| **3 · Tiempo real** | Captura desde AC y predicción en ventana deslizante. | Pendiente |

La Etapa 1 ya está preparada para la 3: las features se calculan **por ventana**,
el filtro es **causal** (guarda su estado) y los parámetros de escalado quedan en
el modelo. La Etapa 2 deja lista la infraestructura de streaming (WebSocket con
tramas binarias Float32) para reutilizarla tal cual.

## Requisitos

```bash
python -m pip install -r requirements.txt
```

Probado con Python 3.11, numpy 2.x, scipy 1.15, pandas 3.x, scikit-learn 1.9 y
FastAPI 0.143. El `requirements.txt` **fusiona** las dependencias de las dos
etapas (no reemplaza las de la Etapa 1: `matplotlib` y `joblib` siguen siendo
necesarias).

## Estructura

```
PROYECTO/
├── config.yaml               # todas las decisiones (sección 1 del plan)
├── requirements.txt
├── plan_etapa1.md
├── plan_etapa2.md
├── main.py                   # orquestación de la Etapa 1 (CLI)
├── conftest.py               # pytest: raíz en sys.path
├── data/
│   ├── raw/                  # CSV crudos + *_verdad.csv (verdad simulada)
│   ├── processed/            # señal limpia (csv.gz), importancias.csv, modelo_ridge.joblib
│   └── reports/              # reporte HTML autocontenido
├── sim/
│   └── generador.py          # fuente F1: genera telemetría + degradación real
├── src/                      # ciencia de la Etapa 1 (sin dependencias web)
│   ├── config.py             # esquema y carga de config
│   ├── limpieza.py           # remuestreo, validación, outliers, filtro
│   ├── features.py           # features por ventana
│   ├── etiquetas.py          # etiqueta canónica y proxy
│   ├── modelo.py             # Ridge y Kalman
│   ├── evaluacion.py         # métricas y robustez
│   └── reporte.py            # figuras + HTML
├── backend/                  # API de la Etapa 2 (envuelve src/)
│   ├── app.py                # instancia FastAPI, CORS, montaje de frontend/dist
│   ├── respuestas.py         # respuesta JSON rápida (orjson)
│   ├── dependencias.py       # inyección de la caché
│   ├── routers/              # sesiones, telemetria, modelos, configuracion
│   ├── ws/                   # stream /ws/telemetria (control JSON + tramas binarias)
│   └── servicios/
│       ├── adaptador_pipeline.py  # envuelve src/ sin I/O innecesario
│       ├── cache_memoria.py       # DataFrames procesados en RAM
│       ├── analisis.py            # Ridge, Kalman, espectro, robustez
│       └── serializacion.py       # numpy -> JSON/Float32
└── tests/                    # 86 tests
```

## Uso — Etapa 1 (pipeline offline)

Genera datos simulados, corre el pipeline completo y escribe el reporte:

```bash
python main.py
```

Procesa un CSV existente (busca `<nombre>_verdad.csv` al lado para validar):

```bash
python main.py --entrada data/raw/sim_42.csv
```

Opciones: `--config`, `--salida`, `--semilla`, `-v`.

## Uso — Etapa 2 (backend)

Levanta la API en local:

```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

- Documentación interactiva (Swagger): <http://127.0.0.1:8000/docs>
- Sonda de vida: <http://127.0.0.1:8000/health>

> Cuando exista `frontend/dist`, `backend/app.py` la monta automáticamente en `/`
> y la aplicación web queda servida por este mismo proceso.

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
| `GET /api/config` | Configuración activa en JSON. |
| `POST /api/config` | Aplica overrides anidados sobre `config.yaml`. |
| `DELETE /api/config` | Restablece a los valores de fábrica. |
| `GET /api/config/exportar` | Descarga la configuración como YAML interoperable con `main.py`. |

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

> El **replay** no vive en el backend: sobre una sesión grabada el frontend ya tiene las muestras
> en un `Float32Array` y reproduce avanzando un cursor. El streaming a 100 Hz se añadirá en la
> Etapa 3, cuando el dato nazca en el servidor.

## Pruebas

```bash
python -m pytest -q
```

**86 tests** en verde. Cobertura por área:

| Fichero | Qué cubre |
|---|---|
| `tests/test_limpieza.py`, `test_features.py`, `test_etiquetas.py`, `test_modelo.py`, `test_evaluacion.py`, `test_generador.py`, `test_reporte.py`, `test_pipeline.py` | Etapa 1 (53 tests). |
| `tests/test_api_rest.py` | Endpoints REST: arrays alineados, downsampling, crudo vs. limpio, 404/400/422, subida de CSV, robustez, stint, reset de config. |
| `tests/test_api_ws.py` | WebSocket: control, tramas binarias. |
| `tests/test_coherencia_api.py` | La API reproduce **exactamente** el pipeline de `main.py` (Ridge por CV y Kalman con los Q/R de `config.yaml`), el PSD de Welch y los MAE de referencia de `sim_42.csv`. |
| `tests/test_rendimiento.py` | Latencia y tramas contra un servidor **`uvicorn` real** (el `TestClient` no mide red). |

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
| **F1. Simulada** | `sim/generador.py` (código propio) | Sí, por construcción | Usada en Etapa 1 y 2 |
| **F2. Live Telemetry** | App de AC que guarda logs CSV por rueda | Sí (`Tire wear %`) | Extensión opcional (Etapa 2) |
| **F3. Logger propio** | Script Python sobre la memoria compartida de AC | No (solo proxy) | Etapa 3 |
| **F4. Datasets públicos** | Vueltas de AC en Hugging Face (parquet) | No | Pruebas de limpieza |

En las Etapas 1 y 2 se usa **solo F1** (datos propios, sin licencia externa). El
alcance obligatorio de la Etapa 2 es F1 + drag & drop de CSV; F2 y F4 requieren un
**adaptador de esquema** (mapeo de columnas al contrato) y quedan como extensión
opcional. Hay que **revisar la licencia de cada dataset** antes de publicar
resultados (el dataset de Silverstone GP es MIT). Detalle en `plan_etapa1.md`, §2.

## Esquema de datos

Cualquier fuente (F1…F4) debe producir estas columnas (el contrato está en
`src/config.py`; el backend lo **valida** al cargar):

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
verdadera, casi sin ruido) y se reporta la sensibilidad a R en el HTML.

## Pendiente de la Etapa 2

El backend está completo y probado; falta la capa de interfaz y la distribución:

- [ ] **Frontend** (`frontend/`, Vite + uPlot): Vistas 1 (telemetría cruda vs. limpia),
      3 (predicción y bandas), 4 (laboratorio de parámetros), y luego 5, 2 y 6.
- [ ] **App de escritorio** (`desktop.py` con pywebview) y scripts `.bat`.
- [ ] **Empaquetado** a `.exe` (`TelemetryAnalytics.spec`) y validación a 60 FPS con 360k muestras.
- [ ] **Replay** (Vista 6): el frontend lo reproduce en local sobre las muestras ya recibidas.
      El streaming servidor→cliente a 100 Hz se implementará en la **Etapa 3**, cuando el dato
      nazca en el servidor (captura en vivo).

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
