# Plan Etapa 1: Pipeline offline (v2)


> **Nota de reorganización.** Los módulos que este plan llama `src/` viven ahora en
> `telemetria/pipeline/`, y el orquestador `main.py` es
> `telemetria/pipeline/orquestador.py` (se ejecuta con `python -m telemetria pipeline`).
Proyecto: predicción de degradación de neumáticos con telemetría de Assetto Corsa (AC).

**Objetivo de la Etapa 1:** un pipeline que limpia señales, extrae features, entrena Ridge y Kalman, evalúa y genera un reporte, todo sobre archivos CSV. Aquí se valida que la lógica es correcta, antes de meter complejidad.

> **Nota de nomenclatura (v2).** Antes las "fuentes de datos" se llamaban A, B, C, D y las etapas también empiezan por letra. Para evitar choques, en este documento:
> - Las **etapas** son **Etapa 1 / Etapa 2 / Etapa 3**.
> - Las **fuentes de datos** son **F1, F2, F3, F4** (ver sección 2).

---

## 0. Hoja de ruta del proyecto

- **Etapa 1: Pipeline offline (F1).** Limpieza, features, Ridge y Kalman sobre CSV. Se valida que la lógica es correcta antes de meter complejidad.
- **Etapa 2: Dashboard (F2).** Visualización de señal cruda vs. limpia, parámetros ajustables y resultados de predicción. Sirve para revisar resultados.
- **Etapa 3: Tiempo real (F3).** Captura desde AC y predicción en ventanas deslizantes. Aquí se juntan todos los módulos anteriores.

La Etapa 1 se diseña desde ya pensando en la 3: las features reciben **una ventana**, no un archivo; el filtro es **causal**; y el escalado de features queda guardado para reutilizarlo.

---

## 1. Decisiones fijadas (precondiciones)

Estas decisiones van **antes** de escribir código. Son las que bloqueaban los pasos 2–4 en la v1. Se pueden ajustar más adelante, pero quedan fijadas por defecto y registradas en `config.yaml`.

