# Plan Etapa 3: Captura en tiempo real desde Assetto Corsa

Proyecto: predicciÃ³n de degradaciÃ³n de neumÃ¡ticos con telemetrÃ­a de Assetto Corsa
(AC).

**Objetivo de la Etapa 3:** conectar el sistema a una sesiÃ³n real de AC, leer la
telemetrÃ­a desde su **memoria compartida**, acondicionarla de forma **estrictamente
causal** (sin mirar el futuro), estimar la degradaciÃ³n y proyectarla unas vueltas
hacia adelante **mientras se conduce**, todo servido por el mismo dashboard de la
Etapa 2 (nueva **Vista 7 Â«En vivoÂ»**) y ejecutable como **app local (navegador)**. La
fuente de datos de esta etapa es la **F3 (logger propio)**, que convive con el
generador F1 (usado como **modo seco** para desarrollar sin AC en pista).

> **Continuidad:** la Etapa 1 dejÃ³ las features calculables **por ventana** y el
> filtro **causal con estado**; la Etapa 2 dejÃ³ el WebSocket y el montaje de
> estÃ¡ticos. La Etapa 3 solo aÃ±ade el *origen* del dato (memoria de AC), el
> acondicionador muestra-a-muestra y un motor en ventana deslizante; reutiliza
> `src/` sin reescribir la ciencia.

---

## 0. Hoja de ruta del proyecto

- **Etapa 1: Pipeline offline (F1).** Limpieza, features, Ridge y Kalman sobre CSV.
  *(Estado: Implementada y probada)*
- **Etapa 2: Dashboard interactivo y app local (navegador) (F1).** Backend REST +
  WebSocket, frontend Canvas/uPlot, laboratorio de parÃ¡metros, espectro, robustez,
  replay y distribuciÃ³n. *(Estado: Implementada; extras Â§3.2/Â§3.5 del plan de la
  Etapa 2 quedan como opcionales)*
- **Etapa 3: Tiempo real (F3).** Captura desde la memoria compartida de AC,
  acondicionamiento causal, motor en vivo, Vista 7 y app local (navegador).

---

## 1. Decisiones fijadas (precondiciones)

| # | DecisiÃ³n | Valor por defecto | Por quÃ© / cuÃ¡ndo revisarlo |
|---|---|---|---|
| D1 | VÃ­a de captura de AC | **Memoria compartida nativa (`Local\acpmf_physics`, `acpmf_graphics`, `acpmf_static`)** | Es el mecanismo oficial de AC/CM, en modo lectura, y no depende de CSP. Las apps Lua de AC requieren CSP, corren en el hilo de render y son malas capturadoras: quedan como **extra opcional de Etapa 4**. |
| D2 | Acceso a la memoria | **API de Win32 con `ctypes` (`OpenFileMappingW` + `MapViewOfFile` con `FILE_MAP_READ`)** | `mmap.mmap(tagname=...)` **crea** la secciÃ³n si no existe (imposible distinguir Â«AC apagadoÂ» de Â«secciÃ³n vacÃ­aÂ») y `from_buffer` exige un buffer escribible. La API de Win32 falla limpio cuando AC no estÃ¡ en pista y permite leer en solo-lectura. |
| D3 | Fuente de datos | **F3 (logger propio) para el vivo; F1 como Â«modo secoÂ»** | El modo seco reproduce un CSV por **la misma ruta de cÃ³digo** que el dato real, asÃ­ que sirve para desarrollar y para los tests sin depender de AC. |
| D4 | Frecuencia de muestreo | **Captura â‰ˆ333 Hz (`fs_original`); bus a 100 Hz (`fs_salida`)** | La fÃ­sica de AC se actualiza a ~333 Hz; el pipeline (features, Welch) estÃ¡ diseÃ±ado a 100 Hz. Se decima con un **acumulador temporal** para respetar jitter. |
| D5 | Acondicionamiento causal | **Outliers mediana/MAD causal + IIR Butterworth SOS (20 Hz) muestra a muestra + decimaciÃ³n** | En vivo no hay futuro. El detector causal sustituye el pico por un *zero-order hold* y marca la salida como no vÃ¡lida; el IIR conserva su estado entre llamadas (forma II traspuesta, escalar y rÃ¡pida). |
| D6 | DegradaciÃ³n en vivo | **`tyreWear` (grip) auto-calibrado contra su pico; fallback al proxy** | En AC1 `tyreWear[4]` es una seÃ±al de **agarre/salud** (no monÃ³tona): al calentar sube y al degradarse baja. Se normaliza `(pico âˆ’ grip)/pico` y se limita a `[0,1]`; si no hay grip utilizable, cae al proxy de tiempos como en la Etapa 1. |
| D7 | Registro de la captura | **`LoggerVivo`: `<nombre>.csv` con el esquema del proyecto + `<nombre>_verdad.csv`** | Permite volver a procesar una captura con el pipeline batch (y comparar contra la verdad si la fuente la trae). |
| D8 | Transporte al frontend | **WebSocket `/api/vivo/stream` empujando JSON a ~10 Hz (`fps_ws`)** | MÃ¡s rÃ¡pido que lo que el ojo necesita y mucho mÃ¡s barato que empujar cada muestra de 100 Hz. La ventana se reenvÃ­a completa (600 puntos) y el cliente solo repinta. |
| D9 | Vista de la interfaz | **Vista 7 Â«En vivoÂ»** | El frontend ya tenÃ­a 6 vistas (la 6 es Replay, que reproduce en local). La captura servidorâ†’cliente merece su propia pestaÃ±a. |
| D10 | App local | Lanzador `desktop.py` que levanta uvicorn y abre el navegador | Simple, sin dependencias adicionales de GUI** | Se puede usar como app nativa (WebView2) o como servidor local para una segunda pantalla/tablet, sin depender de que `pywebview` estÃ© instalado. |
| D12 | Desacople fuenteâ†”motor | **`BusTiempoReal` (buffer circular en RAM)** | La fuente (hilo) publica; el motor y el WS leen. Evita acoplar la captura de AC al consumo del frontend. |
| D13 | Criterio de correcciÃ³n live-vs-batch | **CorrelaciÃ³n > 0.97 por canal y error relativo < 0.2** | El objetivo no es igualdad bit a bit (el batch remuestrea con `resample_poly` y usa otra inicializaciÃ³n del filtro), sino que la seÃ±al en vivo sea **coherente** con la del pipeline offline. |
| D14 | Prueba de coherencia | **`tests/test_coherencia_live_batch.py`** | Reproduce un CSV crudo por la ruta viva y lo compara con `limpieza.preprocesar`; fija el criterio D13 como test de regresiÃ³n. |

