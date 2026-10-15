# Plan Etapa 2: Dashboard web y aplicación de escritorio para telemetría interactiva (v2 - Opción B, revisado antes de implementar)

Proyecto: predicción de degradación de neumáticos con telemetría de Assetto Corsa (AC).

**Objetivo de la Etapa 2:** construir una herramienta interactiva de alto rendimiento desacoplada (**Backend FastAPI + Frontend Web en Canvas/uPlot**) que funcione tanto en navegador web (ideal para segundas pantallas y tablets) como en una **aplicación de escritorio nativa de Windows empaquetable en un `.exe`** (vía `pywebview` + `pyinstaller`). Permite inspeccionar señales a 100 Hz a 60 FPS sin *jank*, ajustar hiperparámetros en tiempo real (Kalman <20 ms; Ridge <100 ms con *debounce*), comparar las estimaciones de Ridge y Kalman contra la degradación de referencia, y dejar resuelta la infraestructura de streaming para la **Etapa 3 (tiempo real)**.

> **Justificación arquitectónica (FastAPI + Frontend Web + Contenedor Desktop):**
> - Un stint de 40 vueltas a 100 Hz contiene **~360.000 muestras por canal**. Frameworks basados en re-ejecución total de Python y árboles DOM/SVG (como Streamlit/Plotly estándar) colapsan la memoria del navegador y sufren retardos notables (>1 s) al mover sliders.
> - Separar el cómputo científico (Python: `numpy`, `scipy`, `scikit-learn`) de la visualización acelerada por hardware (Frontend con Canvas 2D / WebGL mediante **uPlot**) permite renderizar 500.000 puntos en menos de 25 ms con menos de 5 MB de RAM.
> - **Doble modo de despliegue:**
>   1. **Aplicación de Escritorio (`.exe`):** Mediante `pywebview`, la interfaz web se ejecuta dentro de una ventana nativa de Windows (usando el motor WebView2 de Edge ya instalado en Windows 10/11), comportándose como cualquier programa de escritorio profesional (tipo MoTeC o SimHub), con icono propio y sin barras de navegador.
>   2. **Servidor Web Local (Segunda pantalla / Tablet):** Permite abrir la telemetría en un monitor secundario, móvil o tablet mientras conduces en Assetto Corsa a pantalla completa.
> - **Continuidad hacia la Etapa 3:** En la Etapa 3 (captura en vivo desde Assetto Corsa), este mismo frontend consumirá los paquetes a través del WebSocket ya implementado, sin tener que rediseñar la interfaz.

---

## 0. Hoja de ruta del proyecto

- **Etapa 1: Pipeline offline (F1).** Limpieza, features, Ridge y Kalman sobre CSV. Pipeline batch validado con métricas y reporte estático. *(Estado: Implementada y probada)*
- **Etapa 2: Dashboard interactivo y app desktop (F1).** Backend REST + WebSocket en FastAPI, frontend en Canvas/uPlot con telemetría fluida a 60 FPS, parámetros dinámicos, análisis espectral de Welch, diagnósticos de robustez, modo replay y empaquetado a ejecutable de escritorio (`.exe`). *(Estado: En desarrollo en esta rama)*
- **Etapa 3: Tiempo real (F3).** Conexión directa del backend a la memoria compartida de AC (`acpmf_physics`) transmitiendo paquetes por WebSocket al frontend/ejecutable existente.

---

## 1. Decisiones fijadas (precondiciones)

Estas decisiones de arquitectura y frontend están fijadas para garantizar fluidez absoluta, modularidad, usabilidad como app de escritorio y compatibilidad hacia adelante con la Etapa 3.

