# Plan Etapa 3: Captura en tiempo real desde Assetto Corsa

Proyecto: predicción de degradación de neumáticos con telemetría de Assetto Corsa
(AC).

**Objetivo de la Etapa 3:** conectar el sistema a una sesión real de AC, leer la
telemetría desde su **memoria compartida**, acondicionarla de forma **estrictamente
causal** (sin mirar el futuro), estimar la degradación y proyectarla unas vueltas
hacia adelante **mientras se conduce**, todo servido por el mismo dashboard de la
Etapa 2 (nueva **Vista 7 «En vivo»**) y ejecutable como **app local (navegador)**. La
fuente de datos de esta etapa es la **F3 (logger propio)**, que convive con el
generador F1 (usado como **modo seco** para desarrollar sin AC en pista).

> **Continuidad:** la Etapa 1 dejó las features calculables **por ventana** y el
> filtro **causal con estado**; la Etapa 2 dejó el WebSocket y el montaje de
> estáticos. La Etapa 3 solo añade el *origen* del dato (memoria de AC), el
> acondicionador muestra-a-muestra y un motor en ventana deslizante; reutiliza
> `telemetria/pipeline` sin reescribir la ciencia.

---

## 0. Hoja de ruta del proyecto

- **Etapa 1: Pipeline offline (F1).** Limpieza, features, Ridge y Kalman sobre CSV.
  *(Estado: Implementada y probada)*
- **Etapa 2: Dashboard interactivo y app local (navegador) (F1).** Backend REST +
  WebSocket, frontend Canvas/uPlot, laboratorio de parámetros, espectro, robustez,
  replay y distribución. *(Estado: Implementada; extras §3.2/§3.5 del plan de la
  Etapa 2 quedan como opcionales)*
- **Etapa 3: Tiempo real (F3).** Captura desde la memoria compartida de AC,
  acondicionamiento causal, motor en vivo, Vista 7 y app local (navegador).

---

## 1. Decisiones fijadas (precondiciones)

| # | Decisión | Valor por defecto | Por qué / cuándo revisarlo |
|---|---|---|---|
| D1 | Vía de captura de AC | **Memoria compartida nativa (`Local\acpmf_physics`, `acpmf_graphics`, `acpmf_static`)** | Es el mecanismo oficial de AC/CM, en modo lectura, y no depende de CSP. Las apps Lua de AC requieren CSP, corren en el hilo de render y son malas capturadoras: quedan como **extra opcional de Etapa 4**. |
| D2 | Acceso a la memoria | **API de Win32 con `ctypes` (`OpenFileMappingW` + `MapViewOfFile` con `FILE_MAP_READ`)** | `mmap.mmap(tagname=...)` **crea** la sección si no existe (imposible distinguir «AC apagado» de «sección vacía») y `from_buffer` exige un buffer escribible. La API de Win32 falla limpio cuando AC no está en pista y permite leer en solo-lectura. |
| D3 | Fuente de datos | **F3 (logger propio) para el vivo; F1 como «modo seco»** | El modo seco reproduce un CSV por **la misma ruta de código** que el dato real, así que sirve para desarrollar y para los tests sin depender de AC. |
| D4 | Frecuencia de muestreo | **Captura ≈333 Hz (`fs_original`); bus a 100 Hz (`fs_salida`)** | La física de AC se actualiza a ~333 Hz; el pipeline (features, Welch) está diseñado a 100 Hz. Se decima con un **acumulador temporal** para respetar jitter. |
| D5 | Acondicionamiento causal | **Outliers mediana/MAD causal + IIR Butterworth SOS (20 Hz) muestra a muestra + decimación** | En vivo no hay futuro. El detector causal sustituye el pico por un *zero-order hold* y marca la salida como no válida; el IIR conserva su estado entre llamadas (forma II traspuesta, escalar y rápida). |
| D6 | Degradación en vivo | **`tyreWear` (grip) auto-calibrado contra su pico; fallback al proxy** | En AC1 `tyreWear[4]` es una señal de **agarre/salud** (no monótona): al calentar sube y al degradarse baja. Se normaliza `(pico − grip)/pico` y se limita a `[0,1]`; si no hay grip utilizable, cae al proxy de tiempos como en la Etapa 1. |
| D7 | Registro de la captura | **`LoggerVivo`: `<nombre>.csv` con el esquema del proyecto + `<nombre>_verdad.csv`** | Permite volver a procesar una captura con el pipeline batch (y comparar contra la verdad si la fuente la trae). |
| D8 | Transporte al frontend | **WebSocket `/api/vivo/stream` empujando JSON a ~10 Hz (`fps_ws`)** | Más rápido que lo que el ojo necesita y mucho más barato que empujar cada muestra de 100 Hz. La ventana se reenvía completa (600 puntos) y el cliente solo repinta. |
| D9 | Vista de la interfaz | **Vista 7 «En vivo»** | El frontend ya tenía 6 vistas (la 6 es Replay, que reproduce en local). La captura servidor→cliente merece su propia pestaña. |
| D10 | App local | Lanzador `telemetria/api/lanzador.py` (`python -m telemetria`) que levanta uvicorn y abre el navegador | Simple, sin dependencias adicionales de GUI** | Se puede usar como app nativa (WebView2) o como servidor local para una segunda pantalla/tablet, sin añadir dependencias de GUI. |
| D12 | Desacople fuente↔motor | **`BusTiempoReal` (buffer circular en RAM)** | La fuente (hilo) publica; el motor y el WS leen. Evita acoplar la captura de AC al consumo del frontend. |
| D13 | Criterio de corrección live-vs-batch | **Correlación > 0.97 por canal y error relativo < 0.2** | El objetivo no es igualdad bit a bit (el batch remuestrea con `resample_poly` y usa otra inicialización del filtro), sino que la señal en vivo sea **coherente** con la del pipeline offline. |
| D14 | Prueba de coherencia | **`tests/test_coherencia_live_batch.py`** | Reproduce un CSV crudo por la ruta viva y lo compara con `limpieza.preprocesar`; fija el criterio D13 como test de regresión. |

