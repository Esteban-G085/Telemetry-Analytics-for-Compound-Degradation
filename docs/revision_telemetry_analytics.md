# Revisión técnica — Telemetry-Analytics-for-Compound-Degradation

Repositorio: `Esteban-G085/Telemetry-Analytics-for-Compound-Degradation`

## Alcance de la revisión

**Revisado:** README, `plan_etapa1.md`, `plan_etapa3.md`, `config.yaml`, `motor_vivo.py`, `fuentes.py`, `acondicionador.py`, `vivo.py`.

**No revisado:** `plan_etapa2.md`, `limpieza.py`, `features.py`, `modelo.py`, `ac_info.py`, el frontend y los tests. Los puntos que dependen de ellos están marcados como hipótesis en la sección D.

---

## Resumen del flujo (cómo funciona hoy)

1. **Captura.** Lectura de la memoria compartida de AC (`acpmf_physics/graphics/static`) con `OpenFileMappingW` + `MapViewOfFile` en solo lectura, a ~333 Hz. En modo seco se reproduce un CSV por la misma ruta.
2. **Acondicionamiento causal.** Outliers por mediana/MAD con zero-order hold, Butterworth orden 4 a 20 Hz (SOS, forma II traspuesta) y decimación a 100 Hz.
3. **Features** (batch): ventanas de 2 s con salto de 1 s. Estadísticos por rueda, trabajo de fricción, grados-segundo (umbral 90 °C) y potencia de Welch por bandas sobre el slip.
4. **Etiqueta.** Verdad simulada, o proxy de tiempo de vuelta corregido por combustible.
5. **Modelos.** Ridge por ventana (agregado por vuelta) y Kalman de nivel + tendencia por vuelta.
6. **En vivo** (`MotorVivo`): degradación = `(pico − grip) / pico`, media de las cuatro ruedas por vuelta, proyección con Kalman. **Ridge no interviene.**

---

## A. Lo que el proyecto dice y el código no cumple

| # | El proyecto dice | El código hace | Dónde |
|---|---|---|---|
| A1 | El CSV de `LoggerVivo` es crudo y reprocesable en batch (D7) | Lo alimenta el bus, es decir, la señal ya filtrada y decimada. Al reprocesarlo, el batch aplica un segundo filtro y una segunda detección de outliers | `vivo.py` (`bus.suscribir(logger.registrar)`), `fuentes.py` |
| A2 | La decimación usa un acumulador temporal que respeta el jitter (D4) | Suma el `dt` nominal (1/333 s) en cada llamada y no usa los `timestamp_s` | `acondicionador.py` |
| A3 | Sin grip utilizable, la degradación cae al proxy de tiempos (D6) | Queda en NaN con modo `"none"` | `motor_vivo.py` |
| A4 | El README dice que el motor en vivo usa Ridge; el plan 1 dice que el `.joblib` sirve para la Etapa 3 | En el código revisado, Ridge no se carga ni se llama en vivo | `motor_vivo.py` |
| A5 | La degradación se deriva del grip (tabla §5 del plan 3) | Se calcula pero no se guarda. `grip_*` queda fuera del esquema, así que las sesiones de AC se graban sin etiqueta ni `_verdad.csv` | `motor_vivo.py` (`LoggerVivo`) |
| A6 | Las features se diseñaron para ventanas de 2 s (D2) | En vivo usan `vivo.ventana_s = 6`, que es la ventana del osciloscopio | `config.yaml`, `motor_vivo.py` |
| A7 | El plan 1 dice que la memoria de AC no expone desgaste y que F3 usa el proxy | La Etapa 3 usa `tyreWear` como señal de grip. Esa parte del plan 1 quedó desactualizada | `plan_etapa1.md` |
| A8 | `ritmo_hz` parece una frecuencia de reproducción | Solo actúa como interruptor: el ritmo real lo marcan los timestamps del CSV | `fuentes.py` (`FuenteCSV`) |

---

## B. Errores y riesgos de diseño

