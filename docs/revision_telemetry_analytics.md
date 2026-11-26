# Revisión técnica — Telemetry-Analytics-for-Compound-Degradation

Repositorio: `Esteban-G085/Telemetry-Analytics-for-Compound-Degradation`

## Alcance de la revisión

**Revisado:** README, `plan_etapa1.md`, `plan_etapa3.md`, `config.yaml`, `motor_vivo.py`, `fuentes.py`, `acondicionador.py`, `vivo.py`.

**No revisado en la revisión original:** `plan_etapa2.md`, `limpieza.py`, `features.py`, `modelo.py`, `ac_info.py`, el frontend y los tests. Los puntos que dependen de ellos están marcados como hipótesis en la sección D. En la Fase 2 se revisaron además los tests, el modelo Kalman y la GUI PySide6; el frontend Vite/uPlot ya no está en el repositorio.

---

## Resumen del flujo (cómo funciona hoy)

1. **Captura.** Lectura de la memoria compartida de AC (`acpmf_physics/graphics/static`) con `OpenFileMappingW` + `MapViewOfFile` en solo lectura, a ~333 Hz. En modo seco se reproduce un CSV por la misma ruta.
2. **Acondicionamiento causal.** Outliers por mediana/MAD con zero-order hold, Butterworth orden 4 a 20 Hz (SOS, forma II traspuesta) y decimación a 100 Hz.
3. **Features** (batch): ventanas de 2 s con salto de 1 s. Estadísticos por rueda, trabajo de fricción, grados-segundo (umbral 90 °C) y potencia de Welch por bandas sobre el slip.
4. **Etiqueta.** Verdad simulada, o proxy de tiempo de vuelta corregido por combustible.
5. **Modelos.** Ridge por ventana (agregado por vuelta) y Kalman de nivel + tendencia por vuelta.
6. **En vivo** (`MotorVivo`): degradación = `(pico − grip) / pico`, media de las cuatro ruedas por vuelta, proyección con Kalman. **Ridge no interviene.**

---

## A. Lo que el proyecto decía y el código no cumplía

Estado actualizado en la Fase 2: las ocho entradas están resueltas en código o
cerradas como decisión de diseño. Se conservan para explicar por qué los planes
cambiaron.

| # | El proyecto decía | El código hacía | Dónde | Estado en Fase 2 |
|---|---|---|---|---|
| A1 | El CSV de `LoggerVivo` es crudo y reprocesable en batch (D7) | El bus alimentaba la señal ya filtrada y decimada; reprocesarla aplicaría un segundo filtro | `vivo.py`, `fuentes.py` | **Resuelto.** `LoggerVivo` se suscribe a `Fuente.suscribir_crudo`, antes del acondicionador. Cubierto por `test_captura_cruda_reprocesable_en_batch`. |
| A2 | La decimación usa un acumulador temporal que respeta el jitter (D4) | Sumaba el `dt` nominal en cada llamada | `acondicionador.py` | **Resuelto.** El acumulador usa `timestamp_s`, con el `dt` nominal solo como respaldo. |
| A3 | Sin grip utilizable, la degradación cae al proxy de tiempos (D6) | Queda en NaN con modo `"none"` | `motor_vivo.py` | **Cerrado como decisión D11.** Se retiró la afirmación del plan; no se mezclan proxy y grip. |
| A4 | El README decía que el motor en vivo usa Ridge y que el `.joblib` sirve para la Etapa 3 | Ridge no se carga ni se llama en vivo | `README.md`, `motor_vivo.py` | **Resuelto en docs.** README §Etapa 3 dice explícitamente «Ridge no interviene en vivo» y el artefacto ya no se presenta como parte de la captura. |
| A5 | La degradación se deriva del grip pero no se guarda | `grip_*` quedaba fuera del esquema y no había `_verdad.csv` | `motor_vivo.py` (`LoggerVivo`) | **Resuelto.** `LoggerVivo.COLUMNAS_EXTRA` incluye `packetId`, `grip_*` y `degradacion`; no se genera `_verdad.csv`. |
| A6 | Las features se diseñaron para ventanas de 2 s (D2) | En vivo usaba `vivo.ventana_s = 6` | `config.yaml`, `motor_vivo.py` | **Resuelto.** `vivo.ventana_s = 2.0` y `MotorVivo.W == 200`; `test_features_no_vacias_con_ventana_2s`. |
| A7 | El plan 1 decía que la memoria de AC no expone desgaste y que F3 usa el proxy | La Etapa 3 usa `tyreWear` como grip | `plan_etapa1.md` | **Resuelto en docs.** Nota D6 actualizada y corregida la sección 8 de etiquetas en esta fase. |
| A8 | `ritmo_hz` parece una frecuencia de reproducción | Solo actúa como interruptor: el ritmo real lo marcan los timestamps | `fuentes.py` (`FuenteCSV`) | **Documentado.** El docstring de `FuenteCSV` lo describe como interruptor conservado por compatibilidad. |

