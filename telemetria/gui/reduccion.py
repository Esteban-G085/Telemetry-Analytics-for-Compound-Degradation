"""Reducción de puntos para las gráficas de la GUI (LTTB local).

El backend ya entrega las vueltas con un ``max_puntos`` acordado. Esta capa no
cambia las claves JSON ni vuelve a pedir datos al servidor: solo decide qué
muestras se dibujan cuando la vista tiene menos píxeles que puntos.

La variante es **multicanal**: en cada cubo elige la muestra cuyo vector de
señales está más lejos del punto anterior y de la media del cubo. Así un pico
que solo aparece en el freno también puede conservarse, aunque el acelerador
sea llano. Todas las series comparten los mismos índices, de modo que el cursor
y la diferencia A − B siguen leyendo el mismo instante.
"""

from __future__ import annotations

import numpy as np


def presupuesto_puntos(
    ancho_px: int, *, factor: int = 3, minimo: int = 900, maximo: int = 6000
) -> int:
    """Puntos a pedir/dibujar para un ancho de gráfico dado.

    Con ~1000 px y ``factor=3`` se piden 3000 puntos: suficientes para que el
    ojo no note que faltan muestras, pero lejos de los 20000 del valor por defecto del
    backend. El límite inferior evita graficas casi vacías antes de mostrar la
    ventana y el superior evita peticiones enormes en pantallas muy anchas.
    """
    ancho = max(1, int(ancho_px))
    return max(minimo, min(maximo, ancho * max(1, int(factor))))


def indice_lttb(x: list, series: dict[str, list], umbral: int) -> list[int]:
    """Índices representativos, ordenados, que conservan los picos.

    ``umbral`` es el número máximo de puntos deseado. Si la serie ya cabe no se
    reduce nada. El primer y el último punto siempre se conservan.
    """
    if not series:
        return list(range(len(x)))
    longitud = min([len(x)] + [len(valores) for valores in series.values()])
    if umbral >= longitud or umbral < 3 or longitud < 3:
        return list(range(longitud))

    # NaN/None cuentan como 0 para el cálculo de áreas; las claves JSON no se
    # tocan, solo se eligen índices.
    matriz = np.column_stack(
        [
            np.nan_to_num(np.asarray(list(valores)[:longitud], dtype=float))
            for valores in series.values()
        ]
    )
    seleccion = [0]
    tamano_cubo = (longitud - 2) / (umbral - 2)
    anterior = 0
    for cubo in range(umbral - 2):
        inicio = int(cubo * tamano_cubo) + 1
        fin = min(int((cubo + 1) * tamano_cubo) + 1, longitud - 1)
        inicio = max(inicio, anterior + 1)
        if inicio >= fin:
            continue

        bloque = matriz[inicio:fin]
        vector_anterior = matriz[anterior]
        areas = ((bloque - vector_anterior) ** 2).sum(axis=1) + (
            (bloque - bloque.mean(axis=0)) ** 2
        ).sum(axis=1)
        mejor = inicio + int(np.argmax(areas))
        seleccion.append(mejor)
        anterior = mejor

    seleccion.append(longitud - 1)
    return seleccion


def reducir(
    x: list, series: dict[str, list], max_puntos: int
) -> tuple[list, dict[str, list], list[int]]:
    """Reduce ``x`` y todas las ``series`` con los mismos índices.

    Devuelve ``(x_reducido, series_reducidas, indices)``. Los índices permiten
    reutilizar la selección en valores derivados (por ejemplo la curva
    normalizada o la curva de diferencia) sin recalcular nada.
    """
    indices = indice_lttb(x, series, max_puntos)
    return (
        [x[i] for i in indices],
        {canal: [valores[i] for i in indices] for canal, valores in series.items()},
        indices,
    )
