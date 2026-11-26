# Interfaz de escritorio (PySide6) — guía rápida

Este proyecto cuenta ahora con una **ventana nativa de escritorio** en lugar del
dashboard de navegador. El backend (FastAPI) se mantiene igual; la GUI es un
cliente más que se conecta a sus endpoints REST y WebSocket, sin dependencias
HTTP externas: usa `QNetworkAccessManager` y `QWebSocket` de Qt.

🐴: se quitó el lanzador de navegador, la pestaña «Telemetría», los endpoints
de dispersión/correlación y `/stint`; la GUI cubre lo útil con siete pestañas.

## Arrancar la aplicación

Opción A — doble clic:
```
ejecutar_app.bat
```
(por defecto abre la GUI de escritorio).

Opción B — terminal:
```bash
# Con el entorno activado:
python -m telemetria gui

# O directamente, sin activar el entorno:
.venv\Scripts\python.exe -m telemetria gui

# Subcomando equivalente (ambos hacen lo mismo):
python -m telemetria          # default: abre la GUI de escritorio
python -m telemetria gui      # explícito
```

La primera vez tarda unos segundos: levanta el backend uvicorn en segundo
plano, espera a que responda en `http://127.0.0.1:8000/health` y abre la
ventana.

## Flujo recomendado

0. Si es tu primera vez, pulsa **Guía rápida** en la barra superior. Se abre
   una ventana pequeña **no modal**: puedes dejarla abierta mientras recorres
   las pestañas. Explica los pasos y el significado de MAE, RMSE, SNR, outlier,
   PSD, bandas, α, Q/R y «subida del error».
1. Abre la pestaña **Sesiones**.
2. Elige `sim_test_99.csv` (el CSV demo ligero; `sim_42.csv` pesa ~334 MB) y
   pulsa **Cargar sesión seleccionada**.
3. Espera un momento: las demás pestañas se recargan automáticamente con la
   sesión nueva y muestran el espectro, las predicciones, el replay, etc.

Si aún no hay sesión cargada, las pestañas dependientes muestran
«Sin sesión activa. Carga un CSV en la pestaña 'Sesiones'» en lugar de errores
HTTP 404/409. Ese 404 inicial del backend es normal: significa que no hay
ninguna sesión activa todavía.

En **Espectro**, el selector de vuelta solo ofrece vueltas con al menos 8
muestras. Las vueltas finales muy cortas (por ejemplo, la vuelta 9 de
`sim_test_99.csv`, con 1 muestra) se omiten porque el cálculo de Welch no tiene
datos suficientes y antes provocaba un error 422.

## Modo archivo y modo vivo

El aviso superior dice siempre en qué modo estás y desactiva lo que no
corresponde, para que nunca parezca que puedes mezclar un CSV con datos en vivo:

- **Modo archivo** (el inicial y el que se activa al cargar un CSV): las
  pestañas de archivo están disponibles, pero el botón **Conectar telemetría
  (WS)** y la pestaña **En vivo** quedan desactivados.
- **Modo vivo**: se activa con el botón **Cambiar a modo vivo** o al iniciar una
  captura. Queda disponible solo **En vivo**; las pestañas que analizan
  archivos (**Sesiones**, **Espectro**, **Predicción**, **Taller de modelos**,
  **Robustez** y **Replay**) se desactivan. Para volver, pulsa **Cambiar a modo
  archivo**.

Esto es solo una separación de interfaz: no cambia ningún endpoint ni clave del
backend.

Toda la interfaz usa una única paleta clara definida en `paleta.py`, tanto para
Qt como para las gráficas pyqtgraph. No depende del modo nocturno del sistema:
no hay textos blancos sobre fondos claros.

## Cómo leer la interfaz

- **Ayuda siempre visible.** Arriba de cada pestaña hay un recuadro «Qué estás
  viendo» que explica para qué sirve esa pantalla y qué puedes hacer. No hay que
  abrir ningún menú ni consultar este documento para entenderlo.
- **Guía rápida y glosario.** El botón de la barra superior abre una ventana
  no modal con «Cómo empezar», «Qué significan las métricas» y «Cómo comparar
  señales en Replay». Los controles y las cabeceras llevan tooltips con las
  mismas definiciones, así que no hace falta memorizar siglas.
- **Resultados y parámetros separados.** En **Predicción** solo se leen
  resultados y un resumen de los parámetros usados. Todos los controles están
  en **Taller de modelos**: Q/R y monotonía de Kalman, alpha de Ridge, una tabla
  que compara «Guardado» con «En pantalla» y una lista de features con tooltip.
  Pulsa **Aplicar y recalcular** para actualizar las curvas de Predicción.
