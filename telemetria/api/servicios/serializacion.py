"""Conversion de arrays numpy a JSON compacto para la API.

El frontend consume arrays planos (D4): aqui se redondean para reducir el
tamano del payload. Los valores no finitos los convierte a ``null`` el
serializador (``orjson``), no este modulo.
"""

from __future__ import annotations

import numpy as np


def lista_numerica(valores, decimales: int | None = 4) -> list:
    """Array numpy -> lista JSON (``None`` en los no finitos).

    El camino rapido (todo finito, lo habitual) no recorre elemento a elemento:
    ``np.round`` + ``ndarray.tolist()`` corren en C. El camino lento solo se usa
    cuando hay NaN/Inf (huecos largos marcados como invalidos).
    """
    a = np.asarray(valores, dtype=float)
    if decimales is not None:
        a = np.round(a, int(decimales))
    if np.isfinite(a).all():
        return a.tolist()
    return [None if not np.isfinite(v) else float(v) for v in a.tolist()]


def indices_minmax(x, max_puntos: int) -> np.ndarray | None:
    """Indices que preservan los picos (min/max por cubo) al reducir.

    Devuelve ``None`` cuando no hace falta reducir. La reduccion se calcula
    una vez sobre un canal y se aplica a todos para no desalinear series.
    """
    n = len(x)
    if n <= max_puntos or max_puntos < 4:
        return None
    n_cubos = max(1, max_puntos // 2)
    bordes = np.linspace(0, n, n_cubos + 1).astype(int)
    idx: list[int] = []
    arr = np.asarray(x, dtype=float)
    for i in range(n_cubos):
        a, b = int(bordes[i]), int(bordes[i + 1])
        if b - a <= 1:
            idx.append(a)
            continue
        seg = arr[a:b]
        if not np.isfinite(seg).any():
            idx.append(a)
            continue
        imin = a + int(np.nanargmin(seg))
        imax = a + int(np.nanargmax(seg))
        if imin == imax:
            idx.append(imin)
        else:
            idx.extend(sorted((imin, imax)))
    return np.unique(np.asarray(idx, dtype=int))


def empaquetar_float32(matrices: list[np.ndarray]) -> bytes:
    """Empaqueta filas (n_canales, n_muestras) como float32 little-endian.

    Es el formato de la trama binaria del WebSocket (D4): el cliente lo monta
    directo en un ``Float32Array`` sin parseo. Todas las filas miden lo mismo.
    """
    return np.asarray(matrices, dtype="<f4").tobytes()