---

## 2. Arquitectura y flujo de comunicación

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        ASSETTO CORSA (proceso del juego)                 │
│   Local\acpmf_physics  ·  Local\acpmf_graphics  ·  Local\acpmf_static    │
└───────────────────────────────────▲──────────────────────────────────────┘
                                    │ OpenFileMappingW + MapViewOfFile (READ)
                                    │ ~333 Hz
┌───────────────────────────────────┴──────────────────────────────────────┐
│                          BACKEND (Python / FastAPI)                      │
│                                                                          │
│   FuenteVivo (telemetria/adquisicion/ac_info.py + telemetria/adquisicion/fuentes.py)                           │
│        └─> fila cruda (dict con el esquema del proyecto)                 │
│   AcondicionadorCausal (telemetria/adquisicion/acondicionador.py)                           │
│        └─> outliers causales + IIR SOS 20 Hz + decimación 100 Hz         │
│   BusTiempoReal  ──>  MotorVivo (telemetria/adquisicion/motor_vivo.py)                      │
│        ├─ features en ventana deslizante (telemetria/pipeline/features.py)               │
│        ├─ degradación desde grip auto-calibrado / columna inyectada      │
│        └─ predicción Kalman (telemetria/pipeline/modelo.py)                              │
│   LoggerVivo  ──>  data/vivo/<nombre>.csv  (+ _verdad.csv)               │
│                                                                          │
│   REST: /api/vivo/{iniciar,detener,estado,ventana,sesiones,layout}       │
│   WS:   /api/vivo/stream  (push JSON ~10 Hz)                            │
└───────────────────────────────────▲──────────────────────────────────────┘
                                    │ REST + WebSocket