| # | Decisión | Valor por defecto | Por qué / cuándo revisarlo |
|---|---|---|---|
| D1 | Arquitectura del sistema | **Desacoplada: Backend FastAPI + Frontend Web SPA** | Python realiza el procesamiento de señales pesado y sirve endpoints REST/WebSocket; el navegador o WebView ejecuta el renderizado en GPU sin recargar la página. |
| D2 | Motor de visualización de series temporales | **uPlot (Canvas 2D acelerado)** | Es la librería de series temporales más rápida del ecosistema web (<25 ms para 150.000 puntos, memoria < 5 MB en browser, frente a >200 MB de Plotly/SVG). Permite zoom, pan y cursores sincronizados a 60 FPS. |
| D3 | Protocolos de comunicación | **REST (HTTP) para I/O y configuración; WebSocket para telemetría interactiva** | REST para listar sesiones, cargar CSVs y exportar YAML; WebSocket para el streaming continuo de telemetría y respuesta instantánea al mover sliders. |
| D4 | Formato de transferencia de datos | **Híbrido: JSON con arrays planos por vuelta; frames binarios (Float32) para stint completo y replay** | Evita objetos anidados redundantes (`[{x, y}, ...]`); transfiere arrays paralelos `[timestamps, canal_1, canal_2, ...]`. Por vuelta (~3.600 muestras) JSON es suficiente y depurable; para stint completo (360k muestras) o replay a 100 Hz se usa **payload binario** del WebSocket (`ArrayBuffer` → `Float32Array` directo a Canvas, sin parseo JSON ni presión al *Garbage Collector*), cumpliendo de verdad el objetivo de "Float32Array en cliente". |
| D5 | Modos de ejecución de la interfaz | **1. Sesión estática (análisis de CSV)** y **2. Replay simulado / Live (preparatorio Etapa 3)** | El modo 1 permite navegar una sesión completa por vueltas con cursores analíticos. El modo 2 emite las muestras a la frecuencia original (100 Hz) con una barra de reproducción (*play/pause/scrub*). |
| D6 | Distribución y ejecución en escritorio | **Doble vía: Ventana nativa Windows (`desktop.py` con PyWebView) y `.exe` (PyInstaller)** | Permite ejecutar con doble clic en Windows sin abrir consola negra de comandos ni navegador tradicional, manteniendo el acceso web opcional para segundas pantallas. |
| D7 | Gestión de estado y reactividad | **Store cliente reactivo ligero + caché en memoria en FastAPI** | Mover un slider de Kalman ($Q$, $R$) envía un mensaje liviano por WebSocket y el backend recalcula solo el filtro en ~20 ms. El slider de $\alpha$ de Ridge dispara un re-fit **en el threadpool** (`asyncio.to_thread`) con *debounce* de 100 ms para no saturar el event loop. El frontend actualiza únicamente la curva afectada sin tocar el resto de la UI. |
| D8 | Diseño estético y estilo | **Dark Telemetry estilo "Mission Control / F1"** | Interfaz profesional de ingeniería de carreras: paleta oscura profunda (zinc/slate), tipografía sans moderna (*Inter* / *Outfit*) y monoespaciada para datos (*JetBrains Mono*), acentos cromáticos normalizados por canal (Velocidad: Blanco/Cyan, Slip: Ámbar, Temperatura: Rojo carmesí, Carga: Verde esmeralda). |
| D9 | Selector y disposición de ruedas | **Selector individual + Vista de planta de coche 2×2 interactiva** | Permite aislar una rueda (FL, FR, RL, RR) o ver las 4 simultáneamente con balance térmico y de agarre en tiempo real. |
| D10 | Persistencia de parámetros | **Exportación bidireccional de YAML vía REST (`/api/config`)** | Cualquier ajuste realizado en los sliders de la interfaz se puede descargar como `config_custom.yaml` o guardar en el servidor para usarlo en `python main.py`. |
| D11 | Soporte de fuentes de datos (alcance Etapa 2) | **Obligatorio: F1 (Simulada) + Drag & Drop de CSV con validación de esquema. Opcional: F2 y F4** | Selector de archivos de `data/raw/` o carga local mediante dropzone con validación instantánea del contrato de `src/config.py`. F2 (Live Telemetry) y F4 (HuggingFace) requieren un **adaptador de esquema** (mapeo de sus columnas al contrato) y se dejan como extensión opcional al final; ningún criterio de la §12 depende de ellos. |

---

## 2. Arquitectura del Sistema y Flujo de Comunicación