- **Métricas con nombre claro.** En Predicción se lee «Error medio (MAE)» y
  «Error grande (RMSE)», con la nota «Menor es mejor». En Robustez, «Error sin
  fallos» y «Subida del error ↑» sustituyen a `MAE base` y `Delta`. En Espectro,
  las franjas sombreadas llevan escrito **Baja**, **Media** y **Alta**.
- **Nombres comprensibles.** Los selectores muestran nombres como
  «Acelerador», «Freno» o «Deslizamiento FL (delantera izquierda)», con su
  unidad cuando aplica. Si dejas el ratón sobre una opción, el tooltip da una
  explicación más larga. Las claves internas (`throttle`, `wheel_slip_fl`, ...)
  siguen siendo las mismas en la API; solo cambia lo que se muestra.
- **Columnas de contexto ocultas.** `timestamp_s` es el eje del tiempo y `lap`
  es el agrupador de vueltas, por lo que no se ofrecen como «señal para dibujar»
  en **Espectro** ni en **Replay**.
- **Leyendas y colores.** Las gráficas de Espectro y Predicción llevan leyenda.
  En Replay, cada señal del comparador tiene un color fijo y distinto, asignado
  en el orden en que la marcaste (no por orden alfabético de la API).
- **Eje y cursor.** En el comparador de Replay puedes alternar entre
  **Tiempo de vuelta (s)** y **Progreso de vuelta (%)**. El eje Y dice la
  magnitud y su unidad (km/h, °C, N, psi o «mando»); al normalizar pasa a
  **Valor normalizado (0–1)** y la leyenda y el cursor recuerdan el valor
  original. Al pasar el ratón por Replay, Predicción o Espectro aparecen dos
  guías y una caja con la posición exacta y el valor de cada serie con su
  unidad; la caja cambia de lado cerca del borde derecho para no cortarse.
  **Ver toda la vuelta** restaura el zoom al rango completo.
- **Contexto al hacer zoom.** Bajo cada gráfica de Replay hay un **minimapa**
  con la vuelta completa. La franja sombreada es el **rango visible**, que
  también se escribe con números: «Viendo 1000.0–1500.0 s de 0.0–2999.0 s
  (17 %)». Puedes arrastrar la franja para moverte por la vuelta sin perder la
  referencia. Además, el zoom está **limitado a los datos reales**: ya no puedes
  arrastrar el plano hasta un punto donde la gráfica desaparece. El botón
  **Ver toda la vuelta** está tanto en el comparador como en el detalle.

## Comparar señales en Replay

La pestaña **Replay** tiene dos zonas:

1. **Comparar señales de la vuelta** (arriba). Elige una vuelta y marca varias
   señales a la vez. El atajo «Acelerador + freno» deja marcadas esas dos
   señales; también hay atajos para velocidad+slip y temperaturas por rueda, o
   puedes marcarlas una a una en la lista. La casilla **Normalizar señales**
   escala cada curva entre 0 y 1: es útil para comparar la *forma* de señales con
   unidades distintas (por ejemplo, acelerador en % y temperatura en °C); la
   leyenda y el cursor recuerdan el rango original. **Progreso de vuelta (%)**
   cambia el eje horizontal de segundos a porcentaje recorrido, **Diferencia
   A − B** dibuja una curva punteada con la resta cuando hay exactamente dos
   señales marcadas, y **Ver toda la vuelta** vuelve a encuadrar el eje tras
   hacer zoom. Todas las señales comparten el mismo eje temporal y el cursor
   sincronizado. La GUI pide solo unos 2–3 puntos por píxel (900–6000 según el
   ancho), guarda la vuelta en caché y vuelve a muestrear con LTTB al hacer zoom,
   sin repetir la petición. La etiqueta **Puntos dibujados** indica cuántos se
   muestran frente a cuántos se recibieron. El **minimapa** y la etiqueta
   «Viendo …» señalan la parte de la vuelta que estás inspeccionando.
2. **Detalle de una señal** (abajo). Muestra la señal original frente a la
   filtrada y los puntos descartados. Encima hay tres tarjetas: **Muestras
   válidas**, **Descartadas** y **Calidad (%)** (porcentaje de muestras marcadas
   como válidas). Cada tarjeta explica su significado al pasar el ratón.

Ambas zonas usan la misma vuelta seleccionada, pero peticiones distintas: el
comparador no pisa el gráfico de detalle.

## Estructura de la GUI (`telemetria/gui/`)