### Prioridad alta

**B1. El `pico` del grip es frágil.**
- El grip llega crudo: no está en `canales_filtrables()` ni en `canales_fisicos()`, así que pasa sin filtro, sin detección de outliers y con la decimación sin antialias.
- `pico = max(pico, grip)` nunca baja ni se reinicia al cambiar neumáticos. Un valor espurio fija el pico y sesga toda la sesión hacia una degradación mayor.
- Sugerencia: pico robusto (percentil alto de las primeras vueltas o de una ventana) y reinicio por stint.

**B2. Paquetes perdidos sin detectar.**
- `fs_entrada = 333` es fijo y nunca se mide.
- Si el hilo no alcanza ese ritmo, el filtro y el espaciado de salida dejan de coincidir con lo supuesto, sin aviso.
- Sugerencia: contar saltos de `packetId` (`pid − último − 1`) y exponerlos en `estado()`.

**B3. Un suscriptor que falla mata la captura.**
- `BusTiempoReal.publicar` llama a los suscriptores sin `try/except`.
- Si `_on_muestra` o `registrar` lanzan una excepción, rompe el `while` de `Fuente.run`. El hilo termina y solo queda el mensaje en `errores`.

### Prioridad media

**B4. Kalman sobre la media de las cuatro ruedas.**
- Una rueda que se degrada más queda enmascarada.
- La vuelta en curso entra como observación con el mismo `R` que una vuelta completa, aunque es una media parcial y ruidosa al inicio de la vuelta.
- El filtro se recalcula desde cero en cada llamada a `estado()`.

**B5. `estado()` es costoso (~10 Hz).**
- Reconstruye un `DataFrame` de 600 filas, ejecuta Welch, recalcula features y vuelve a filtrar el Kalman.
- `bus.ultimas(n)` copia el deque completo (hasta 12 000 dicts) antes de recortar.
- Sugerencia: `islice` sobre las últimas `n` muestras y un Kalman incremental.

**B6. `iniciar()` crea el CSV antes de saber si la fuente arranca.**
- Con AC apagado, `FuenteVivo._preparar` falla, pero el logger ya creó `ac_<fecha>.csv` con solo la cabecera. `cerrar()` borra el `_verdad` vacío, no el CSV principal, y `listar()` lo muestra.
- Si `_resolver_archivo` falla en modo seco, el bus nuevo ya reemplazó al anterior, pero `motor` sigue apuntando a la sesión previa.
- `sleep(0.05)` no garantiza que `_preparar` haya terminado. Un error al abrir la memoria puede llegar después de que la respuesta ya dijo «activo».

**B7. El filtro arranca con estado cero.**
- No se usa `sosfilt_zi` (el plan 1 lo pedía). Las primeras salidas suben desde 0 durante ~0.1–0.2 s.
- Esas muestras llegan al CSV y al osciloscopio, aunque el motor las ignora por usar ventanas largas.

**B8. La banda «alta» (15–40 Hz) cae en la zona de transición del filtro.**
- Respuesta del Butterworth orden 4 a 20 Hz: ≈ −0.4 dB a 15 Hz, −3 dB a 20 Hz, ≈ −14 dB a 30 Hz, ≈ −24 dB a 40 Hz.
- La potencia de esa banda depende de la pendiente del filtro. Si `corte_hz` cambia (el Laboratorio lo permite), la feature cambia de significado sin aviso.

### Prioridad baja

**B9.** El Welch en vivo descarta los NaN y concatena lo que queda, lo que crea discontinuidades en la señal.

**B10.** `_por_vuelta` se sobrescribe si `lap` retrocede (por ejemplo, al reiniciar la sesión).

**B11.** `_detener_sin_lock` cierra el logger tras `join(timeout=1.5)` sin comprobar que el hilo terminó. Si sigue escribiendo, `registrar` lanza `ValueError` sobre un archivo cerrado, lo que activa B3.

---

## C. Validación y documentación