| # | Decisión | Valor por defecto | Por qué / cuándo revisarlo |
|---|---|---|---|
| D1 | Frecuencia de muestreo objetivo | **100 Hz** | Nyquist = 50 Hz, suficiente para la dinámica de slip y temperatura y barata de procesar. La captura real puede venir a ~333 Hz (física de AC); se remuestrea a 100 Hz (ver sección 5). Subir a 200 Hz solo si las features espectrales lo exigen. |
| D2 | Ventana de features e *hop* | **W = 2.0 s, hop = 1.0 s** (200 y 100 muestras) | Las ventanas de 1.0 s daban resolución espectral de ~1 Hz y muy pocos segmentos en Welch. 2 s permite `nperseg=128`, `noverlap=64`. El *hop* del 50 % es el mismo esquema que se usará en tiempo real. |
| D3 | Filtro pasa-bajas | **Butterworth orden 4, corte 20 Hz, `sosfilt` causal** | Muy por debajo de Nyquist (50 Hz); conserva la señal útil y rechaza el ruido de sensor/muestreo. Causal para que funcione en Etapa 3. |
| D4 | Umbral para grados-segundo | **90 °C** (temperatura de carcasa) | Feature = Σ máx(0, T − 90)·dt. Se bajó de 100 °C a 90 °C al ver que con 100 °C la feature quedaba casi nula en las primeras vueltas (desgaste bajo → T < 100), lo que hacía que el modelo explotara al extrapolar a vueltas tardías. 90 °C es el inicio de la ventana de trabajo "caliente" de la goma. |
| D5 | Vueltas del simulador | **40 vueltas** (configurable) | Suficiente para validación cruzada agrupada sin quedarnos sin datos. |
| D6 | Etiqueta canónica | **degradación acumulada normalizada ∈ [0,1]** | Unifica F1 (verdadera), F2 (`wear%/100`) y el proxy. La **tasa por vuelta** (%/vuelta) es la derivada y se reporta aparte. Ver sección 8. |
| D7 | Corrección por combustible (proxy) | **t_corr = t − k_fuel · kg_combustible**, k_fuel ≈ **0.035 s/kg** | Sin esto el proxy puede dar degradación negativa: aligerar por quemar gasolina mejora la vuelta y enmascara el desgaste. Calibrable por regresión en las primeras vueltas. |
| D8 | Vuelta de referencia del proxy | **mediana de los tiempos corregidos de las vueltas 1–3** | Neumático fresco. Usar el mínimo absoluto del stint arriesga elegir una vuelta atípica. |
| D9 | Umbral de "vuelta de caída" | **0.5** de degradación acumulada normalizada | Punto de cruce del 50 % de la vida útil. Configurable. |
| D10 | Consumo de combustible (simulación) | **~2.5 kg/vuelta** | Necesario para que la corrección por combustible (D7) sea entrenable y realista. |
| D11 | Detector de outliers | **mediana/MAD en ventana causal de 0.5 s, umbral 12·MAD, con piso de 0.5·σ_global** | El MAD local se anula en tramos quietos y confundiría los cambios de nivel (recta↔curva) con picos. El piso relativo a la dispersión global del canal lo evita. Ver sección 7. |
| D12 | Regularización de Ridge | **grid de α hasta 1000, recorte (`clip`) de features estandarizadas a ±6 σ y descarte de columnas constantes en train** | Con pocas vueltas (p. ej. 8) una feature casi constante en train se amplifica en test y hace explotar la predicción. Estas tres defensas lo evitan. |
| D13 | Granularidad de Ridge | **nivel ventana; las predicciones se agregan por vuelta** para compararlas con Kalman | Entrenar a nivel vuelta con ~65 features y ~40 filas es inestable. A nivel ventana hay miles de filas y el split por vueltas sigue evitando la fuga. |
| D14 | Acoplamiento físico del simulador | **la masa de combustible y la degradación afectan el tiempo de vuelta** (masa ⇒ aceleración/frenada; degradación ⇒ agarre en curva) | Sin esto, el tiempo de vuelta era plano y el proxy solo reflejaba la monotonía del combustible. Al modelar ambos, el proxy captura la **pérdida de agarre** (mecanismo real del desgaste) y la corrección de combustible tiene sentido físico. |
| D15 | Features de la ablación por circularidad | **excluir slip, temperatura, PSD, grados-segundo y `trabajo_friccion`** | `trabajo_friccion = Σ|slip|·carga·v·dt` **deriva del slip**; excluirlo es imprescindible para que la ablación sea válida (su nombre no contiene "slip"). |
| D16 | Diagnóstico de signos físicos | reportar **conteo individual y suma de coeficientes por grupo** | Con features muy correlacionadas los signos individuales no son concluyentes; la suma por grupo compensa cancelaciones. |
| D17 | Cobertura de bandas Kalman | **reportar sensibilidad a R** en vez de forzar 0.95 | Con ~10 vueltas de test la cobertura solo toma múltiplos de 0.1; perseguir 0.95 exacto sería sobreajuste. Se reporta MAE y cobertura para varios R. |
| D18 | Ruido de proceso del Kalman | **q_nivel = 1e-4, q_pendiente = 1e-5**; la varianza de predicción **incluye el ruido de proceso acumulado** (`F^h P F^h' + Σ F^j Q F^j'`) | El desgaste se acelera dentro del stint, así que la pendiente necesita ruido de proceso no despreciable para seguirla (con 1e-6 el MAE era 0.045; con 1e-5 baja a 0.020). Omitir el término acumulado subestimaba las bandas. |

**Unidades y rangos esperados por canal** (a documentar en el README):

| Canal | Unidad | Rango físico esperado |
|---|---|---|
| `temp_core_c` | °C | 60 – 120 |
| `pressure_psi` | psi | 20 – 35 |
| `wheel_load_n` | N | 0 – 15000 |
| `wheel_slip` | adimensional | 0 – ~0.5 (con picos; ver limpieza) |
| `dirty_level` | adimensional | 0 – 1 |
| `speed_kmh` | km/h | 0 – ~350 |
| `throttle`, `brake`, `steering` | adimensional | 0 – 1 / −1 – 1 |

