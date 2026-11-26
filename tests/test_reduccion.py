"""Reducción local de gráficas: menos puntos, mismos picos y misma alineación."""

from __future__ import annotations

from telemetria.gui.reduccion import indice_lttb, presupuesto_puntos, reducir


def test_presupuesto_se_adapta_al_ancho_y_esta_acotado() -> None:
    assert presupuesto_puntos(1000) == 3000
    assert presupuesto_puntos(100) == 900
    assert presupuesto_puntos(5000) == 6000
    assert presupuesto_puntos(1000, factor=2) == 2000


def test_lttb_conserva_extremos_y_un_pico_solo_de_otro_canal() -> None:
    n = 1200
    x = [i * 0.01 for i in range(n)]
    throttle = [0.5 + 0.1 * (i % 20) / 20 for i in range(n)]
    brake = [0.2 for _ in range(n)]
    pico = 817
    brake[pico] = 9.9

    indices = indice_lttb(x, {"throttle": throttle, "brake": brake}, 60)

    assert indices[0] == 0
    assert indices[-1] == n - 1
    assert pico in indices
    assert len(indices) <= 60
    assert indices == sorted(indices)


def test_reducir_comparte_indices_y_no_desalinea_series() -> None:
    x = [float(i) for i in range(20)]
    series = {
        "throttle": [float(i % 5) for i in range(20)],
        "brake": [float(20 - i) for i in range(20)],
    }

    x_r, y_r, indices = reducir(x, series, 6)

    assert len(indices) == 6
    assert x_r == [x[i] for i in indices]
    for canal, valores in series.items():
        assert y_r[canal] == [valores[i] for i in indices]


def test_reducir_no_toca_una_serie_que_ya_cabe() -> None:
    x = [0.0, 0.1, 0.2, 0.3]
    series = {"canal": [1.0, 2.0, 3.0, 4.0]}

    x_r, y_r, indices = reducir(x, series, 900)

    assert indices == [0, 1, 2, 3]
    assert x_r == x
    assert y_r == series