| Archivo | Qué hace |
|---------|----------|
| `main.py` | Punto de entrada: arranca backend + ventana |
| `paleta.py` | Paleta clara única aplicada a Qt (QPalette) y pyqtgraph; colores de serie y de banda. |
| `etiquetas_canales.py` | Traduce las claves de la API a nombres legibles y oculta las columnas de contexto. |
| `glosario.py` | Definiciones únicas de MAE, RMSE, R², cobertura, error de caída, SNR, outlier, PSD, bandas, α, Q/R/monotonía, restablecimiento, calidad, progreso, diferencia, cursor y modos para tooltips y guía. |
| `dialogo_ayuda.py` | «Guía rápida»: diálogo no modal con el paso a paso y el glosario. |
| `cliente_api.py` | Cliente REST (`QNetworkAccessManager`) + WebSocket (`QWebSocket`) nativos de Qt, sin hilos propios; emite señales y cachea las vueltas por sesión/vuelta/canales. |
| `reduccion.py` | Presupuesto de puntos según el ancho del gráfico y LTTB multicanal local para el zoom. No toca las claves JSON del backend. |
| `graficas.py` | Ayudas de gráficas: minimapa con rango limitado a los datos y cursor compartido con posición, unidades y valores. Lee cada serie en su abscisa real cuando las frecuencias difieren. |
| `parametros.py` | Valores por defecto, etiquetas y explicaciones de features compartidas por el Taller y Predicción; conserva las claves del backend. |
| `ventana_principal.py` | `QMainWindow`: barra de estado, aviso de modo, botón «Guía rápida», 7 pestañas con gating archivo/vivo y panel WS. |
| `vistas/vista_base.py` | Clase base de todas las pestañas; provee el bloque de ayuda superior (`agregar_ayuda()`). |
| `vistas/v_sesiones.py` | Lista de sesiones (CSV), cargar sesión, ver sesión activa. |
| `vistas/v_espectro.py` | Espectro de Welch (crudo vs. limpio) por canal. |
| `vistas/v_prediccion.py` | Resultados de Ridge y Kalman: entrenamiento frente a prueba, banda de Kalman, procedencia de la referencia, métricas ampliadas, importancias y cursor; recibe los parámetros desde el Taller. |
| `vistas/v_laboratorio.py` | «Taller de modelos»: todos los parámetros (Q/R/monotonía y alpha), tabla antes/después de la configuración y features con tooltips. |
| `vistas/v_robustez.py` | MAE vs SNR y simulador de fallo de sensores con evaluación individual y combinada separadas. |
| `vistas/v_replay.py` | Replay de una vuelta: comparador multi-señal con cursor, progreso %, diferencia A − B, minimapa/rango visible y ejes con unidades; detalle crudo vs. limpio con outliers y KPIs. Ambos usan `max_puntos` adaptativo y LTTB local. |
| `vistas/v_vivo.py` | Captura en vivo: iniciar/detener, estado, osciloscopio. |

## Pestañas disponibles

| # | Pestaña | Qué muestra | Endpoints usados |
|---|---------|-------------|------------------|
| 1 | **Sesiones** | CSV disponibles, cargar sesión, sesión activa | `GET/POST /api/sesiones/*` |
| 2 | **Espectro** | PSD de Welch por canal (crudo/limpio), bandas etiquetadas, ventana efectiva frente a solicitada y resolución por curva | `GET /api/telemetria/espectro` |
| 3 | **Predicción** | Ridge ajuste/prueba, Kalman con banda, referencia simulada o proxy, MAE/RMSE/R²/cobertura/error de caída e importancias | `POST /api/modelos/kalman/estimar`, `POST /api/modelos/ridge/ajustar` |
| 4 | **Taller de modelos** | Parámetros centralizados (Q/R/monotonía y α), antes/después de la config y features explicadas. Distingue α fijado, candidatos de CV y α aplicado | `GET/POST/DELETE /api/config`, `GET /api/modelos/features` |
| 5 | **Robustez** | Error frente al ruido (SNR), ablación individual por sensor y resultado combinado en secciones separadas | `POST /api/modelos/robustez`, `POST /api/modelos/sensores` |
| 6 | **Replay** | Comparador de varias señales (cursor, progreso %, diferencia A − B) + detalle crudo/limpio, outliers y tarjetas de calidad | `GET /api/telemetria/vuelta/{lap}` |
| 7 | **En vivo** | Captura desde AC o CSV, estado, osciloscopio | `POST/GET /api/vivo/*` |

## Coherencia de resultados (Fase 1)

### Ablación de sensores

La pestaña **Robustez** tiene una tabla de selección y dos experimentos. En
**Individual**, cada sensor se desconecta por separado y se re-entrena Ridge; la
tabla se ordena por subida del error y la gráfica muestra esa subida. En
**Combinado**, todos los sensores seleccionados se desconectan a la vez y el
resultado aparece solo en la sección B. El MAE combinado nunca se copia a las
filas individuales. La subida del error indica sensibilidad del modelo a perder
esa información, no una causa física.