---

## 2. Fuentes de datos: de dónde salen los CSV

**Decisión para la Etapa 1: se usa solo la fuente F1 (datos simulados).** No se extrae telemetría del juego todavía. Las fuentes F2, F3 y F4 quedan documentadas para fases posteriores. Cuando llegue ese momento, el cambio se limita a escribir un adaptador que convierta sus columnas al esquema del proyecto; el resto del pipeline no cambia.

Motivo: con datos simulados conoces la degradación verdadera, así que puedes validar limpieza, features y modelos antes de depender de archivos del juego.

| Fuente | Qué es | Tiene desgaste real | Cuándo usarla |
|---|---|---|---|
| **F1. Simulada** | Generada por `sim/generador.py` | Sí (la conoces por construcción) | Desde el primer día |
| **F2. Live Telemetry** | App de AC que guarda logs CSV por rueda | Sí, incluye `Tire wear (%)` (verificar columna y si es acumulado de sesión) | Primera captura real (alimenta Etapa 2) |
| **F3. Logger propio** | Script Python en Windows que lee la memoria compartida de AC | No (solo el proxy) | Etapa 3 (predicción en vivo) |
| **F4. Datasets públicos** | Vueltas de AC en Hugging Face (formato parquet) | No | Probar limpieza con datos reales y ruidosos |

### F1. Datos simulados (la base de la etapa)
- Los genera `sim/generador.py`. Cada ejecución produce:
  - Un CSV de telemetría en `data/raw/` con el esquema de la sección 3.
  - Un archivo aparte (`*_verdad.csv`) con la **degradación verdadera muestreada por muestra** (no solo por vuelta), para poder etiquetar por ventana.
- Usa semilla fija con `numpy.random.default_rng(seed)`: los resultados son reproducibles.
- Permite variar parámetros para simular neumáticos que se degradan rápido o lento, y **variar la fuerza del acoplamiento** entre degradación y slip/temperatura (ver sección 9, circularidad).

### F2. Live Telemetry (captura real con logs de AC) — *fase posterior*
Es la fuente real más útil para empezar, porque ya guarda CSV por rueda y además registra el desgaste.

1. Descarga la app desde GitHub (`albertowd/live-telemetry`) o desde Overtake.gg.
2. Descomprime el contenido en la carpeta principal de AC (la que contiene `acs.exe`), por ejemplo `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa`.
3. Abre AC, activa la app y en la ventana de opciones activa **Logging** (viene desactivado por defecto).
4. Maneja una sesión. Los logs se guardan al terminar.
5. Revisa `Documents/Assetto Corsa/logs/`:
   - `LiveTelemetry_EN.csv`: datos del motor de la sesión.
   - `LiveTelemetry_FL.csv`, `_FR.csv`, `_RL.csv`, `_RR.csv`: datos por rueda.
6. Copia los archivos a `data/raw/` (desde `/mnt/c/Users/<tu_usuario>/Documents/Assetto Corsa/logs/`).

**Pendiente de verificar:** abre un CSV y confirma los nombres exactos de las columnas (temperatura, presión, carga, slip, desgaste), la frecuencia de muestreo y, sobre todo, **si `Tire wear (%)` es acumulado de sesión o por stint** (cambia cómo se usa como etiqueta).

**Tarea:** escribir `sim/adaptador_live_telemetry.py` que una los 4 CSV por rueda con el de motor usando el tiempo como llave, y lo convierta al esquema del proyecto.

### F3. Logger propio (captura.py) — *fase posterior (Etapa 3)*
Se usa si quieres controlar la frecuencia y el formato, o si la app F2 no te sirve.

