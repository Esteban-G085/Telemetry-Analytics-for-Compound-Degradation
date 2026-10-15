# Predicción de degradación de neumáticos (Etapa 1)

Pipeline **offline** para predecir la degradación de neumáticos a partir de telemetría,
pensado para Assetto Corsa (AC). Esta etapa trabaja sobre **CSV** y valida toda la
lógica (limpieza → features → modelos → evaluación → reporte) antes de añadir
complejidad.

El diseño completo está en [`plan_etapa1.md`](plan_etapa1.md).

## Hoja de ruta

| Etapa | Qué es | Estado |
|---|---|---|
| **1 · Pipeline offline** | Limpieza, features, Ridge y Kalman sobre CSV (fuente simulada F1). | Implementada |
| **2 · Dashboard** | Señal cruda vs. limpia, parámetros ajustables y resultados de predicción. | Pendiente |
| **3 · Tiempo real** | Captura desde AC y predicción en ventana deslizante. | Pendiente |

La Etapa 1 ya está preparada para la 3: las features se calculan **por ventana**, el
filtro es **causal** (guarda su estado) y los parámetros de escalado quedan en el modelo.

## Requisitos

```bash
python -m pip install -r requirements.txt
```

Probado con Python 3.11, numpy 2.x, scipy 1.15, pandas 3.x y scikit-learn 1.9.

## Estructura

```
PROYECTO/
├── config.yaml               # todas las decisiones (sección 1 del plan)
├── requirements.txt
├── plan_etapa1.md
├── main.py                   # orquestación (CLI)
├── conftest.py               # pytest: raíz en sys.path
├── data/
│   ├── raw/                  # CSV crudos + *_verdad.csv (verdad simulada)
│   ├── processed/            # señal limpia (csv.gz), importancias.csv, modelo_ridge.joblib
│   └── reports/              # reporte HTML autocontenido
├── sim/
│   └── generador.py          # fuente F1: genera telemetría + degradación real
├── src/
│   ├── config.py             # esquema y carga de config
│   ├── limpieza.py           # remuestreo, validación, outliers, filtro
│   ├── features.py           # features por ventana
│   ├── etiquetas.py          # etiqueta canónica y proxy
│   ├── modelo.py             # Ridge y Kalman
│   ├── evaluacion.py         # métricas y robustez
│   └── reporte.py            # figuras + HTML
└── tests/                    # 48 tests
```

## Uso

Genera datos simulados, corre el pipeline completo y escribe el reporte:

```bash
python main.py
```

Procesa un CSV existente (busca `<nombre>_verdad.csv` al lado para validar):

```bash
python main.py --entrada data/raw/sim_42.csv
```

Opciones: `--config`, `--salida`, `--semilla`, `-v`.

Tests:

```bash
python -m pytest -q
```

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
| **F1. Simulada** | `sim/generador.py` (código propio) | Sí, por construcción | Usada en Etapa 1 |
| **F2. Live Telemetry** | App de AC que guarda logs CSV por rueda | Sí (`Tire wear %`) | Etapa 2 |
| **F3. Logger propio** | Script Python sobre la memoria compartida de AC | No (solo proxy) | Etapa 3 |
| **F4. Datasets públicos** | Vueltas de AC en Hugging Face (parquet) | No | Pruebas de limpieza |

En la Etapa 1 se usa **solo F1** (datos propios, sin licencia externa). F2–F4 se
usarán en fases posteriores; hay que **revisar la licencia de cada dataset** antes de
publicar resultados con ellos (el dataset de Silverstone GP es MIT). El detalle está
en `plan_etapa1.md`, sección 2.

## Esquema de datos

Cualquier fuente (F1…F4) debe producir estas columnas (el contrato está en
`src/config.py`):

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

Proxy vs. verdad: correlación **0.998**, MAE 0.027. Error en la vuelta de caída: **0**.
El Kalman lineal queda por detrás de Ridge porque la degradación simulada se acelera
al final del stint (curva de caída no lineal); aun así se mantiene en ~0.02 subiendo
`q_pendiente` (1e-5) para que la pendiente siga esa aceleración. La cobertura de las
bandas al 95 % da 1.00 (bandas conservadoras: la observación es la degradación
verdadera, casi sin ruido) y se reporta la sensibilidad a R en el HTML.

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
