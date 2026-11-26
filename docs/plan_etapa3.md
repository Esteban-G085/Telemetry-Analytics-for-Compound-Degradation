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
| D4 | Frecuencia de muestreo | **Captura ≈333 Hz (`fs_original`); bus a 100 Hz (`fs_salida`)** | La física de AC se actualiza a ~333 Hz; el pipeline (features, Welch) está diseñado a 100 Hz. Se decima con un **acumulador temporal sobre los `timestamp_s` reales** para respetar el jitter medido, no el `dt` nominal. |
| D5 | Acondicionamiento causal | **Outliers mediana/MAD causal + IIR Butterworth SOS (20 Hz) muestra a muestra + decimación** | En vivo no hay futuro. El detector causal sustituye el pico por un *zero-order hold* y marca la salida como no válida; el IIR conserva su estado entre llamadas (forma II traspuesta, escalar y rápida) y arranca con `sosfilt_zi` para no subir desde 0. |
| D6 | Degradación en vivo | **`tyreWear` (grip) normalizado contra el máximo observado en la captura** | En AC1 `tyreWear[4]` es una señal de **agarre/salud** (no monótona): al calentar sube y al degradarse baja. Se normaliza `(pico − grip)/pico` y se limita a `[0,1]`. El pico es el **máximo visto** (no un P95) y no se reinicia por cambio de neumáticos; solo se limpia la historia cuando la vuelta retrocede (B10). **Sin grip utilizable la degradación queda en `NaN` (modo `none`)**; no cae al proxy de tiempos (D11). El pico robusto sigue pendiente en B1. |
| D7 | Registro de la captura | **`LoggerVivo`: `<nombre>.csv` **crudo** (esquema + `packetId`/`grip_*`/`degradacion`)** | El logger se suscribe a la fuente **antes** del acondicionador, así el CSV es reprocesable en batch sin doble filtrado. No escribe un `_verdad.csv` aparte: la verdad se recalcula en batch desde el propio CSV. El modo seco sí **lee** un `<nombre>_verdad.csv` si ya existe al lado del archivo reproducido. |
| D8 | Transporte a la GUI | **WebSocket `/api/vivo/stream` empujando JSON a ~10 Hz (`fps_ws`)** | Más rápido que lo que el ojo necesita y mucho más barato que empujar cada muestra de 100 Hz. La ventana se reenvía completa (200 puntos, 2 s) y el cliente solo repinta. |
| D9 | Vista de la interfaz | **Vista 7 «En vivo»** | La GUI ya tenía 6 pestañas (la 6 es Replay, que reproduce en local). La captura servidor→cliente merece la suya propia. |
| D10 | App local | `python -m telemetria` (o `ejecutar_app.bat`) abre la **GUI nativa PySide6** | Se retiró el lanzador de navegador: la app es una ventana de escritorio con `QNetworkAccessManager` y `QWebSocket`, sin frontend Vite/uPlot ni WebView2. |
| D11 | Fallback sin grip | **Dejar la degradación en `NaN` (modo `none`); no caer al proxy de tiempos** | El proxy de tiempos y la degradación por grip no son comparables; mezclarlos engaña. Se expone la ausencia de etiqueta en vez de un valor inventado (decisión de la revisión, A3). |
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
│        ├─ degradación desde grip / columna inyectada                     │
│        └─ predicción Kalman (telemetria/pipeline/modelo.py)                              │
│   LoggerVivo  ──>  data/vivo/<nombre>.csv  (crudo; sin _verdad.csv)      │
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
  `FuenteVivo` cuenta los `packetId` **salteados** (`paquetes_perdidos`, B2) y mide
  la frecuencia real de captura (`fs_medida`); la memoria se cierra desde el propio
  hilo de captura (`_limpiar`), no desde otro hilo (D2).
- `Fuente.esperar_arranque(timeout)`: confirma que `_preparar` terminó (o falló)
  antes de dar la captura por activa (B6).