- Corre en **Windows** con Python desde python.org. La versión de Microsoft Store no permite acceder a la memoria compartida.
- Lee `acpmf_physics`, `acpmf_graphics` y `acpmf_static` (nombres para AC original; ACC usa los mismos nombres con otra estructura).
- Necesitas las definiciones de la estructura de memoria de AC (por ejemplo, el archivo `sim_info.py` de la comunidad) para interpretar los bytes.
- Escribe una fila por muestra en CSV con el esquema del proyecto.
- Nota: la memoria compartida de AC original **no expone el desgaste**, por eso F3 usa el proxy.
- Referencia: el proyecto `glama.ai/mcp/servers/khlg0s4evt` lee estas mismas memorias compartidas de AC en Windows (verificar que el enlace siga vivo).

### F4. Datasets públicos de Hugging Face (datos reales de AC) — *fase posterior*
Conjunto de datasets de vueltas de AC publicados por el usuario `Nasim435`, en formato parquet, con telemetría a alta frecuencia:

- Imola: https://huggingface.co/datasets/Nasim435/Imola-lap-data
- Nürburgring GP: https://huggingface.co/datasets/Nasim435/Nurburgring-GP-Lap-data
- Spa-Francorchamps: https://huggingface.co/datasets/Nasim435/spa-francorchamps-lap-data
- Silverstone GP: https://huggingface.co/datasets/Nasim435/Silverstone-GP-lap-data (licencia MIT)

Columnas que traen (según la vista previa): velocidad, RPM, acelerador, freno, dirección, aceleraciones, y por rueda (FL, FR, RL, RR) carga (`load_*`), slip (`slip_*`) y presión (`psi_*`), además de altura de suspensión, clima y combustible.

**Advertencias:**
- Los datasets **no traen desgaste**, así que sirven para probar limpieza y features, no para validar la predicción.
- Algunos valores de slip son muy grandes (p. ej. millones). Son candidatos perfectos para probar la limpieza de outliers, pero **revisa las unidades**: puede que `load_*` y `slip_*` no estén en N ni en unidades adimensionales.
- Revisa la licencia de cada dataset antes de usarlo en un informe.
- Su esquema es distinto al tuyo: necesitas un adaptador (ver tarea de mapeo en la sección 3).

---

## 3. Esquema de datos y adaptadores

Define el formato de los CSV antes de escribir código. Todas las fuentes (F1–F4) deben convertirse a este mismo esquema.

- [x] Columnas de tiempo y vehículo: `timestamp_s`, `lap`, `speed_kmh`, `throttle`, `brake`, `steering`, `fuel_kg`.
- [x] Por cada rueda (FL, FR, RL, RR): `temp_core_c`, `pressure_psi`, `wheel_slip`, `wheel_load_n`, `dirty_level`, y opcionalmente `wear_pct` (solo para fuentes que lo tengan).
- [x] **Etiqueta canónica:** `degradacion` ∈ [0,1] acumulada y monótona (ver D6 y sección 8). Para F1 vive en el archivo de verdad; para el resto se deriva.
- [x] Documentar **unidades y rangos esperados** (tabla de la sección 1) en el README.
- [x] Función de validación que rechace archivos con columnas faltantes o tipos incorrectos.
- [x] Dejar documentado en el README que el esquema es el contrato que cualquier fuente futura debe cumplir.
- [ ] *(Fase posterior)* Tabla de mapeo por fuente en `sim/mapeo_fuentes.yaml`: nombre original → nombre del proyecto.
- [ ] *(Fase posterior)* Adaptador para F2 (`sim/adaptador_live_telemetry.py`).
- [ ] *(Fase posterior)* Adaptador para F4 (`sim/adaptador_hf.py`), **con conversión explícita de unidades** por columna.

## 4. Generador de datos simulados (`sim/generador.py`)