```
┌────────────────────────────────────────────────────────────────────────┐
│                   APLICACIÓN DE ESCRITORIO (.exe)                      │
│             Ventana nativa Windows con PyWebView (Edge WebView2)       │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  Header: Selector de sesión, fuente, modo (Offline / Replay)    │   │
│   └────────────────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────┬─────────────────────────────────┐   │
│   │  Paneles uPlot (Canvas 2D)   │  Planta de coche 2×2 (Heatmap)  │   │
│   │  - Telemetría cruda vs limpia│  - Temperaturas de banda        │   │
│   │  - Espectro Welch (PSD)      │  - Desgaste estimado / slip     │   │
│   │  - Predicción Ridge + Kalman │  - Carga normal vertical        │   │
│   └──────────────────────────────┴─────────────────────────────────┘   │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  Laboratorio de sliders reactivos (fc, MAD, k_fuel, Q, R, SNR) │   │
│   └────────────────────────────────────────────────────────────────┘   │
└───────────────────▲───────────────────────────────▲────────────────────┘
                    │ REST (HTTP)                   │ WebSocket (/ws/telemetria)
                    │  - /api/sesiones              │  - Paquetes de telemetría
                    │  - /api/procesar              │  - Slider drag events (<20ms)
                    │  - /api/config                │  - Replay de carrera 100 Hz
                    ▼                               ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        BACKEND (Python / FastAPI)                      │
│                                                                        │
│   [ Servidor ASGI local en segundo plano (localhost:8000) ]            │
│       ├── Servir estáticos compilados del Frontend (`frontend/dist`)   │
│       ├── `src.limpieza`   ──> Remuestreo 100 Hz, Outliers, SOS causal │
│       ├── `src.features`   ──> Ventanas 2s, Welch PSD, Grados-segundo │
│       ├── `src.etiquetas`  ──> Wear canónico y corrección k_fuel       │
│       ├── `src.modelo`     ──> Inferencia Ridge & recursión de Kalman  │
│       └── `src.evaluacion` ──> Métricas, drop-off lap, cobertura bandas│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Módulos y Vistas de la Interfaz

La aplicación se estructura en una consola centralizada de alta productividad con pestañas temáticas fluidas:

### 3.1 Módulo 1: Telemetría de Alta Frecuencia (Cruda vs. Limpia)
Objetivo: Inspección visual de la fidelidad del sensor a 100 Hz con zoom milimétrico y latencia cero.

- [ ] **Canvas uPlot sincronizado multicanal:**
  - Canal principal: `wheel_slip`, `temp_core_c`, `wheel_load_n` o `pressure_psi`.
  - Canal de referencia sincronizado (subgráfico inferior): `speed_kmh`, `throttle`, `brake`, `steering`.
  - Eje X compartido con cursor vertical sincronizado que muestra los valores numéricos exactos de todos los canales en el punto del cursor.
- [ ] **Visualización analítica de limpieza:**
  - Traza cruda en gris semitransparente superpuesta a la traza filtrada con color identificativo de rueda.
  - Marcadores de outliers detectados (glifos en el canvas) calculados por el algoritmo mediana/MAD causal.
  - Sombreado de tramos con datos perdidos o huecos temporales interpolados.
- [ ] **Navegación temporal y por vuelta:**
  - Selector de vuelta rápida (Vuelta 1 a $N$) con indicador de tiempo de vuelta.
  - Paginador de vuelta con teclas de flecha (← / →) para auditar anomalías vuelta por vuelta sin saturar la pantalla.
  - Modo "Stint completo" con visualización optimizada mediante min-max bucket downsampling.
- [ ] **KPIs de calidad de señal en tiempo real:**
  - Outliers descartados en la vuelta / sesión.
  - Atenuación de varianza del ruido ($10 \log_{10}(\sigma^2_{\text{cruda}} / \sigma^2_{\text{filtrada}})$).
  - Estado del filtro causal (retardo de grupo estimado en muestras).

### 3.2 Módulo 2: Dinámica del Monoplaza y Análisis Espectral (Welch)
Objetivo: Auditar la energía frecuencial de las vibraciones de slip y la distribución espacial de desgaste.

- [ ] **Espectrograma y Densidad Espectral de Potencia (Welch PSD):**
  - Gráfica interactiva de PSD en escala logarítmica (dB/Hz vs. Hz).
  - Selector de `nperseg` de Welch (64–512, defecto 128): con fs = 100 Hz y `nperseg = 128`, $\Delta f \approx 0.78$ Hz y la banda baja (0.5–5 Hz) solo dispone de ~6 bins; subir a 256/512 mejora la resolución frecuencial a costa de ventanas más cortas.
  - Comparación en tiempo real: espectro crudo vs. espectro tras filtro Butterworth SOS.
  - Resaltado de bandas configuradas: Banda Baja (0.5–5 Hz), Media (5–15 Hz), Alta (15–40 Hz).
  - Línea vertical indicadora de la frecuencia de corte actual ($f_c$).
- [ ] **Esquema de Planta del Coche 2×2 (Tire Heatmap & Balance):**
  - Representación visual del chasis con las 4 posiciones (FL, FR, RL, RR).
  - Indicadores dinámicos por rueda:
    - Temperatura de carcasa promedio (escala de color de azul a rojo crítico > 105 °C).
    - Presión media y carga normal promedio en apoyos.
    - Trabajo de fricción acumulado ($\int |\text{slip}| \cdot F_z \cdot v \cdot dt$).
- [ ] **Matriz de correlación de features:**
  - Dispersión interactiva de features seleccionadas por el usuario (ej. Grados-segundo vs. Tasa de degradación).

### 3.3 Módulo 3: Predicciones, Modelos y Filtro de Kalman
Objetivo: Auditoría visual de la degradación estimada frente al desgaste real/proxy.

- [ ] **Gráfico de evolución de degradación del stint:**
  - Eje X: Número de vuelta (1 a $N$). Eje Y: Degradación canónica normalizada $\in [0, 1]$.
  - Trazas simultáneas:
    - **Verdad de referencia:** Degradación real simulada (F1) o logueada por AC (F2).
    - **Proxy de desgaste:** Delta de tiempos corregido por combustible ($k_{\text{fuel}}$).
    - **Predicción Ridge:** Agregación por vuelta de las ventanas de telemetría.
    - **Filtro de Kalman:** Estado estimado $\hat{x}_{k|k}$ con opción de pronóstico a $h$ pasos.
    - **Baselines:** Media móvil acumulada y repetición del último valor.
- [ ] **Bandas de incertidumbre dinámica de Kalman:**
  - Intervalo de confianza al 95 % ($\pm 1.96 \sqrt{P_k}$) renderizado como área sombreada suave.
  - Selector de horizonte de pronóstico ($h = 1, 3, 5$ vueltas) mostrando la expansión de la incertidumbre.
- [ ] **Detección de la Vuelta de Caída (*Drop-Off Lap*):**
  - Línea de umbral crítica ajustable (defecto: 0.5 de degradación).
  - Marcadores de cruce: Vuelta de caída real vs. estimada por Ridge y Kalman.
  - Error explícito en número de vueltas ($\Delta \text{Laps}$).
- [ ] **Tabla de métricas de precisión:**
  - MAE, RMSE, $R^2$ y cobertura real de las bandas de incertidumbre (comparada contra el 95 % teórico).

### 3.4 Módulo 4: Laboratorio de Parámetros Dinámico (Kalman <20 ms; Ridge <100 ms con *debounce*)
Objetivo: Experimentar interactivamente con los hiperparámetros del pipeline mediante controles que responden sin recargar la página.

- [ ] **Panel de control de limpieza:**
  - Slider: Frecuencia de corte Butterworth ($f_c \in [5.0, 40.0]$ Hz, paso 0.5 Hz).
  - Slider: Umbral de MAD para outliers ($6.0$ a $20.0$).
  - Toggle: Activación/desactivación de interpolación causal de huecos.
- [ ] **Panel de control de features y proxy:**
  - Slider: Umbral de grados-segundo ($70$ a $110$ °C).
  - Slider: Coeficiente de combustible $k_{\text{fuel}}$ ($0.010$ a $0.080$ s/kg).
  - Switch: "Calibración automática de $k_{\text{fuel}}$ por regresión".
- [ ] **Panel de control de modelos (reactividad instantánea vía WebSocket):**
  - Slider logarítmico: $\alpha$ de regularización de Ridge ($10^{-3}$ a $10^{3}$). Fija el valor **directamente, sin validación cruzada** (partiendo del α elegido por CV en la Etapa 1); el re-fit corre en un hilo con *debounce* de 100 ms.
  - Toggle de ablación: Excluir features derivadas de slip/temperatura (mitigación de circularidad).
  - Sliders de ruido de Kalman:
    - $\log_{10}(Q_{\text{nivel}})$ (de $-6$ a $-2$).
    - $\log_{10}(Q_{\text{pendiente}})$ (de $-7$ a $-3$).
    - $\log_{10}(R)$ (de $-5$ a $-1$).
  - Switch: "Monotonicidad estricta ($x_k \ge x_{k-1}$)".
- [ ] **Gestión de perfiles de configuración:**
  - Botón: "Guardar configuración actual en servidor".
  - Botón: "Descargar `config_custom.yaml`".
  - Botón: "Restablecer a valores de fábrica (`config.yaml`)".

### 3.5 Módulo 5: Diagnóstico Físico, Robustez y Estrés de Señal
Objetivo: Evaluar el comportamiento del sistema ante condiciones degradadas y validar la física del modelo.

- [ ] **Simulador interactivo de ruido de canal (SNR):**
  - Slider dinámico de SNR: desde 40 dB (óptimo) hasta 0 dB (severamente ruidoso).
  - Inyección de ruido gaussiano interactiva sobre las entradas con actualización en vivo del error MAE.
  - Gráfica interactiva MAE vs. SNR en dB.
- [ ] **Inspección de física de coeficientes Ridge:**
  - Gráfica de barras horizontales con el peso estandarizado $\beta_j$ de cada feature.
  - Indicador visual de congruencia física: barras verdes (signo positivo esperado para degradación) y barras rojas (signo contraintuitivo / advertencia de colinealidad).
  - Agrupación colapsable por familias (`grados_segundo`, `temperatura`, `carga`, `friccion`, `psd`, `slip`).
- [ ] **Simulador de fallo de sensores:**
  - Switches para desconectar canales individuales (ej. fallo del sensor de presión de la rueda delantera derecha).
  - Observación inmediata de cómo Kalman compensa la pérdida de precisión.

### 3.6 Módulo 6: Modo Replay / Live Telemetry (Puente a Etapa 3)
Objetivo: Emular la experiencia de carrera en tiempo real que se conectará con Assetto Corsa en la Etapa 3.

- [ ] **Control de reproducción:** Botones de *Play*, *Pausa*, *Velocidad (1x, 2x, 5x)* y barra de progreso de tiempo (*scrubbing*).
- [ ] **Buffer circular en frontend:** La gráfica avanza como un osciloscopio / registrador de tira continua a 100 Hz mostrando una ventana deslizante de los últimos 10–30 segundos.
- [ ] **Estimación en ventana deslizante:** El backend emite la predicción de degradación a medida que los datos fluyen, demostrando que el código es 100 % causal.

---

## 4. Arquitectura del Backend (`backend/`)

El backend expone una API rápida y liviana utilizando **FastAPI**:

```
backend/
├── app.py                # Instancia de FastAPI, middleware CORS y montaje de estáticos
├── routers/
│   ├── sesiones.py       # Listar, cargar y validar archivos CSV de data/raw/
│   ├── telemetria.py     # Obtención de canales procesados y estadísticas
│   ├── modelos.py        # Endpoints para inferencia y re-entrenamiento
│   └── configuracion.py  # Carga, validación y exportación de config.yaml
├── ws/
│   ├── gestor.py         # Gestor de conexiones WebSocket y eventos
│   └── stream_telemetria.py # Transmisión continua / replay a 100 Hz
└── servicios/
    ├── adaptador_pipeline.py # Envoltorio sobre src/ para llamadas sin I/O innecesario
    └── cache_memoria.py      # Almacenamiento de DataFrames procesados en RAM