- **Nota (D3, confirmada):** el `timestamp_s` de AC es **de lectura**, no del tick de
  física: `FuenteVivo._siguiente` pasa `ciclo = time.perf_counter() - t0` y
  `MemoriaAC.leer_muestra` usa `perf_counter` por defecto. Es lo correcto para una
  captura de un solo hilo, pero el jitter incluye el *scheduling* del SO; `fs_medida`
  lo refleja.

### 3.2 Acondicionador causal (`telemetria/adquisicion/acondicionador.py`)

- Detección de outliers **causal** por mediana/MAD en ventana deslizante (misma
  idea que `limpieza.detectar_outliers`, sin futuro), con recálculo periódico de
  las estadísticas para no penalizar el *throughput*.
- Cobertura alineada con el batch: **outliers** en `canales_fisicos()` (incluye
  `speed_kmh`) y **filtro** en `canales_filtrables()`.
- IIR Butterworth SOS de orden 4 a 20 Hz, aplicado muestra a muestra con
  recurrencia directa (forma II traspuesta) e inicializado con `sosfilt_zi` en la
  primera muestra de cada canal.
- Decimación por **acumulador temporal sobre los timestamps reales** (~333 Hz a
  100 Hz), con el `dt` nominal como respaldo.
- **Nota (B8):** la banda «alta» (15–40 Hz) cae en la **transición** del Butterworth
  a 20 Hz (≈ −0.4 dB a 15 Hz, −3 dB a 20 Hz, −14 dB a 30 Hz). Su potencia depende de
  `corte_hz`: cambiar el corte cambia el significado de la feature sin aviso, así que
  `bandas_hz.alta` y `limpieza.filtro.corte_hz` no deben moverse por separado
  (comentado en `config.yaml`).

### 3.3 Motor en vivo (`telemetria/adquisicion/motor_vivo.py`, `telemetria/api/servicios/vivo.py`)

- `MotorVivo`: mantiene la ventana reciente en un `DataFrame`, calcula las features
  con `features_ventana`, estima la **degradación agregada** desde el grip
  (`(pico observado − grip)/pico`, con la media de las cuatro ruedas) o desde la
  columna `degradacion` inyectada en modo seco, y proyecta esa media con
  `KalmanDegradacion` las próximas `vivo.anticipacion_vueltas` vueltas. Sin grip y
  sin columna inyectada la degradación queda en `NaN` (modo `none`, D11). No hay
  predicción por rueda ni `R` ampliado para la vuelta parcial (B4 pendiente), y
  `_predecir` vuelve a filtrar la serie completa en cada `estado()` (B5
  pendiente, aunque `KalmanDegradacion` ya expone `paso`). Si la vuelta retrocede
  (nueva sesión) se reinicia el *stint* en vez de sobrescribir la historia (B10) y
  el Welch en vivo interpola los huecos internos en lugar de concatenar muestras
  separadas (B9). El pico robusto P95 y el reinicio por cambio de neumáticos
  siguen pendientes (B1).
- `LoggerVivo`: se suscribe **antes** del acondicionador (`Fuente.suscribir_crudo`)
  y vuelca el CSV **crudo** (esquema + `packetId`/`grip_*`/`degradacion`) en
  `data/vivo/`. No genera `_verdad.csv`: la verdad se recalcula en batch desde el
  propio CSV. El archivo se crea **perezosamente** en el primer registro (B6) y
  las escrituras tras `cerrar()` se ignoran en lugar de lanzar (B11).
- `VivoSesion`: orquesta fuente + acondicionador + bus + motor + logger, con
  `iniciar` / `detener` / `estado` / `ventana` / `listar`. Un CSV inválido no
  detiene la captura en curso (B6) y `estado` expone `paquetes_perdidos`,
  `fs_medida` y `errores_subs` (B2/B3).

### 3.4 Vista 7 «En vivo» (`telemetria/gui/vistas/v_vivo.py`)