- [x] Generar vueltas con un perfil de velocidad realista: rectas, frenadas y curvas, a la frecuencia objetivo (D1).
- [x] Modelar la degradación como una variable oculta que aumenta lentamente con cada vuelta, afectando slip (sube) y temperatura (sube con el tiempo de uso), y **reduciendo el agarre en curva** (la vuelta se alarga). El parámetro de acoplamiento es configurable.
- [x] Modelar el **consumo de combustible** (D10) como masa que baja con el tiempo, afectando aceleración/frenada (auto más liviano ⇒ más rápido), para que la corrección del proxy (D7) sea realista (D14).
- [x] Agregar ruido gaussiano por canal, offset de sensor, outliers aleatorios y huecos de datos.
- [x] Guardar en `data/raw/` el CSV de telemetría y, en un archivo aparte, la **degradación verdadera por muestra**.
- [x] Usar semilla fija (`numpy.random.default_rng(seed)`) y registrar versiones para reproducibilidad real.
- [x] Permitir variar parámetros: degradación rápida/lenta y acoplamiento fuerte/débil.

## 5. Adquisición y remuestreo a rejilla uniforme (`src/limpieza.py`, paso 0)

**Nuevo en v2.** Los CSV reales no vienen con `dt` perfectamente constante (jitter, drift de reloj, y sobre todo la unión de 4 CSV por rueda por tiempo). `sosfilt`, Welch y FFT **asumen fs constante**.

- [x] Ordenar por `timestamp_s` y detectar duplicados / saltos de tiempo.
- [x] **Remuestrear a rejilla uniforme** a la fs objetivo (D1), interpolando por rueda.
- [x] **Antialias antes de decimar**: si la fs de origen es mayor (p. ej. 333 Hz), aplicar un pasa-bajas < fs/2 de destino antes de bajar la frecuencia (`scipy.signal.resample_poly` o `decimate` lo hacen, pero hay que aplicarlo explícitamente si se interpola a mano).
- [x] Comprobar que el archivo resultante tiene `dt` constante (test).

## 6. Limpieza (`src/limpieza.py`)

- [x] Validar esquema y convertir tipos.
- [x] Marcar valores fuera de rango físico (tabla de la sección 1) como NaN. Los datasets de F4 sirven para calibrar estos rangos.
- [x] Detectar outliers por **ventana deslizante** con mediana y MAD (o filtro de Hampel). *No usar mediana/MAD global: como el desgaste crece durante la sesión, la mediana global está sesgada.*
- [x] Interpolar huecos cortos (hasta N muestras, definido en config); dejar marcados los largos. **Nunca interpolar a través de la frontera entre vueltas** (fabricarías datos de una vuelta con la adyacente).
- [x] Aplicar filtro pasa-bajas Butterworth en forma **SOS** con estado, causal (`sosfilt` + `sosfilt_zi`), para que sirva en tiempo real. Inicializar el estado (o quitar la tendencia inicial) para evitar el **transitorio de arranque**, que si no la detección de outliers confunde con picos. Verificar que la frecuencia de corte sea menor que Nyquist.
- [x] Normalizar **solo features** (no filtrado): guardar los parámetros de normalización ajustados **solo con train** para reutilizarlos. *No normalizar por min/max del archivo completo: en Etapa 3 no tendrías ese dato y además hay fuga temporal.*
- [x] Generar un registro de calidad: cuántos valores se corrigieron por tipo de problema.

**Conceptos de clase:** muestreo, aliasing, Nyquist, filtrado, SNR.

## 7. Segmentación y features (`src/features.py`)

- [x] Dividir la señal en ventanas de tamaño fijo (W = 2.0 s, hop = 1.0 s, D2) y también agrupar por vuelta.
- [x] Por ventana y rueda, calcular media, desviación estándar, máximo, RMS y energía.
- [x] Calcular el proxy de trabajo de fricción: suma de |slip| × carga × velocidad × dt.
- [x] Calcular grados-segundo por encima del umbral de temperatura (D4).
- [x] Calcular espectro con Welch sobre slip (`nperseg=128`, `noverlap=64`) y obtener potencia en bandas definidas.
- [x] Agregar las ventanas en features por vuelta (para el modelo a nivel de vuelta).
- [x] **Diseñar las funciones para recibir una ventana, no un archivo completo.** Esto es lo que permite reutilizarlas en la Etapa 3.