```

### Endpoints REST principales:
- `GET /health`: Sonda de vida; `desktop.py` espera su `200` antes de abrir la ventana (evita la pantalla en blanco si el servidor tarda o el puerto estaba ocupado).
- `GET /api/sesiones`: Lista los CSVs disponibles en `data/raw/` y metadatos de las sesiones.
- `POST /api/sesiones/cargar`: Selecciona o sube un CSV; valida esquema y lo remuestrea.
- `GET /api/telemetria/vuelta/{lap}`: Retorna arrays planos de tiempo y canales para la vuelta solicitada (JSON; ~3.600 muestras, ligero).
- `GET /api/telemetria/espectro`: Retorna arrays de frecuencias y PSD en dB para la señal seleccionada.
- `POST /api/modelos/kalman/estimar`: Recibe $Q, R$, monotonicidad y devuelve el estado estimado y bandas en <15 ms (el recálculo real sobre 40 vueltas es <1 ms).
- `POST /api/modelos/ridge/ajustar`: Fija $\alpha$ (y la ablación) y re-entrena; corre en el threadpool con *debounce* para no bloquear el event loop.
- `GET /api/config`: Retorna la configuración activa en formato JSON.
- `POST /api/config`: Actualiza parámetros y permite exportar como YAML.

### WebSocket `/ws/telemetria`:
- Permite comunicación full-duplex de baja latencia (<5 ms de ida y vuelta local).
- **Trama JSON** para eventos de control: `{ tipo: "ajuste_kalman", q_nivel, q_pendiente, r }` $\rightarrow$ Respuesta con nuevo vector de estado.
- **Trama binaria** (`ArrayBuffer`, Float32 en little-endian con cabecera `[n_muestras, n_canales]`) para stint completo y replay: se mapea directo a `Float32Array` en el cliente sin parseo (los 360k puntos en JSON serían ~10 MB por envío).
- Modo Replay: Envío de paquetes de telemetría a 100 Hz simulando la conexión en vivo de AC.
- Los cómputos pesados (re-fit de Ridge, extracción de features) se despachan con `asyncio.to_thread` para que el event loop nunca se bloquee.

---

## 5. Arquitectura del Frontend (`frontend/`)

Estructura modular limpia, moderna y sin sobrecarga innecesaria:

```
frontend/
├── index.html            # Shell de la aplicación (HTML5 semántico, layouts, accesibilidad)
├── package.json          # Vite + uPlot
├── vite.config.js        # Configuración de dev server y proxy hacia FastAPI
├── src/
│   ├── main.js           # Punto de entrada, enrutador de pestañas y WebSocket
│   ├── api.js            # Cliente HTTP (fetch) y WebSocket
│   ├── estado.js         # Estado global de la aplicación (sesión activa, vuelta, configs)
│   ├── estilos/
│   │   ├── variables.css # Tokens de diseño (paleta Dark Telemetry, tipografías, espaciados)
│   │   ├── layout.css    # Grids de cabecera, gráficos y paneles laterales
│   │   ├── uplot_tema.css# Estilos personalizados para las curvas, leyendas y tooltips
│   │   └── widgets.css   # Sliders táctiles, switches, botones glassmorphism
│   ├── componentes/
│   │   ├── graficas.js   # Creación y actualización de instancias uPlot
│   │   ├── heatmap_coche.js # Renderizado de la planta 2x2 del auto
│   │   ├── panel_sliders.js # Controles dinámicos con debounce y WebSocket
│   │   └── tabla_kpis.js # Tarjetas KPI de error, degradación y drop-off lap
│   └── vistas/
│       ├── v_telemetria.js
│       ├── v_espectro.js
│       ├── v_prediccion.js
│       ├── v_laboratorio.js
│       ├── v_robustez.js
│       └── v_replay.js
```

---

## 6. Modo Aplicación de Escritorio y Empaquetado a `.exe`

Para cumplir con el objetivo de tener una aplicación de escritorio ejecutable con doble clic (`.exe`) sin perder la flexibilidad web:

### 6.1 Lanzador de escritorio (`desktop.py` con PyWebView)
- Se implementa un lanzador en Python (`desktop.py`) que arranca el servidor FastAPI en un hilo en segundo plano en `127.0.0.1` sobre **un puerto libre detectado dinámicamente** (8000 por defecto; si está ocupado, 8001, 8002…) y espera la sonda `GET /health` antes de abrir la ventana.
- Abre inmediatamente una ventana nativa de Windows mediante **`pywebview`**:
  - Utiliza el motor nativo de Windows (Microsoft Edge WebView2 / Chromium).
  - Tamaño inicial configurado a $1440 \times 900$ px con soporte de pantalla completa (F11).
  - Título personalizado: `"Telemetry Analytics - Compound Degradation"`.
  - Icono de ventana nativo de Windows (`assets/icon.ico`).
  - Al cerrar la ventana, el proceso del servidor backend se detiene limpiamente.

### 6.2 Flujo de compilación a ejecutable independiente (`compilar_exe.bat`)
1. **Paso 1 (Compilar Frontend):** Se ejecuta `npm run build` dentro de `frontend/`, generando la carpeta estática optimizada `frontend/dist`.
2. **Paso 2 (Montaje de estáticos en FastAPI):** `backend/app.py` monta la carpeta `frontend/dist` para servir la aplicación automáticamente en la raíz `/`.
3. **Paso 3 (Empaquetado con PyInstaller):** Se usa un archivo **`TelemetryAnalytics.spec`** (no una línea de comandos: en Windows el continuador de línea es `^`, no `\`, y los `--add-data` dentro de un `.bat` son un foco habitual de errores). Contenido relevante del `.spec`:
   - `--add-data "frontend/dist;frontend/dist"` → la interfaz ya compilada.
   - `--add-data "config.yaml;."` → configuración por defecto.
   - `--icon "assets/icon.ico"` e inclusión de los *dat files* de `pywebview` (requisito para que la ventana nativa funcione dentro del `.exe`).
   - **No se empaqueta `data/raw`:** los CSV crecen con cada sesión y quedarían sellados dentro del binario. El ejecutable crea `data/raw/` **junto al `.exe`** en el primer arranque y además admite cargar CSV por drag & drop (D11). Opcional: incluir solo `sim_42.csv` como sesión de demostración.
4. **Resultado:** Se genera la carpeta `dist/TelemetryAnalytics/TelemetryAnalytics.exe`, listo para abrir con doble clic sin necesidad de tener Python ni Node.js instalados en la máquina de destino. Se usa `--onedir` **en lugar de `--onefile`** a propósito: el modo *onefile* extrae numpy/pandas/scipy a `%TEMP%` en cada arranque y tarda varios segundos hasta mostrar la ventana.

### 6.3 Scripts de conveniencia en la raíz
- `iniciar_desktop.bat`: Lanza el modo escritorio de inmediato para desarrollo.
- `iniciar_web.bat`: Lanza solo el servidor FastAPI para acceder desde el navegador o tablet.
- `compilar_exe.bat`: Compila el frontend y genera el `.exe` con un solo clic.

---

## 7. Rendimiento y Optimización para Señales de 100 Hz

Para garantizar que la experiencia sea instantánea tanto en la web como en la ventana `.exe`:

1. **Estructura de datos en cliente (`Float32Array`):** En lugar de objetos JavaScript `{timestamp: ..., valor: ...}`, el backend envía arrays numéricos planos: JSON por vuelta para análisis y **frames binarios Float32** para stint/replay, que el cliente monta directo en `Float32Array` sin parseo ni sobrecarga de recolección de basura (*Garbage Collection*).
2. **WebGL / Canvas 2D sin recrear el DOM:** uPlot dibuja en un elemento `<canvas>`. Las actualizaciones de sliders borran y redibujan las curvas en menos de 2 milisegundos, manteniendo 60 FPS estables.
3. **Cursores sincronizados entre gráficas:** Al pasar el ratón sobre la gráfica de slip, el cursor de velocidad, freno y temperatura se sincroniza inmediatamente mediante el bus de eventos de uPlot (`uPlot.sync("telemetria")`).
4. **Caché en memoria en el Backend:** Una vez que `src.limpieza` remuestrea y filtra el CSV, el DataFrame resultante reside en la memoria RAM del servidor FastAPI; las peticiones posteriores solo leen rebanadas de memoria sin I/O de disco.

---

## 8. Pruebas y Validación (`tests/`)

Se incorporan pruebas automatizadas específicas para la Etapa 2:

- [ ] **Tests de API REST (`tests/test_api_rest.py`):**
  - Validación de endpoints con `httpx` / `TestClient` de FastAPI.
  - Comprobar que `/api/telemetria/vuelta/1` devuelve arrays numéricos correctos y con dimensiones coincidentes.
  - Verificar que la validación de esquema rechaza CSVs mal formateados con código 422.
- [ ] **Tests de WebSocket (`tests/test_api_ws.py`):**
  - Conexión y desconexión limpia del cliente WebSocket.
  - Enviar mensaje de ajuste de Kalman y verificar que la respuesta contiene las bandas nuevas.
  - Medir latencia **contra un servidor `uvicorn` real** con un cliente `websockets` (el `TestClient` de FastAPI es síncrono en proceso y no mide latencia de red): objetivo <50 ms.
  - Validar que la trama binaria de replay decodifica a la forma esperada `[n_canales, n_muestras]`.
- [ ] **Tests de coherencia numérica:**
  - Comprobar que los resultados de Ridge y Kalman calculados por la API son exactamente idénticos a los generados por `main.py` de la Etapa 1, **con el slider de $\alpha$ en su valor por defecto (el elegido por CV) y los Q/R de `config.yaml`**.
- [ ] **Test de exportación de configuración:**
  - Verificar que el endpoint `/api/config` genera un YAML que cumple con `src.config.cargar_config`.
- [ ] **Test de montaje de la aplicación de escritorio:**
  - Comprobar que `desktop.py` puede inicializar la ventana y que los archivos estáticos de `frontend/dist` están disponibles.

---

## 9. Conceptos de clase aplicados en la Etapa 2

- **Sistemas de adquisición y telemetría:** Protocolos de comunicación en tiempo real (WebSockets vs. polling HTTP), latencia de transmisión y empaquetamiento de tramas de sensores.
- **Filtrado digital interactivo:** Inspección en vivo del compromiso entre ancho de banda, rechazo de ruido fuera de banda y retardo de fase en filtros causales IIR (Butterworth SOS).
- **Procesamiento espectral de señales:** Interpretación visual de la densidad espectral de potencia (PSD) estimada mediante el método de Welch, resolución frecuencial ($\Delta f$) y efecto del enventanado.
- **Fusión de datos y estimación recursiva (Kalman):** Balance dinámico entre la confianza en el modelo de dinámica vehicular ($Q$) y la varianza de los instrumentos de medición ($R$).
- **Arquitectura de software para ingeniería:** Separación estricta de responsabilidades (*Separation of Concerns*), servicios backend de alto rendimiento, renderizado por hardware en cliente y distribución nativa de escritorio.

---

## 10. Dependencias del Proyecto (Actualizadas)

### Backend y Runtime Desktop (`requirements.txt`):
```txt
# --- Etapa 1 (conservar; FUSIONAR, no reemplazar el archivo actual) ---
numpy>=2.0
scipy>=1.13
pandas>=2.0
scikit-learn>=1.4
matplotlib>=3.8     # src/reporte.py (Etapa 1)
joblib>=1.3         # main.py persiste el modelo Ridge
pyyaml>=6.0
pytest>=8.0
# --- Etapa 2 (nuevo) ---
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
websockets>=12.0
httpx>=0.27.0       # TestClient de FastAPI
pywebview>=5.1
pyinstaller>=6.8.0
```
> El `requirements.txt` actual ya incluye `matplotlib`, que este listado anterior omitía: reemplazarlo a ciegas **rompería los 48 tests de Etapa 1**.

### Frontend (`frontend/package.json`):
```json
{
  "name": "telemetry-analytics-dashboard",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "uplot": "^1.6.30"
  },
  "devDependencies": {
    "vite": "^5.3.0"
  }
}
```

---

## 11. Orden de trabajo secuencial (por prioridad)

> **MVP = pasos 1–5 con las Vistas 1, 3 y 4**, que son las que exigen los criterios de la §12. Las Vistas 5, 2 y 6 se implementan después; la 5 solo añade el slider de SNR y la 2/6 son las primeras en recortarse si aprieta el plazo (aunque ya cuentan con criterio propio).

1. **Dependencias del Backend y Runtime Desktop:**
   - Fusionar en `requirements.txt` las dependencias nuevas (`fastapi`, `uvicorn`, `websockets`, `httpx`, `pywebview`, `pyinstaller`) **sin eliminar** `matplotlib`/`joblib` de la Etapa 1.
   - Crear el módulo `backend/` conectando directamente con los módulos existentes de `src/`.
2. **Endpoints REST y WebSocket de telemetría:**
   - Implementar endpoints para listar sesiones, extraer telemetría por vuelta, calcular PSD Welch y la sonda `/health`.
   - Implementar el WebSocket (`/ws/telemetria`) con tramas JSON de control y tramas binarias de datos.
3. **Setup del Frontend Web con Vite y uPlot:**
   - Inicializar el entorno del frontend con Vite y configurar estilos base de telemetría oscura.
   - Construir el adaptador de gráficas uPlot sincronizadas con soporte para 100 Hz.
4. **Implementación de las Vistas de la Interfaz (en este orden):**
   - **Vista 1 (prioridad):** Telemetría Cruda vs. Limpia con detección visual de outliers y selector de vuelta.
   - **Vista 3 (prioridad):** Curva de degradación, bandas de Kalman $\pm 1.96\sigma$, baselines y drop-off lap.
   - **Vista 4 (prioridad):** Laboratorio de hiperparámetros reactivos y exportador YAML.
   - Vista 5: Inyección interactiva de ruido SNR y diagnósticos físicos de Ridge.
   - Vista 2: Espectro Welch en dB y esquema 2×2 del chasis del vehículo.
   - Vista 6: Modo Replay con osciloscopio en tiempo real (preparando la Etapa 3).
5. **Contenedor de Escritorio y Empaquetado (`desktop.py` y `.bat`):**
   - Implementar `desktop.py`: puerto libre dinámico, espera de `/health` y ventana nativa con `pywebview`.
   - Crear script `iniciar_desktop.bat` para arranque instantáneo con doble clic.
   - Crear script `compilar_exe.bat` con PyInstaller (mediante `TelemetryAnalytics.spec`) para generar el `.exe` distribuible.
6. **Pruebas automatizadas y validación:**
   - Implementar tests de endpoints REST y WebSocket en `tests/` (latencia con servidor real).
   - Verificar rendimiento de 60 FPS con 360k muestras.
7. **Documentación:**
   - Actualizar `README.md`: tabla de hoja de ruta (Etapa 2 → Implementada), estructura con `backend/`/`frontend/` e instrucciones de uso en navegador y como ejecutable de escritorio.

---

## 12. Criterios para dar Etapa 2 por terminada

- La aplicación de escritorio se abre mediante `desktop.py` (o `iniciar_desktop.bat`) en una ventana nativa de Windows, esperando a `/health`, sin errores ni barras de navegador.
- Los endpoints REST responden en <20 ms con la caché caliente y el recálculo de Kalman responde en <20 ms; el re-fit de Ridge (vía WebSocket, con *debounce*) completa el ciclo en <100 ms sin congelar la interfaz.
- La navegación por la telemetría a 100 Hz es fluida a 60 FPS, sin bloqueos al hacer zoom o pan sobre 360k muestras (Canvas 2D / uPlot).
- La gráfica de telemetría muestra con claridad los picos de outliers detectados por la mediana/MAD y la curva limpia suavizada por el filtro causal.
- Mover los sliders de Kalman ($Q$, $R$) recalcula y redibuja la estimación de estado y sus bandas de incertidumbre en tiempo real.
- El espectro Welch muestra crudo vs. filtrado con la línea de $f_c$ desplazándose en vivo, y la planta 2×2 refleja temperatura, presión y carga de las cuatro ruedas.
- Se puede inyectar ruido con el slider de SNR y observar la degradación instantánea del error de predicción.
- El modo Replay reproduce una sesión a 100 Hz (play/pausa/velocidad/scrub) con ventana deslizante, emitiendo la predicción de degradación por tramas binarias.
- La configuración modificada en la interfaz se puede exportar como un archivo YAML válido e interoperable con `main.py`.
- Se genera el ejecutable independiente `.exe` funcional mediante `compilar_exe.bat`.
- Todas las pruebas de backend y consistencia pasan satisfactoriamente (`pytest`).

---

## 13. Registro de cambios de la revisión (v2)

Correcciones aplicadas **antes** de iniciar la implementación, con la mejor decisión para el estado actual del proyecto:

1. **Endpoint WebSocket unificado** a `/ws/telemetria` (el diagrama decía `/ws/stream`).
2. **`requirements.txt` se fusiona, no se reemplaza:** se conservan `matplotlib` y `joblib` de la Etapa 1 (evita romper sus 48 tests).
3. **El slider de $\alpha$ fija el valor directamente** (sin CV), con re-fit en threadpool y *debounce*; el test de coherencia numérica se fija en el α por defecto de la Etapa 1.
4. **Criterios de aceptación (§12) ampliados** con los Módulos 2 (espectro/planta) y 6 (replay), que faltaban, y con criterios de latencia realistas por tipo de endpoint.
5. **D11 acotado:** alcance obligatorio F1 + drag & drop; F2/F4 pasan a extensión opcional (requieren adaptador de esquema) para no comprometer el plazo.
6. **D4 híbrido:** JSON por vuelta y **frames binarios** (Float32) para stint completo/replay, que es lo que realmente cumple "Float32Array en cliente" con 360k muestras.
7. **PyInstaller vía `TelemetryAnalytics.spec`** (el comando con `\` no funciona en un `.bat` de Windows) y **sin empaquetar `data/raw`** dentro del `.exe` (se lee junto al ejecutable + drag & drop); se documenta por qué `--onedir` y no `--onefile`.
8. **Puerto dinámico + `GET /health`** en `desktop.py`, para evitar colisiones en el 8000 y pantallas en blanco.
9. **Test de latencia WebSocket** contra un servidor `uvicorn` real (el `TestClient` síncrono no mide red) y validación de la trama binaria.
10. **§11 reordenado por prioridad:** Vistas 1, 3 y 4 primero (las que exige §12), 5/2/6 después.
11. **Welch:** selector de `nperseg` con nota sobre $\Delta f$ (`nperseg = 128` → $\Delta f \approx 0.78$ Hz, ~6 bins en la banda baja).
12. **README.md** pendiente de actualizar (tabla de hoja de ruta y estructura) — queda explícito en §11.7.