┌───────────────────────────────────┴──────────────────────────────────────┐
│   Vista 7 «En vivo»: osciloscopio · espectro · planta 2×2 · predicción   │
└──────────────────────────────────────────────────────────────────────────┘
```

El **modo seco** sustituye `FuenteVivo` por `FuenteCSV`, que entrega las filas de
un CSV a ritmo real (o a máxima velocidad en tests) por el mismo
`AcondicionadorCausal` y el mismo `MotorVivo`.

---

## 3. Módulos

### 3.1 Logger y lectura de memoria (`telemetria/adquisicion/ac_info.py`, `telemetria/adquisicion/fuentes.py`)

- `SPageFilePhysics` (`packetId`, `gas`, `brake`, `steerAngle`, `speedKmh`,
  `wheelSlip[4]`, `wheelLoad[4]`, `wheelsPressure[4]`, `tyreWear[4]`,
  `tyreDirtyLevel[4]`, `tyreCoreTemperature[4]`, …; `sizeof = 168`),
  `SPageFileGraphics` (`completedLaps`, …; `sizeof = 84`) y `SPageFileStatic`.
- `MemoriaAC.abrir()` / `.cerrar()` / `.leer_muestra()` con la API de Win32.
  `disponible` es `False` (con `error` explicativo) cuando AC no está publicando.
- `verificar_layout()` devuelve un diagnóstico (tamaños + `packetId`) para
  `GET /api/vivo/layout`.
- `Fuente` (hilo base), `FuenteVivo` (memoria de AC) y `FuenteCSV` (modo seco).

### 3.2 Acondicionador causal (`telemetria/adquisicion/acondicionador.py`)

- Detección de outliers **causal** por mediana/MAD en ventana deslizante (misma
  idea que `limpieza.detectar_outliers`, sin futuro), con recálculo periódico de
  las estadísticas para no penalizar el *throughput*.
- Cobertura alineada con el batch: **outliers** en `canales_fisicos()` (incluye
  `speed_kmh`) y **filtro** en `canales_filtrables()`.
- IIR Butterworth SOS de orden 4 a 20 Hz, aplicado muestra a muestra con
  recurrencia directa (forma II traspuesta).
- Decimación por **acumulador temporal** de ~333 Hz a 100 Hz.

### 3.3 Motor en vivo (`telemetria/adquisicion/motor_vivo.py`, `telemetria/api/servicios/vivo.py`)

- `MotorVivo`: mantiene la ventana reciente en un `DataFrame`, calcula las features
  con `features_ventana`, estima la degradación por rueda y proyecta con
  `KalmanDegradacion` las próximas `vivo.anticipacion_vueltas` vueltas.
- `LoggerVivo`: vuelca el esquema + la verdad a `data/vivo/`.
- `VivoSesion`: orquesta fuente + acondicionador + bus + motor + logger, con
  `iniciar` / `detener` / `estado` / `ventana` / `listar`.

### 3.4 Vista 7 «En vivo» (`frontend/src/vistas/v_vivo.js`)

- Selector de fuente (`ac` / `seco`), CSV y ritmo (tiempo real / máxima velocidad);
  botones **Iniciar** / **Detener**; *pills* de estado del WebSocket y de la captura.
- **Osciloscopio**: canal y rueda seleccionables (slip, temperatura, carga,
  presión o velocidad), ventana deslizante de 6 s.
- **Espectro en vivo** de la ventana y **planta 2×2** con el semáforo de
  degradación por rueda y el grip asociado.
- **Predicción** de las próximas vueltas con su intervalo.

### 3.5 app local (navegador) (`telemetria/api/lanzador.py`, `ejecutar_app.bat`)

- `telemetria/api/lanzador.py` (vía `python -m telemetria app`): arranca `uvicorn`
  en un hilo, espera `/health`, opcionalmente inicia la captura (`--modo ac|seco`)
  y abre el navegador por defecto.
- `ejecutar_app.bat` (doble clic).

---

## 4. Backend

### REST

| Método y ruta | Para qué |
|---|---|
| `POST /api/vivo/iniciar` | Arranca la captura (`fuente`, `archivo`, `ritmo_hz`, `bucle`). |
| `POST /api/vivo/detener` | Detiene y cierra el CSV. |
| `GET /api/vivo/estado` | Muestras, vuelta, grip, degradación, predicción, ruta del CSV, errores. |
| `GET /api/vivo/ventana` | Ventana deslizante (`canales`, `n`). |
| `GET /api/vivo/sesiones` | Capturas de `data/vivo/`. |
| `GET /api/vivo/layout` | Diagnóstico de la memoria de AC. |

### WebSocket `/api/vivo/stream`

El servidor empuja `{tipo:"vivo", …}` cada ~100 ms; el cliente puede pedir
`{"canales": [...], "n": 600}` o `{"tipo":"ping"}`.

---

## 5. Mapeo AC → esquema del proyecto

| AC1 | Esquema | Nota |
|---|---|---|
| `speedKmh` | `speed_kmh` | directo |
| `gas` / `brake` / `steerAngle` | `throttle` / `brake` / `steering` | `steering` normalizado y acotado |
| `tyreCoreTemperature[i]` | `temp_core_c_*` | índice `0=FL,1=FR,2=RL,3=RR` |
| `wheelsPressure[i]` | `pressure_psi_*` | directo |
| `wheelSlip[i]` | `wheel_slip_*` | directo |
| `wheelLoad[i]` | `wheel_load_n_*` | directo |
| `tyreDirtyLevel[i]` | `dirty_level_*` | ÷10 |
| `graphics.completedLaps + 1` | `lap` | 1-based |
| `tyreWear[i]` | `grip_<rueda>` (extra) | señal de agarre, **fuera** del esquema |
| — | `degradacion` | de la verdad (modo seco) o derivada del grip |

---

## 6. Criterios de aceptación

- [x] Sin AC en pista, `MemoriaAC` no crashea y `GET /api/vivo/layout` responde
      `disponible: false` con un mensaje claro.
- [x] El modo seco reproduce un CSV por la ruta viva y registra `<nombre>.csv`
      (esquema exacto) + `<nombre>_verdad.csv`.
- [x] La ruta viva es coherente con el batch (D13/D14): correlación > 0.97 por
      canal en `speed_kmh`, `wheel_slip_fl`, `temp_core_c_fl`, `wheel_load_n_fl`.
- [x] El WebSocket emite tramas `tipo:"vivo"` con ventana, degradación y predicción.
- [x] `python -m telemetria` levanta el backend, arranca la captura y sirve el
      frontend compilado (abre el navegador por defecto).
- [x] Suite completa en verde (**123 tests** de Python).
- [x] Tests de montaje del frontend (**8 tests**, Vitest + jsdom) y extras de la
      Etapa 2 §3.2 (dispersión/correlación) y §3.5 (fallo de sensores) cerrados.
- [ ] Validación visual a 60 FPS con 360k muestras (requiere navegador visible).

---

## 7. Registro de implementación (desviaciones respecto al plan previo)

1. **`mmap` → API de Win32.** El borrador usaba `mmap` con `tagname`; se cambió a
   `OpenFileMappingW`/`MapViewOfFile` porque `mmap` crea la sección si no existe
   (no distingue «AC apagado») y porque `from_buffer` exige un buffer escribible.
2. **Vista 7, no 6.** El frontend ya tenía seis vistas; la de captura es la **7**.
3. **Cobertura de outliers ampliada.** Detectado al escribir D14: el generador
   inyecta picos en **cualquier** columna (incluida `speed_kmh`) y el batch limpia
   `canales_fisicos()`. El acondicionador se alineó (outliers en `canales_fisicos`,
   filtro en `canales_filtrables`); sin esto, la correlación caía a ~0.55 por los
   picos gigantes en la velocidad.
4. **Filtro escalar.** El `sosfilt` de SciPy por muestra era demasiado lento
   (~2,2 M llamadas por stint): se sustituyó por la recurrencia directa escalar.
5. **`FuenteCSV` con registros.** `df.iloc[i]` por fila limitaba a ~1350 muestras/s;
   iterar `to_dict("records")` sube a ~1700 muestras/s (el tiempo real necesita 100).
6. **La traza batch tiene un retardo de grupo.** `resample_poly` es un FIR de fase
   lineal y `_resample_poly_df` no compensa su retardo; el residuo medido en vivo es
   de ~10–20 ms. Se documenta en D13/D14 y no se «arregla» para no tocar el batch.
7. **Extras de la Etapa 2 cerrados aquí.** §3.2 (dispersión/correlación de features,
   Vista 2) y §3.5 (simulador de fallo de sensores, Vista 5) se implementaron junto
   con la Etapa 3 porque reutilizan la misma sesión procesada y el mismo Ridge. El
   fallo de presión es **inocuo** a propósito: `pressure_psi` no alimenta ninguna
   feature, y el panel lo evidencia.
8. **Tests del frontend.** Se añadió Vitest + jsdom (`frontend/vitest.config.js`,
   `frontend/tests/`) para el *test de montaje*: las 7 vistas se montan, rellenan su
   contenedor y limpian sin tocar la red. Queda fuera la validación de 60 FPS
   (necesita un navegador real con canvas).

## 8. Fuera de alcance (Etapa 4)

- Adaptadores de esquema para **ACC / AC Evo** y datasets públicos (F2/F4).
- Apps Lua de AC vía **CSP** como fuente alternativa.
- Soporte de **Proton/Wine** o macOS.
- Gráficas 3D y análisis de trayectoria.