---

## 2. Arquitectura y flujo de comunicaciÃ³n

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                        ASSETTO CORSA (proceso del juego)                 â”‚
â”‚   Local\acpmf_physics  Â·  Local\acpmf_graphics  Â·  Local\acpmf_static    â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–²â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                    â”‚ OpenFileMappingW + MapViewOfFile (READ)
                                    â”‚ ~333 Hz
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                          BACKEND (Python / FastAPI)                      â”‚
â”‚                                                                          â”‚
â”‚   FuenteVivo (sim/ac_info.py + sim/fuentes.py)                           â”‚
â”‚        â””â”€> fila cruda (dict con el esquema del proyecto)                 â”‚
â”‚   AcondicionadorCausal (sim/acondicionador.py)                           â”‚
â”‚        â””â”€> outliers causales + IIR SOS 20 Hz + decimaciÃ³n 100 Hz         â”‚
â”‚   BusTiempoReal  â”€â”€>  MotorVivo (sim/motor_vivo.py)                      â”‚
â”‚        â”œâ”€ features en ventana deslizante (src/features.py)               â”‚
â”‚        â”œâ”€ degradaciÃ³n desde grip auto-calibrado / columna inyectada      â”‚
â”‚        â””â”€ predicciÃ³n Kalman (src/modelo.py)                              â”‚
â”‚   LoggerVivo  â”€â”€>  data/vivo/<nombre>.csv  (+ _verdad.csv)               â”‚
â”‚                                                                          â”‚
â”‚   REST: /api/vivo/{iniciar,detener,estado,ventana,sesiones,layout}       â”‚
â”‚   WS:   /api/vivo/stream  (push JSON ~10 Hz)                            â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–²â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                    â”‚ REST + WebSocket
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚   Vista 7 Â«En vivoÂ»: osciloscopio Â· espectro Â· planta 2Ã—2 Â· predicciÃ³n   â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

El **modo seco** sustituye `FuenteVivo` por `FuenteCSV`, que entrega las filas de
un CSV a ritmo real (o a mÃ¡xima velocidad en tests) por el mismo
`AcondicionadorCausal` y el mismo `MotorVivo`.

---

## 3. MÃ³dulos

### 3.1 Logger y lectura de memoria (`sim/ac_info.py`, `sim/fuentes.py`)

- `SPageFilePhysics` (`packetId`, `gas`, `brake`, `steerAngle`, `speedKmh`,
  `wheelSlip[4]`, `wheelLoad[4]`, `wheelsPressure[4]`, `tyreWear[4]`,
  `tyreDirtyLevel[4]`, `tyreCoreTemperature[4]`, â€¦; `sizeof = 168`),
  `SPageFileGraphics` (`completedLaps`, â€¦; `sizeof = 84`) y `SPageFileStatic`.
