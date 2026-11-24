# Interfaz de escritorio (PySide6) — guía rápida

Este proyecto cuenta ahora con una **ventana nativa de escritorio** en lugar del
dashboard de navegador. El backend (FastAPI) se mantiene igual; la GUI es un
cliente más que se conecta a sus endpoints REST y WebSocket.

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
  es el agrupador de vueltas. Aparecen en la lista de canales de **Telemetría**,
  pero no se ofrecen como «señal para dibujar» en **Espectro** ni en **Replay**.
- **Leyendas y colores.** Las gráficas de Espectro y Predicción llevan leyenda.
  En Replay, cada señal del comparador tiene un color fijo y distinto.

## Comparar señales en Replay

La pestaña **Replay** tiene dos zonas:

1. **Comparar señales de la vuelta** (arriba). Elige una vuelta y marca varias
   señales a la vez. El atajo «Acelerador + freno» deja marcadas esas dos
   señales; también hay atajos para velocidad+slip y temperaturas por rueda, o
   puedes marcarlas una a una en la lista. La casilla **Normalizar señales**
   escala cada curva entre 0 y 1: es útil para comparar la *forma* de señales con
   unidades distintas (por ejemplo, acelerador en % y temperatura en °C).
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
| `glosario.py` | Definiciones únicas de MAE, RMSE, SNR, outlier, PSD, bandas, α, Q/R y calidad para tooltips y guía. |
| `dialogo_ayuda.py` | «Guía rápida»: diálogo no modal con el paso a paso y el glosario. |
| `cliente_api.py` | Cliente REST (httpx) + WebSocket (QWebSocket). Todas las peticiones van a un hilo de fondo para no congelar la ventana. |
| `ventana_principal.py` | `QMainWindow`: barra de estado del backend, botón «Guía rápida», 8 pestañas y panel conectar/desconectar WebSocket. |
| `vistas/vista_base.py` | Clase base de todas las pestañas; provee el bloque de ayuda superior (`agregar_ayuda()`). |
| `vistas/v_sesiones.py` | Lista de sesiones (CSV), cargar sesión, ver sesión activa. |
| `vistas/v_telemetria.py` | Canales disponibles y área de gráfico (pyqtgraph). |
| `vistas/v_espectro.py` | Espectro de Welch (crudo vs. limpio) por canal. |
| `vistas/v_prediccion.py` | Predicción de degradación (Ridge + Kalman) con métricas. |
| `vistas/v_laboratorio.py` | Parámetros Q/R de Kalman, gestión de configuración y features. El alpha de Ridge está en Predicción. |
| `vistas/v_robustez.py` | MAE vs SNR y simulador de fallo de sensores. |
| `vistas/v_replay.py` | Replay de una vuelta: comparador multi-señal y detalle crudo vs. limpio con outliers y KPIs. |
| `vistas/v_vivo.py` | Captura en vivo: iniciar/detener, estado, osciloscopio. |

## Pestañas disponibles

| # | Pestaña | Qué muestra | Endpoints usados |
|---|---------|-------------|------------------|
| 1 | **Sesiones** | CSV disponibles, cargar sesión, sesión activa | `GET/POST /api/sesiones/*` |
| 2 | **Telemetría** | Canales disponibles, gráfico base | `GET /api/telemetria/canales` |
| 3 | **Espectro** | PSD de Welch por canal (crudo/limpio), bandas Baja/Media/Alta etiquetadas | `GET /api/telemetria/espectro` |
| 4 | **Predicción** | Degradación estimada (Ridge, Kalman), error medio (MAE) y error grande (RMSE) | `POST /api/modelos/kalman/estimar`, `POST /api/modelos/ridge/ajustar` |
| 5 | **Laboratorio** | Q/R de Kalman, guardar/restablecer config, features (α está en Predicción) | `GET/POST/DELETE /api/config`, `GET /api/modelos/features` |
| 6 | **Robustez** | Error frente al ruido (SNR), error sin fallos y subida del error ↑ al desconectar sensores | `POST /api/modelos/robustez`, `POST /api/modelos/sensores` |
| 7 | **Replay** | Comparador de varias señales + detalle crudo/limpio, outliers y tarjetas de calidad | `GET /api/telemetria/vuelta/{lap}` |
| 8 | **En vivo** | Captura desde AC o CSV, estado, osciloscopio | `POST/GET /api/vivo/*` |

El panel superior permite conectar/desconectar el WebSocket de telemetría en
tiempo real (`/ws/telemetria`). En la pestaña **Telemetría** hay un área de
texto que muestra los mensajes del WS (control, ping/pong, tramas binarias
decodificadas) y el gráfico se actualiza cuando llegan datos binarios.

En la pestaña **En vivo**, al iniciar una captura se abre automáticamente el
WebSocket `/api/vivo/stream`, que empuja JSON tipo `vivo` cada ~100 ms con el
estado del motor y la ventana reciente para el osciloscopio en tiempo real.

## Tecnologías

- **PySide6** (LGPL, open source): widgets de ventana nativa.
- **pyqtgraph**: gráficos rápidos para señales de telemetría.
- **httpx**: cliente HTTP para llamar al backend FastAPI.
- **QWebSocket**: WebSocket nativo de Qt para datos en tiempo real.

## Qué se reutiliza del proyecto original

Todo el backend (`telemetria/api/`, FastAPI), el pipeline de procesamiento
(`telemetria/pipeline/`) y la captura en vivo (`telemetria/adquisicion/`)
quedan intactos. Solo se reemplaza el frontend del navegador por esta GUI de
escritorio.

## Comprobación rápida

```bash
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Incluye 17 tests de humo de la GUI en modo `offscreen`: comprueban que arranca
sin sesión, que se refresca al cargar una, que las 8 pestañas tienen ayuda
visible, que los selectores usan nombres amables y ocultan las columnas de
contexto, y que el comparador de Replay dibuja varias señales (también
normalizadas). También cubren la **Guía rápida**, las tarjetas de calidad de
Replay, las cabeceras claras de métricas y las etiquetas de las bandas del
espectro.

## Mejora opcional

- Empaquetar en `.exe` con PyInstaller si se quiere distribuir sin instalar
  Python. Los WebSockets de telemetría y de captura viva ya están conectados a
  sus gráficos/paneles.