- **Circularidad.** Ridge solo se entrenó con simulación acoplada. El acople fuerte hace que el ajuste casi perfecto (MAE 0.0023) no demuestre capacidad predictiva sobre AC real. Faltan los adaptadores F2/F4 y una corrida con datos reales.
- **Acople débil.** El plan 1 marca «repetir con acople débil» como hecho, pero el README lo lista como pendiente. Conviene dejar esa corrida documentada.
- **Cobertura de Kalman = 1.00.** El plan §10 pide ≈ 95 %. D17 lo relaja a reportar la sensibilidad a R, pero en la simulación la etiqueta casi no tiene ruido, así que el 1.00 no dice mucho. Sugerencia: calibrar `R` con el error del proxy (MAE 0.027).
- **Plan 3.** La tabla de decisiones salta de D10 a D12 y tiene un `**` suelto en D10.
- **Tests que faltan:** logger → batch, pérdida de paquetes, detener bajo carga y features no vacías en modo seco.

---

## D. Por verificar (hipótesis, no confirmadas)

1. **`features` casi siempre `None` en modo seco.** `MotorVivo._features` exige 600 muestras todas finitas. El CSV simulado inyecta outliers (`outliers_prop`) y huecos (`huecos_prop`), que acaban como NaN. Comprobación: contar cuántas veces `estado()["features"]` no es `None`.
2. **`FuenteVivo.detener()` llama a `memoria.cerrar()` desde otro hilo** mientras el hilo de captura puede estar leyendo. Podría dar un acceso a memoria inválido. Requiere revisar `ac_info.py`.
3. **Los timestamps de AC parecen ser de lectura** (`perf_counter`) y no del tick de la física. Requiere revisar `ac_info.py`.
4. **Doble filtrado al reprocesar capturas** (A1). El efecto en la ganancia a 20 Hz (−6 dB en lugar de −3 dB) es teórico; conviene medirlo con una captura real.

---

## E. Orden sugerido de trabajo

1. **Logger crudo y con etiqueta (A1, A5).** Registrar la fila cruda desde `Fuente._emitir`, antes del acondicionador, y guardar `grip_*` y `degradacion` como columnas extra.
2. **Pico robusto y reiniciable (B1).**
3. **Robustez del bus y la fuente (B2, B3, B11).** `try/except` en los suscriptores, conteo de `packetId` perdidos y comprobar que el hilo terminó antes de cerrar el logger.
4. **Fallback al proxy (A3)**, o eliminar esa afirmación del plan.
5. **Decimación con timestamps reales (A2).**
6. **Documentación (A4, A6, A7, C).** Corregir README y planes.
7. **Rendimiento (B4, B5, B6)** y el resto de la prioridad baja.

---

## F. Checklist

- [ ] A1 — Logger registra la señal cruda
- [ ] A2 — Decimación basada en timestamps
- [ ] A3 — Fallback al proxy implementado o retirado del plan
- [ ] A4 — README: aclarar el rol de Ridge en vivo
- [ ] A5 — Guardar `grip_*` y `degradacion` en las capturas de AC
- [ ] A6 — Decidir la ventana de features en vivo
- [ ] A7 — Actualizar el plan 1 (grip en vez de «AC no expone desgaste»)
- [ ] A8 — Renombrar o documentar `ritmo_hz`
- [ ] B1 — Pico del grip robusto y reiniciable
- [ ] B2 — Contar `packetId` perdidos
- [ ] B3 — Proteger los suscriptores del bus
- [ ] B4 — Kalman por rueda o con `R` ajustado en la vuelta parcial
- [ ] B5 — Optimizar `estado()` y `bus.ultimas`
- [ ] B6 — Crear el CSV solo cuando la fuente arrancó
- [ ] B7 — Inicializar el filtro con `sosfilt_zi`
- [ ] B8 — Documentar la dependencia de la banda alta con `corte_hz`
- [ ] B9–B11 — Prioridad baja
- [ ] C — Validación con datos reales y tests faltantes
- [ ] D — Verificar las cuatro hipótesis