**Conceptos de clase:** ventanas, energía, transformada de Fourier, densidad espectral.

## 8. Etiquetas (`src/etiquetas.py`)

**Definición canónica (D6):** `degradacion` ∈ [0,1], acumulada y monótona. La **tasa** (%/vuelta) es su derivada.

Esta parte cambia según la fuente:

- **F1 (simulada):** la etiqueta es la degradación verdadera del generador, muestreada por muestra → escalar y etiquetar por ventana.
- **F2 (Live Telemetry):** si el CSV trae `Tire wear (%)`, úsalo como etiqueta real (`wear%/100`). Recordar verificar si es acumulado de sesión. Es la mejor opción disponible.
- **F3 y F4:** no tienen desgaste. Usa el proxy:
  - [x] Calcular el tiempo por vuelta.
  - [x] **Corregir por combustible** con D7 (`t_corr = t − k_fuel · kg`); calibrar `k_fuel` por regresión en las primeras vueltas.
  - [x] Definir la vuelta de referencia (D8: mediana de las vueltas 1–3 corregidas) y calcular el delta por vuelta.
  - [x] Suavizar el delta con media móvil o Savitzky-Golay.
  - [x] Imponer monotonía (`cummax`) y normalizar a 0–1 por vuelta.

En todos los casos:
- [x] Documentar qué etiqueta usaste y por qué.
- [x] En la simulación, **comparar el proxy contra la degradación verdadera** para medir qué tan bueno es (esto valida el proxy para la Etapa 3, donde solo tendrás proxy).

## 9. Modelos (`src/modelo.py`)

Se entrenan en **dos granularidades distintas**, y por eso se comparan al final a nivel de vuelta:

### Ridge (nivel ventana → escalar de degradación)
- [x] Construir la matriz X (features por ventana) y el vector y (degradación por ventana).
- [x] Ajustar `StandardScaler` **solo con datos de entrenamiento**.
- [x] Elegir alpha con validación cruzada temporal **agrupada por vuelta**: bloques contiguos de vueltas; ninguna ventana de una vuelta puede aparecer a la vez en train y test.
- [x] Guardar coeficientes y modelo entrenado.
- [x] **Verificación física:** los signos de los coeficientes deben concordar con la física (más slip / más carga / más temperatura → más degradación).
- [x] **Mitigación de circularidad:** entrenar y reportar además un modelo *ablacionado* sin features derivadas de slip/temperatura (y sin `trabajo_friccion`, que también deriva del slip, D15). Si el acople del generador es fuerte, el modelo completo tendrá un ajuste casi perfecto que **no** demuestra capacidad predictiva sobre AC real. Repetir con acople débil.

### Filtro de Kalman (nivel vuelta → seguimiento y predicción del escalar)
- [x] Definir el modelo de estado: nivel con tendencia (nivel = degradación acumulada, pendiente = tasa por vuelta).
- [x] Definir la observación: la etiqueta por vuelta (wear o proxy).
- [x] **Fijar Q y R a mano y reportar sensibilidad.** Con ~40 vueltas no se pueden estimar de forma fiable (EM sobreajustaría).
- [x] Implementar la forma recursiva: predicción y actualización por cada medición.
- [x] Imponer/mencionar la **monotonicidad** (la degradación no baja): restringir el nivel, o declararlo como limitación del modelo lineal.
- [x] Implementar predicción a k vueltas hacia adelante con **bandas de incertidumbre crecientes**.

### Comparación
- [x] Comparar ambos modelos **a nivel de vuelta** (agregar las predicciones de Ridge por vuelta): mismo split temporal para los dos.
- [x] Incluir baselines simples (predecir la media, o repetir el último valor) para tener referencia.

## 10. Evaluación (`src/evaluacion.py`)