- `MemoriaAC.abrir()` / `.cerrar()` / `.leer_muestra()` con la API de Win32.
  `disponible` es `False` (con `error` explicativo) cuando AC no estÃ¡ publicando.
- `verificar_layout()` devuelve un diagnÃ³stico (tamaÃ±os + `packetId`) para
  `GET /api/vivo/layout`.
- `Fuente` (hilo base), `FuenteVivo` (memoria de AC) y `FuenteCSV` (modo seco).

### 3.2 Acondicionador causal (`sim/acondicionador.py`)

- DetecciÃ³n de outliers **causal** por mediana/MAD en ventana deslizante (misma
  idea que `limpieza.detectar_outliers`, sin futuro), con recÃ¡lculo periÃ³dico de
  las estadÃ­sticas para no penalizar el *throughput*.
- Cobertura alineada con el batch: **outliers** en `canales_fisicos()` (incluye
  `speed_kmh`) y **filtro** en `canales_filtrables()`.
- IIR Butterworth SOS de orden 4 a 20 Hz, aplicado muestra a muestra con
  recurrencia directa (forma II traspuesta).
- DecimaciÃ³n por **acumulador temporal** de ~333 Hz a 100 Hz.

### 3.3 Motor en vivo (`sim/motor_vivo.py`, `backend/servicios/vivo.py`)

- `MotorVivo`: mantiene la ventana reciente en un `DataFrame`, calcula las features
  con `features_ventana`, estima la degradaciÃ³n por rueda y proyecta con
  `KalmanDegradacion` las prÃ³ximas `vivo.anticipacion_vueltas` vueltas.
- `LoggerVivo`: vuelca el esquema + la verdad a `data/vivo/`.
- `VivoSesion`: orquesta fuente + acondicionador + bus + motor + logger, con
  `iniciar` / `detener` / `estado` / `ventana` / `listar`.

### 3.4 Vista 7 Â«En vivoÂ» (`frontend/src/vistas/v_vivo.js`)

- Selector de fuente (`ac` / `seco`), CSV y ritmo (tiempo real / mÃ¡xima velocidad);
  botones **Iniciar** / **Detener**; *pills* de estado del WebSocket y de la captura.
- **Osciloscopio**: canal y rueda seleccionables (slip, temperatura, carga,
  presiÃ³n o velocidad), ventana deslizante de 6 s.
- **Espectro en vivo** de la ventana y **planta 2Ã—2** con el semÃ¡foro de
  degradaciÃ³n por rueda y el grip asociado.
- **PredicciÃ³n** de las prÃ³ximas vueltas con su intervalo.

### 3.5 app local (navegador) y empaquetado (`desktop.py`, `.bat`, `.spec`)

- `desktop.py`: arranca `uvicorn` en un hilo, espera `/health`, opcionalmente
  inicia la captura (`--modo ac|seco`) y abre `pywebview` (o el navegador).
- `ejecutar_app.bat` y `construir_exe.bat`.

---

## 4. Backend

### REST

| MÃ©todo y ruta | Para quÃ© |
|---|---|
| `POST /api/vivo/iniciar` | Arranca la captura (`fuente`, `archivo`, `ritmo_hz`, `bucle`). |
| `POST /api/vivo/detener` | Detiene y cierra el CSV. |
| `GET /api/vivo/estado` | Muestras, vuelta, grip, degradaciÃ³n, predicciÃ³n, ruta del CSV, errores. |
| `GET /api/vivo/ventana` | Ventana deslizante (`canales`, `n`). |
| `GET /api/vivo/sesiones` | Capturas de `data/vivo/`. |
| `GET /api/vivo/layout` | DiagnÃ³stico de la memoria de AC. |

### WebSocket `/api/vivo/stream`

El servidor empuja `{tipo:"vivo", â€¦}` cada ~100 ms; el cliente puede pedir
`{"canales": [...], "n": 600}` o `{"tipo":"ping"}`.

---

## 5. Mapeo AC â†’ esquema del proyecto

| AC1 | Esquema | Nota |
|---|---|---|
| `speedKmh` | `speed_kmh` | directo |
| `gas` / `brake` / `steerAngle` | `throttle` / `brake` / `steering` | `steering` normalizado y acotado |
| `tyreCoreTemperature[i]` | `temp_core_c_*` | Ã­ndice `0=FL,1=FR,2=RL,3=RR` |
| `wheelsPressure[i]` | `pressure_psi_*` | directo |
| `wheelSlip[i]` | `wheel_slip_*` | directo |
| `wheelLoad[i]` | `wheel_load_n_*` | directo |
| `tyreDirtyLevel[i]` | `dirty_level_*` | Ã·10 |
| `graphics.completedLaps + 1` | `lap` | 1-based |
| `tyreWear[i]` | `grip_<rueda>` (extra) | seÃ±al de agarre, **fuera** del esquema |
| â€” | `degradacion` | de la verdad (modo seco) o derivada del grip |