---

## B. Errores y riesgos de diseño

> En cada apartado, la nota *Estado* describe la situación actual en Fase 2; la
> lista de debajo reproduce el diagnóstico original y está redactada en su
> tiempo verbal.

### Prioridad alta

**B1. El `pico` del grip es frágil.** *Sigue pendiente.* El código usa
`pico = max(pico, max(validos))`: no hay P95 ni detección de cambio de
neumáticos. Solo se limpia la historia cuando la vuelta retrocede (B10).
- El grip llega crudo: no está en `canales_filtrables()` ni en `canales_fisicos()`, así que pasa sin filtro, sin detección de outliers y con la decimación sin antialias.
- `pico = max(pico, grip)` nunca baja ni se reinicia al cambiar neumáticos. Un valor espurio fija el pico y sesga toda la sesión hacia una degradación mayor.
- Sugerencia: pico robusto (percentil alto de las primeras vueltas o de una ventana) y reinicio por stint.

**B2. Paquetes perdidos sin detectar.** *Resuelto.* `FuenteVivo._siguiente`
cuenta los saltos de `packetId` y mide `fs_medida`; `VivoSesion.estado()` expone
ambos junto a `errores_subs`, y la pestaña En vivo los muestra. Pruebas:
`test_ac_cuenta_paquetes_perdidos`, `test_estado_incluye_diagnostico` y
`test_estado_refleja_diagnostico_no_cero`.
- `fs_entrada = 333` es fijo y nunca se mide.
- Si el hilo no alcanza ese ritmo, el filtro y el espaciado de salida dejan de coincidir con lo supuesto, sin aviso.
- Sugerencia: contar saltos de `packetId` (`pid − último − 1`) y exponerlos en `estado()`.

**B3. Un suscriptor que falla mata la captura.** *Resuelto.*
`BusTiempoReal.publicar` y `Fuente._emitir` envuelven cada suscriptor en
`try/except` y contabilizan los fallos (`errores_subs`,
`errores_subs_crudos`). Prueba: `test_detener_bajo_carga`.
- `BusTiempoReal.publicar` llama a los suscriptores sin `try/except`.
- Si `_on_muestra` o `registrar` lanzan una excepción, rompe el `while` de `Fuente.run`. El hilo termina y solo queda el mensaje en `errores`.

### Prioridad media

**B4. Kalman sobre la media de las cuatro ruedas.** *Sigue pendiente.* El
estado y la predicción siguen siendo agregados; no hay Kalman por rueda ni `R`
ampliado para la vuelta parcial.
- Una rueda que se degrada más queda enmascarada.
- La vuelta en curso entra como observación con el mismo `R` que una vuelta completa, aunque es una media parcial y ruidosa al inicio de la vuelta.
- El filtro se recalcula desde cero en cada llamada a `estado()`.

**B5. `estado()` es costoso (~10 Hz).** *Avance parcial.* `bus.ultimas` ya usa
`islice` en lugar de copiar el deque completo, pero `estado()` sigue
reconstruyendo el `DataFrame` y `_predecir` vuelve a filtrar la serie completa
en cada llamada. El Kalman incremental sigue pendiente.
- Reconstruye un `DataFrame` de 600 filas, ejecuta Welch, recalcula features y vuelve a filtrar el Kalman.
- `bus.ultimas(n)` copia el deque completo (hasta 12 000 dicts) antes de recortar.
- Sugerencia: `islice` sobre las últimas `n` muestras y un Kalman incremental.