- [x] Split temporal: entrenar con las primeras vueltas, probar con las siguientes. Nunca mezclar vueltas al azar.
- [x] Calcular MAE, RMSE y R² para cada modelo y cada baseline. *El R² solo es engañoso con series temporales y pocos puntos; repórtalo junto al MAE, no en solitario.*
- [x] Calcular el error en la vuelta de caída (D9): diferencia entre la vuelta predicha y la real donde la degradación supera el umbral. Es la métrica principal.
- [x] **Validar la cobertura de las bandas de Kalman:** comprobar que el intervalo al 95 % realmente cubre ≈ 95 %. Si no, las bandas son decorativas.
- [x] Prueba de robustez: agregar ruido al **input** (no a la etiqueta) con SNR decreciente y graficar el error contra el SNR.

**Conceptos de clase:** SNR, robustez frente al ruido.

## 11. Reporte (`src/reporte.py`)

- [x] Gráfica de señal cruda contra señal limpia.
- [x] Gráfica de espectro antes y después del filtro.
- [x] Gráfica de features por vuelta.
- [x] Gráfica de predicción contra real, con bandas de incertidumbre en Kalman.
- [x] Gráfica de error contra SNR.
- [x] Tabla de métricas.
- [x] **Trazabilidad:** incrustar el `config.yaml` usado y un hash del CSV de entrada.
- [x] Exportar todo a un HTML sencillo con las imágenes incrustadas. La versión interactiva es la Etapa 2.

## 12. Orquestación (`main.py`)

- [x] CLI con `argparse`: `python main.py --entrada data/raw/sim.csv --fuente sim`.
- [x] Flujo: adaptar fuente → remuestrear → limpiar → features → etiquetas → entrenar → evaluar → reporte.
- [x] Logging con el progreso de cada paso.
- [x] Guardar los resultados intermedios en `data/processed/`.
- [x] Leer todos los parámetros desde `config.yaml`.

## 13. Pruebas (`tests/`)

Escribe cada prueba junto con su módulo, no al final.

- [x] Validación de esquema rechaza archivos inválidos.
- [x] El **remuestreo antialias** atenúa un tono por encima de la Nyquist de destino (p. ej. 80 Hz desde 333 Hz a 100 Hz).
- [x] El remuestreo deja `dt` constante.
- [x] El filtro **reduce la varianza** del ruido **y conserva la amplitud de una senoidal en banda** (una prueba que solo mide varianza la pasa un filtro que devuelve ceros).
- [x] El filtro es causal: la salida en t no depende de muestras futuras.
- [x] Las features de una señal senoidal de amplitud conocida dan el valor esperado (RMS = A/√2) y el pico de Welch cae en la frecuencia correcta.
- [x] La división temporal no tiene fuga: ninguna vuelta aparece en train y test a la vez, y el escalador se ajusta solo con train.
- [x] Kalman converge sobre datos sintéticos sin ruido.
- [x] Kalman cubre la incertidumbre esperada sobre datos con ruido conocido.
- [x] El generador es determinista con la misma semilla.
- [x] Ridge da resultados reproducibles con la misma semilla.

## 14. Documentación

- [x] README con instalación, uso, esquema de datos, unidades, fuentes soportadas y supuestos.
- [x] Docstrings en las funciones públicas.
- [x] Registro de decisiones (por qué esta frecuencia de corte, esta ventana, este `k_fuel`…).
- [x] Lista de fuentes y licencias de los datos usados.
- [x] Declarar explícitamente la **limitación de circularidad** de los datos simulados.

## 15. Estructura del proyecto y dependencias

**Nuevo en v2.** Añadir esto antes de empezar a codificar.

```
PROYECTO/
  config.yaml
  requirements.txt        # o pyproject.toml
  README.md
  main.py
  data/
    raw/                  # CSV crudos (no versionar los grandes)
    processed/            # intermedios y modelos entrenados
    reports/              # HTML + figuras
  sim/
    generador.py
    adaptador_live_telemetry.py   # fase posterior
    adaptador_hf.py               # fase posterior
    mapeo_fuentes.yaml            # fase posterior
  src/
    limpieza.py           # incluye remuestreo (paso 0)
    features.py
    etiquetas.py
    modelo.py
    evaluacion.py
    reporte.py
  tests/
```

