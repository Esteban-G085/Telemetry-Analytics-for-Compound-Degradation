# Mejoras de claridad externa y hoja de ruta

Este documento sigue la **Fase 1** del plan de claridad externa, ejecutada en la
rama `feature/ui-claridad-externa`. El objetivo es que los resultados de
Telemetry Analytics se puedan entender, reproducir y citar sin reconstruir la
aplicación ni cambiar los algoritmos científicos.

## Principios de la fase

- La GUI y el backend siguen siendo PySide6, pyqtgraph y FastAPI.
- No se eliminan funcionalidades ni se rompen CSV, REST, WebSocket ni captura en vivo.
- No se modifican las etiquetas de entrenamiento ni las métricas para obtener mejores cifras.
- No se presenta una transformación visual como un cálculo científico.
- Los datos originales y los resultados publicados por el backend se conservan.
- El contrato REST existente sigue funcionando: las claves nuevas se añaden, no sustituyen.

## Bloques completados

### 1. Ablación individual y combinada de sensores

Antes la GUI copiaba un único MAE conjunto a todas las filas de sensores. Eso
hacía imposible distinguir "qué pasa si falla este sensor" de "qué pasa si fallan
varios a la vez".

Cambios:

- `analisis.sensores()` acepta `modo="combinado"` por defecto y `modo="individual"`.
- Se calcula **un único baseline temporal** con el mismo `tr`/`te` para todos los experimentos de una petición.
- En modo individual, cada sensor se evalúa en su propio re-entrenamiento; el MAE de una fila nunca se deriva de la evaluación conjunta.
- En modo combinado se mantiene el contrato histórico: `caidos`, `mae_base`, `mae`, `delta`, `columnas_quitadas`, etc.
- La respuesta nueva incluye `modo`, `baseline`, `resultados` y `error` por sensor. Las claves planas solo se rellenan en modo combinado.
- `POST /api/modelos/sensores` acepta `modo` con valores `combinado` o `individual`.
- `ApiClient.sensores(caidos=None, modo=None)` envía `modo` cuando se indica.
- La pestaña Robustez separa la selección de sensores, la tabla individual ordenada por subida del error, la gráfica de barras y una sección independiente para el resultado combinado.
- La interfaz advierte explícitamente que la subida del error mide sensibilidad del modelo a perder información, no causalidad ni importancia física.

Pruebas: `tests/test_api_modelos_extra.py` y `tests/test_gui.py`.

### 2. Resolución real de Welch

Antes `nperseg` podía ser el valor solicitado aunque la señal tuviera menos muestras, y la curva cruda se dibujaba con las frecuencias de la curva filtrada.

Cambios:

- `nperseg` en la respuesta de `espectro()` es el tamaño **efectivo** usado por Welch.
- `nperseg_solicitado` conserva el valor pedido por la GUI o `config.yaml`.
- Se añaden `n_muestras_limpio`, `delta_f`, `nperseg_crudo`, `n_muestras_crudo`, `delta_f_crudo` y `freqs_crudo`.
- Si una señal no tiene muestras suficientes, sus datos de PSD quedan a `null` en lugar de inventarse frecuencias.
- `CursorGrafico.establecer_datos(..., x_por_serie=...)` permite leer cada curva en su abscisa real. Es necesario cuando crudo y limpio usan ventanas distintas.
- La pestaña Espectro muestra la ventana efectiva, la solicitada y la resolución de cada curva. El cursor indica la frecuencia propia de la serie cuando difiere de la referencia.

No se modifican las frecuencias de las bandas para forzar resultados. No se cambia el filtro ni el cálculo de la PSD.

Pruebas: `tests/test_analisis_espectro.py`, `tests/test_coherencia_api.py`, `tests/test_api_rest.py` y `tests/test_gui.py`.

### 3. Coherencia de Predicción

Antes una sola curva mezclaba ajuste y evaluación, no se distinguía la procedencia de la referencia y las importancias no tenían explicación.

Cambios en el backend:

- `ridge_por_vuelta()` añade `laps_train`, `pred_train`, `n_laps_train` y `n_laps_test`.
- `kalman_por_vuelta()` añade conteos de entrenamiento y prueba.
- `_referencia()` añade `referencia_usada`, con valores `verdad_simulada` o `proxy`.
- Las respuestas incluyen `cobertura`, `error_caida` e `importancias` cuando el backend las calcula.