- Selector de fuente (`seco` / `ac`), selector de CSV y botones **Iniciar** /
  **Detener** captura. El panel muestra el estado del motor, el diagnóstico de la
  captura (`paquetes_perdidos`, `fs_medida`, `errores_subs`, B2/B3) y el
  diagnóstico de la memoria de AC.
- **Osciloscopio** en tiempo real sobre `/api/vivo/stream`, con cursor y
  navegación de la ventana.
- El estado muestra la degradación por rueda y su media agregada junto al modo
  (`verdad` o `none`); la predicción con Kalman es agregada. No hay semáforo por
  rueda ni proyección final por rueda (B4 pendiente).
- **Predicción** de las próximas vueltas sobre la media, con la banda de
  incertidumbre de Kalman.

### 3.5 App local (`telemetria/cli.py`, `telemetria/gui/main.py`, `ejecutar_app.bat`)

- `python -m telemetria` (o `python -m telemetria gui`) abre la GUI nativa
  PySide6 con el backend embebido. El subcomando `app` del lanzador de navegador
  se retiró; el cliente usa `QNetworkAccessManager` y `QWebSocket`.
- `python -m telemetria pipeline` ejecuta el pipeline offline de la Etapa 1.
- `ejecutar_app.bat` (doble clic) abre la misma GUI.

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
`{"canales": [...], "n": 200}` o `{"tipo":"ping"}`.

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
      (esquema exacto + extras); el logger no genera `_verdad.csv`.
- [x] La ruta viva es coherente con el batch (D13/D14): correlación > 0.97 por
      canal en `speed_kmh`, `wheel_slip_fl`, `temp_core_c_fl`, `wheel_load_n_fl`.
- [x] El WebSocket emite tramas `tipo:"vivo"` con ventana, degradación y predicción.
- [x] `python -m telemetria` levanta el backend integrado y abre la GUI nativa
      PySide6 (no hay frontend compilado ni navegador).
- [x] Suite completa en verde (**200 tests** de Python).
- [x] Tests de humo de la GUI (**43 tests**, `offscreen`) y extras de la Etapa 2
      §3.2 (dispersión/correlación) y §3.5 (fallo de sensores) cerrados.
- [ ] Validación visual fluida con ventanas largas (requiere la GUI con pantalla
      visible; no se cuenta como hecha con los tests `offscreen`).

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
9. **El CSV crudo no era reprocesable en batch.** Al abrir el logger a la fila cruda
   (A1/A5) aparecieron columnas extra (`packetId`, `grip_*`, `degradacion`), a menudo
   vacías: `interpolar_huecos` las incluía al calcular `valido` y marcaba **todas** las
   muestras como inválidas. La validez pasó a depender solo de las columnas del
   esquema (`columnas_esquema()`), de forma que una captura cruda atraviesa
   `limpieza.preprocesar` (test `test_captura_cruda_reprocesable_en_batch`). Esto
   cierra además la hipótesis **D4**: la captura es cruda, así que el batch aplica
   **un solo filtro** (ya no el −6 dB del doble filtrado).
10. **B5/B9/B10 (avance parcial).** `KalmanDegradacion` expone `paso`, pero
    `MotorVivo._predecir` todavía refiltra la serie completa en cada `estado()`:
    el filtro **incremental**, la predicción por rueda y el `R` ampliado en la
    vuelta parcial (B4/B5) siguen pendientes. Sí están `bus.ultimas` con `islice`
    (B5), el Welch en vivo con interpolación de huecos internos (B9) y el
    reinicio del *stint* al retroceder la vuelta (B10).

## 8. Fuera de alcance (Etapa 4)

- Adaptadores de esquema para **ACC / AC Evo** y datasets públicos (F2/F4).
- Apps Lua de AC vía **CSP** como fuente alternativa.
- Soporte de **Proton/Wine** o macOS.
- Gráficas 3D y análisis de trayectoria.