Dependencias: `numpy`, `scipy`, `pandas`, `scikit-learn`, `matplotlib`, `pyyaml`, `pytest`.

**Nota de entorno.** Correr el repo sobre `/mnt/c` en WSL2 es lento por el I/O cruzado Windows↔Linux. Mantén el repo en el filesystem de WSL (`~/proyecto`) y que los CSV grandes no vivan en `/mnt/c`. La captura real (F2/F3) sí corre en Windows.

---

## Proyectos y recursos similares (para revisar, no para copiar)

| Recurso | Qué ofrece | Para qué te sirve |
|---|---|---|
| [albertowd/live-telemetry](https://github.com/albertowd/live-telemetry) | App de AC que muestra y guarda telemetría de motor y ruedas en CSV, incluido desgaste (%) | Fuente F2 y referencia del formato de logs |
| [Live Telemetry en Overtake.gg](https://www.overtake.gg/downloads/live-telemetry.31666/) | Misma app, con descripción de los logs y su activación | Instrucciones de instalación y activación del logging |
| [decnet100/acr_telemetry](https://github.com/decnet100/acr_telemetry) | Grabador de telemetría a ~333 Hz para ACC y AC Rally, con exportación a CSV y SQLite | Referencia de diseño, documentación de campos (`docs/FIELDS.md`) y exportación |
| [glama.ai: AC race engineer](https://glama.ai/mcp/servers/khlg0s4evt) | Servidor que lee la memoria compartida de AC en Windows | Referencia para el logger propio (F3) y para evitar errores como la versión de Microsoft Store de Python (verificar enlace) |
| [gotzl/pyacc](https://github.com/gotzl/pyacc) | Acceso a la memoria compartida de ACC con ctypes | Referencia de patrones de lectura; es para ACC, no para AC original |
| [PyAccSharedMemory](https://pypi.org/project/pyaccsharedmemory/) | Lector de memoria compartida de ACC en Python | Referencia; tiene estructuras de ACC, no de AC |
| [srounce/winecarte](https://github.com/srounce/winecarte) | Puente de memoria compartida para AC bajo Proton en Linux | No aplica a tu caso con WSL2, solo si algún día corres AC en Linux nativo |
| Datasets de Nasim435 (ver F4) | Vueltas de AC en parquet | Pruebas de limpieza y adaptadores |

**Nota:** las librerías de ACC no sirven directamente para AC original porque las estructuras de memoria son distintas. Para AC original, usa las definiciones de `acpmf_*` de la comunidad.

---

## Orden de trabajo

1. Entorno, estructura de carpetas (sección 15), dependencias y `config.yaml` con las decisiones de la sección 1.
2. Esquema de datos + validación.
3. Generador simulado (F1), con degradación verdadera por muestra y consumo de combustible.
4. Remuestreo y limpieza (secciones 5 y 6).
5. Features (sección 7).
6. Etiquetas: proxy contra la degradación verdadera (sección 8).
7. Ridge (con ablación por circularidad).
8. Kalman.
9. Evaluación (incluida la cobertura de bandas).
10. Reporte.
11. `main.py`.
12. README y ajustes finales.

**Fase posterior:** adaptadores de F2, F3 y F4, y etiquetas con desgaste real de AC.

## Criterios para dar Etapa 1 por terminada

- Con datos simulados, el pipeline corre de principio a fin con un solo comando.
- Ridge y Kalman producen predicciones que se pueden comparar contra la degradación verdadera.
- El modelo ablacionado (sin slip/temperatura) está reportado y explica la circularidad.
- El error contra el SNR está graficado y se puede explicar.
- Los tests pasan (incluidos los de fuga temporal, antialias y cobertura de Kalman).
- El HTML de reporte se genera sin intervención manual y muestra el config y el hash de entrada.