**B6. `iniciar()` crea el CSV antes de saber si la fuente arranca.** *Resuelto.*
`LoggerVivo` abre el archivo en el primer registro, `VivoSesion.iniciar` resuelve
el CSV antes de detener la sesión previa y espera `Fuente.esperar_arranque`
antes de responder. Pruebas: `test_logger_crea_archivo_al_primer_registro`,
`test_archivo_invalido_no_detiene_la_sesion`.
- Con AC apagado, `FuenteVivo._preparar` falla, pero el logger ya creó `ac_<fecha>.csv` con solo la cabecera. `cerrar()` borra el `_verdad` vacío, no el CSV principal, y `listar()` lo muestra.
- Si `_resolver_archivo` falla en modo seco, el bus nuevo ya reemplazó al anterior, pero `motor` sigue apuntando a la sesión previa.
- `sleep(0.05)` no garantiza que `_preparar` haya terminado. Un error al abrir la memoria puede llegar después de que la respuesta ya dijo «activo».

**B7. El filtro arranca con estado cero.** *Resuelto.* El acondicionador
inicializa cada canal con `sosfilt_zi` en la primera muestra.
- No se usa `sosfilt_zi` (el plan 1 lo pedía). Las primeras salidas suben desde 0 durante ~0.1–0.2 s.
- Esas muestras llegan al CSV y al osciloscopio, aunque el motor las ignora por usar ventanas largas.

**B8. La banda «alta» (15–40 Hz) cae en la zona de transición del filtro.**
*Documentado.* `config.yaml` advierte que `bandas_hz.alta` y
`limpieza.filtro.corte_hz` no deben moverse por separado; ver §3.2 del plan 3.
- Respuesta del Butterworth orden 4 a 20 Hz: ≈ −0.4 dB a 15 Hz, −3 dB a 20 Hz, ≈ −14 dB a 30 Hz, ≈ −24 dB a 40 Hz.
- La potencia de esa banda depende de la pendiente del filtro. Si `corte_hz` cambia (el Laboratorio lo permite), la feature cambia de significado sin aviso.

### Prioridad baja

**B9.** El Welch en vivo descarta los NaN y concatena lo que queda, lo que crea discontinuidades en la señal. *Resuelto.* `_rellenar_huecos` recorta los extremos e interpola los huecos internos; prueba `test_espectro_interpola_huecos`.

**B10.** `_por_vuelta` se sobrescribe si `lap` retrocede (por ejemplo, al reiniciar la sesión). *Resuelto.* Un retroceso de vuelta limpia `_por_vuelta`, `_suma` y `_cuenta`; prueba `test_reinicio_stint_al_retroceder_vuelta`.

**B11.** `_detener_sin_lock` cierra el logger tras `join(timeout=1.5)` sin comprobar que el hilo terminó. Si sigue escribiendo, `registrar` lanza `ValueError` sobre un archivo cerrado, lo que activa B3. *Resuelto.* Se hace un segundo `join` y `LoggerVivo.registrar` ignora escrituras tras `cerrar()` (pruebas `test_logger_ignora_escritura_tras_cerrar`, `test_detener_bajo_carga`).

---

## C. Validación y documentación

- **Circularidad.** *Sigue pendiente.* Ridge solo se entrenó con simulación
  acoplada: el MAE 0.0023 no demuestra capacidad predictiva sobre AC real.
  Faltan los adaptadores F2/F4 y una corrida con datos reales; no se sustituye
  por más simulación.
- **Acople débil.** *Sigue pendiente.* El plan 1 marca «repetir con acople
  débil» como hecho, pero el README lo lista como pendiente. Conviene dejar esa
  corrida documentada.
- **Cobertura de Kalman = 1.00.** *Sigue pendiente.* En la simulación la etiqueta
  casi no tiene ruido, así que el 1.00 no dice mucho. Sugerencia: calibrar `R`
  con el error del proxy (MAE 0.027), sin tocar la etiqueta para mejorar cifras.
- **Plan 3.** *Resuelto en Fase 2.* La tabla de decisiones ya no tiene el `**`
  suelto en D10 (ahora describe la GUI nativa) y D6/D7/§3.3/§7 se alinearon con
  el código: sin P95, sin Kalman incremental, sin `_verdad.csv`.