### Espectro

La etiqueta bajo la gráfica distingue la ventana efectiva de Welch de la
ventana solicitada. Cuando la señal original y la filtrada usan ventanas
distintas, cada curva se dibuja con sus frecuencias y el cursor indica la
frecuencia propia de la serie. Si no hay suficientes muestras, la GUI lo dice
en lugar de mostrar una PSD inventada.

### Predicción

La curva discontinua de Ridge es el ajuste sobre entrenamiento; los puntos
grandes son la evaluación sobre prueba y son los únicos que alimentan las
métricas. La franja verde es la banda de incertidumbre de Kalman. La referencia
se nombra como verdad simulada o proxy, y se recuerda que el proxy es una
aproximación. R², cobertura y error de caída se muestran con su explicación; un
valor "No disponible" no significa un buen resultado. La sección de
importancias ordena los coeficientes de Ridge, distingue signos por color y
advierte que un coeficiente no demuestra causalidad.

### Alpha y parámetros

En el **Taller de modelos**, la columna «Guardado» de α muestra la lista de
candidatos de validación cruzada o el único valor fijado en `config.yaml`. La
columna «En pantalla» es el α que se aplica al recalcular. Alpha no se escribe
en `config.yaml`. Q, R y monotonía sí se pueden guardar como overrides;
**Restablecer valores de fábrica** descarta esos overrides y vuelve a los
valores originales sin tocar la sesión de datos.

El detalle técnico de esta fase está en
[`docs/MEJORAS_Y_HOJA_DE_RUTA.md`](docs/MEJORAS_Y_HOJA_DE_RUTA.md).

El panel superior permite conectar/desconectar el WebSocket de telemetría en
tiempo real (`/ws/telemetria`), solo en **modo vivo**; en modo archivo queda
desactivado a propósito.

En la pestaña **En vivo**, al iniciar una captura se abre automáticamente el
WebSocket `/api/vivo/stream`, que empuja JSON tipo `vivo` cada ~100 ms con el
estado del motor y la ventana reciente para el osciloscopio en tiempo real.

## Tecnologías

- **PySide6** (LGPL, open source): widgets de ventana nativa.
- **pyqtgraph**: gráficos rápidos para señales de telemetría.
- **QNetworkAccessManager**: peticiones REST nativas de Qt, asíncronas, sin
  cliente HTTP externo.
- **QWebSocket**: WebSocket nativo de Qt para datos en tiempo real.

## Qué se reutiliza del proyecto original

Todo el backend (`telemetria/api/`, FastAPI), el pipeline de procesamiento
(`telemetria/pipeline/`) y la captura en vivo (`telemetria/adquisicion/`)
quedan intactos en sus claves JSON; solo se reemplaza el frontend del navegador
por esta GUI de escritorio. Los únicos endpoints retirados son los que nadie
usaba (`/stint`, dispersión y correlación).

## Comprobación rápida

```bash
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

**199 tests** en total, de los cuales **43** son de humo de la GUI en modo
`offscreen`. Comprueban que arranca sin sesión, que se refresca al cargar una,
que las 7 pestañas tienen ayuda visible, que los selectores usan nombres
amables y ocultan las columnas de contexto, y que el comparador de Replay
dibuja varias señales (también normalizadas). También cubren la **Guía rápida**,
las tarjetas de calidad de Replay, las cabeceras claras de métricas y las
etiquetas de las bandas del espectro, además del orden estable de colores, el
eje de progreso, la curva de diferencia, el cursor en las gráficas, el
encuadre, el zoom limitado a los datos, la separación de modos, el Taller de
modelos, el presupuesto adaptativo, el zoom sin nueva petición, la caché de
vueltas, el minimapa, el rango visible y las unidades de los ejes. La Fase 1
añade cobertura para la ablación individual y combinada, la ventana efectiva de
Welch, el cursor con frecuencias por serie, las particiones de Ridge, la banda
de Kalman, R², cobertura, error de caída, importancias, la semántica de α y los
tooltips corregidos. Otros 4 tests comprueban la reducción LTTB (picos
compartidos y sin desalinear series).

Medición con el smoke real (`sim_test_99.csv`, vuelta 1): el payload de
`throttle + brake` baja de **94,0 KB / 5067 puntos** con el valor por defecto
del backend a **19,3 KB / 1023 puntos** con el presupuesto adaptativo de la
GUI. El zoom posterior solo recalcula puntos dibujados, sin volver a pedir la
vuelta.

## Mejora opcional

- Empaquetar en `.exe` con PyInstaller si se quiere distribuir sin instalar
  Python. Los WebSockets de telemetría y de captura viva ya están conectados a
  sus gráficos/paneles.