---

## 6. Criterios de aceptaciÃ³n

- [x] Sin AC en pista, `MemoriaAC` no crashea y `GET /api/vivo/layout` responde
      `disponible: false` con un mensaje claro.
- [x] El modo seco reproduce un CSV por la ruta viva y registra `<nombre>.csv`
      (esquema exacto) + `<nombre>_verdad.csv`.
- [x] La ruta viva es coherente con el batch (D13/D14): correlaciÃ³n > 0.97 por
      canal en `speed_kmh`, `wheel_slip_fl`, `temp_core_c_fl`, `wheel_load_n_fl`.
- [x] El WebSocket emite tramas `tipo:"vivo"` con ventana, degradaciÃ³n y predicciÃ³n.
- [x] `desktop.py` levanta el backend, arranca la captura y sirve el frontend
      compilado (probado con el *fallback* a navegador).
- [x] Suite completa en verde (**123 tests** de Python).
- [x] Tests de montaje del frontend (**8 tests**, Vitest + jsdom) y extras de la
      Etapa 2 Â§3.2 (dispersiÃ³n/correlaciÃ³n) y Â§3.5 (fallo de sensores) cerrados.
      seco (`activo`, `n`, `degradacion_modo=verdad`) y frontend servido en `/`.
- [ ] ValidaciÃ³n visual a 60 FPS con 360k muestras (requiere navegador visible).

---

## 7. Registro de implementaciÃ³n (desviaciones respecto al plan previo)

1. **`mmap` â†’ API de Win32.** El borrador usaba `mmap` con `tagname`; se cambiÃ³ a
   `OpenFileMappingW`/`MapViewOfFile` porque `mmap` crea la secciÃ³n si no existe
   (no distingue Â«AC apagadoÂ») y porque `from_buffer` exige un buffer escribible.
2. **Vista 7, no 6.** El frontend ya tenÃ­a seis vistas; la de captura es la **7**.
3. **Cobertura de outliers ampliada.** Detectado al escribir D14: el generador
   inyecta picos en **cualquier** columna (incluida `speed_kmh`) y el batch limpia
   `canales_fisicos()`. El acondicionador se alineÃ³ (outliers en `canales_fisicos`,
   filtro en `canales_filtrables`); sin esto, la correlaciÃ³n caÃ­a a ~0.55 por los
   picos gigantes en la velocidad.
4. **Filtro escalar.** El `sosfilt` de SciPy por muestra era demasiado lento
   (~2,2 M llamadas por stint): se sustituyÃ³ por la recurrencia directa escalar.
5. **`FuenteCSV` con registros.** `df.iloc[i]` por fila limitaba a ~1350 muestras/s;
   iterar `to_dict("records")` sube a ~1700 muestras/s (el tiempo real necesita 100).
6. **La traza batch tiene un retardo de grupo.** `resample_poly` es un FIR de fase
   lineal y `_resample_poly_df` no compensa su retardo; el residuo medido en vivo es
   de ~10â€“20 ms. Se documenta en D13/D14 y no se Â«arreglaÂ» para no tocar el batch.
   `sys.stdout`/`sys.stderr` son `None` y uvicorn falla al configurar el logging. Se
   seco y el frontend en `/`.
8. **Extras de la Etapa 2 cerrados aquÃ­.** Â§3.2 (dispersiÃ³n/correlaciÃ³n de features,
   Vista 2) y Â§3.5 (simulador de fallo de sensores, Vista 5) se implementaron junto
   con la Etapa 3 porque reutilizan la misma sesiÃ³n procesada y el mismo Ridge. El
   fallo de presiÃ³n es **inocuo** a propÃ³sito: `pressure_psi` no alimenta ninguna
   feature, y el panel lo evidencia.
9. **Tests del frontend.** Se aÃ±adiÃ³ Vitest + jsdom (`frontend/vitest.config.js`,
   `frontend/tests/`) para el *test de montaje*: las 7 vistas se montan, rellenan su
   contenedor y limpian sin tocar la red. Queda fuera la validaciÃ³n de 60 FPS
   (necesita un navegador real con canvas).

## 8. Fuera de alcance (Etapa 4)

- Adaptadores de esquema para **ACC / AC Evo** y datasets pÃºblicos (F2/F4).
- Apps Lua de AC vÃ­a **CSP** como fuente alternativa.
- Soporte de **Proton/Wine** o macOS.
- GrÃ¡ficas 3D y anÃ¡lisis de trayectoria.