- **Tests que faltan.** *Resueltos.* `test_captura_cruda_reprocesable_en_batch`
  (logger → batch), `test_ac_cuenta_paquetes_perdidos` y
  `test_estado_refleja_diagnostico_no_cero` (pérdida de paquetes),
  `test_detener_bajo_carga` y `test_features_no_vacias_con_ventana_2s`.

---

## D. Hipótesis resueltas o confirmadas en Fase 2

1. **`features` casi siempre `None` en modo seco.** *Resuelta.* La causa era
   una ventana de 6 s con muestras NaN; con `vivo.ventana_s = 2.0` y el Welch
   interpolando huecos, `test_features_no_vacias_con_ventana_2s` fija que
   `estado()["features"]` no es `None`.
2. **`FuenteVivo.detener()` llama a `memoria.cerrar()` desde otro hilo.** *Resuelta.*
   `FuenteVivo._limpiar` cierra la memoria desde el propio hilo de captura; el
   `detener()` de la fuente solo señala el `Event`.
3. **Los timestamps de AC son de lectura** (`perf_counter`), no del tick de la
   física. *Confirmada y documentada* en §3.1 del plan 3: es lo correcto para un
   solo hilo de captura, y el jitter se reporta con `fs_medida`.
4. **Doble filtrado al reprocesar capturas** (A1). *Resuelta en código* al
   registrar la fila cruda: el batch aplica un solo filtro (plan 3 §7.9). Medir
   la ganancia con una captura real sigue siendo trabajo de la sección C.

---

## E. Orden de trabajo (ejecutado y pendiente)

1. ✅ **Logger crudo y con etiqueta (A1, A5).** Registro desde `Fuente._emitir`, antes del acondicionador, con `grip_*` y `degradacion`.
2. ✅ **Robustez del bus y la fuente (B2, B3, B6, B11).** Suscriptores protegidos, `packetId` perdidos, arranque confirmado y cierre seguro.
3. ✅ **Decimación con timestamps reales (A2)** e inicialización del filtro (B7).
4. ✅ **Fallback al proxy (A3):** se eliminó la afirmación del plan y quedó como decisión D11 (`NaN`, modo `none`).
5. ✅ **Documentación (A4, A6, A7, A8, plan 3).** Corregida en Fase 2.
6. ⬜ **Pico robusto y reiniciable (B1).** Siguiente candidato de código: P95 y cambio de neumáticos, con justificación separada porque cambia la degradación calculada.
7. ⬜ **Kalman por rueda e incremental (B4/B5)** y **validación con datos reales (C)**.

---

## F. Checklist

- [x] A1 — Logger registra la señal cruda (`Fuente.suscribir_crudo`)
- [x] A2 — Decimación basada en `timestamp_s`
- [x] A3 — Fallback retirado del plan: `NaN` / modo `none` (D11)
- [x] A4 — README aclara que Ridge no interviene en vivo
- [x] A5 — `grip_*` y `degradacion` se guardan en el CSV crudo
- [x] A6 — Ventana de features en vivo unificada en 2 s
- [x] A7 — Plan 1 actualizado: F3 expone `tyreWear` como grip
- [x] A8 — `ritmo_hz` documentado como interruptor
- [ ] B1 — Pico del grip robusto (P95) y reinicio por cambio de neumáticos
- [x] B2 — `packetId` perdidos contados y expuestos en `estado()`
- [x] B3 — Suscriptores del bus y crudos protegidos
- [ ] B4 — Kalman por rueda o con `R` ajustado en la vuelta parcial
- [ ] B5 — Optimizar `estado()` (hecho solo `bus.ultimas` con `islice`)
- [x] B6 — CSV creado solo cuando hay registro y arranque confirmado
- [x] B7 — Filtro inicializado con `sosfilt_zi`
- [x] B8 — Dependencia de la banda alta con `corte_hz` documentada
- [x] B9 — Welch interpola huecos internos
- [x] B10 — Retroceso de vuelta reinicia el *stint*
- [x] B11 — Cierre del logger seguro bajo carga
- [ ] C — Validación con datos reales de AC (tests faltantes ya cubiertos)
- [x] D — Cuatro hipótesis verificadas o documentadas

> Las casillas marcadas en Fase 2 no implican cambios de algoritmos: el único
> código nuevo es una prueba que fija que los diagnósticos de captura llegan al
> estado. B1, B4/B5 y la validación con datos reales siguen abiertos.