Cambios en la GUI:

- Ridge se dibuja con dos estilos: ajuste sobre entrenamiento y evaluación sobre prueba. Las métricas se calculan solo sobre la prueba.
- Kalman muestra `banda_inf` y `banda_sup` mediante `FillBetweenItem`, con la banda señalada como incertidumbre del filtro.
- La referencia se etiqueta como verdad simulada o proxy. El proxy se presenta como aproximación, no como medición directa del desgaste.
- La tabla incorpora MAE, RMSE, R², cobertura de bandas y error de caída. Los valores no disponibles se escriben como "No disponible", no como cero.
- La sección de importancias permite ordenar por magnitud, coeficientes positivos o negativos, distingue el signo con color y explica que un coeficiente no demuestra causalidad.
- Las vueltas de entrenamiento y prueba se muestran en la etiqueta de evaluación.

Pruebas: `tests/test_gui.py`, `tests/test_coherencia_api.py`, `tests/test_modelo.py`, `tests/test_evaluacion.py` y `tests/test_features.py`.

### 4. Tooltips de parámetros y semántica de Alpha

Cambios:

- `ETIQUETAS_PARAMETROS` usa el glosario `kalman_monotono` para la casilla de monotonía.
- `estado_alpha(config)` distingue candidatos de validación cruzada, alpha fijado en configuración y alpha aplicado al experimento.
- `parametros_desde_config()` ya no toma el primer elemento de una lista múltiple como alpha guardado.
- La tabla del Taller muestra "validación cruzada (n candidatos)" cuando procede.
- `Restablecer valores de fábrica` elimina los overrides y vuelve a `config.yaml`; no afecta a la sesión de datos.
- Alpha no se escribe en `config.yaml`: afecta al recálculo actual. Q, R y monotonía sí se guardan como overrides del modelo.
- El glosario incorpora R², cobertura, error de caída, Kalman monótono y restablecimiento de fábrica, y amplía la definición de alpha.

Pruebas: `tests/test_gui.py`.

## Contratos y compatibilidad

| Superficie | Cambio | Compatibilidad |
|---|---|---|
| `POST /api/modelos/sensores` | Nuevo campo opcional `modo`, con valor por defecto `combinado`. Respuesta con `modo`, `baseline` y `resultados`. | Las claves planas siguen presentes en modo combinado. |
| `GET /api/telemetria/espectro` | `nperseg` pasa a ser el valor efectivo. Se añaden `nperseg_solicitado` y metadatos por serie. | Las claves `freqs`, `psd_limpio_db` y `psd_crudo_db` conservan su significado. |
| `ApiClient.sensores()` | Nuevo argumento opcional `modo`. | Llamadas sin `modo` siguen funcionando. |
| `CursorGrafico.establecer_datos()` | Nuevo argumento opcional `x_por_serie`. | Las llamadas existentes no cambian. |
| Predicción | Nuevas claves de partición, referencia, cobertura e importancias. | Las claves anteriores (`pred`, `metricas`, etc.) siguen presentes. |

## Verificación

Comandos ejecutados desde la raíz del repositorio con `.venv\Scripts\python.exe`:

```bash
python -m pytest tests/test_gui.py -q
python -m pytest tests/test_api_modelos_extra.py tests/test_analisis_espectro.py tests/test_api_rest.py tests/test_coherencia_api.py tests/test_modelo.py tests/test_evaluacion.py tests/test_features.py tests/test_gui.py -q
python -m pytest -q
```

Resultados:

- GUI: `43 passed`.
- Conjunto parcial de Fase 1: `104 passed`.
- Suite completa: `199 passed`.

Se corrigió durante la fase el fallo del gráfico horizontal de importancias: pyqtgraph no acepta una lista de colores en `brush` de `BarGraphItem`, así que se dibuja un grupo de barras por signo con un `QBrush` válido.

## Fuera de alcance y trabajo posterior

Esta fase no modifica la adquisición, el acondicionador causal, el generador, las etiquetas ni los modelos. Las cuestiones abiertas de `docs/revision_telemetry_analytics.md`, en particular el logger crudo con etiqueta, el pico del grip, la pérdida de paquetes y la validación con datos reales, siguen pendientes y se abordan en fases posteriores. Ninguna de ellas se ha resuelto aquí de forma implícita.
