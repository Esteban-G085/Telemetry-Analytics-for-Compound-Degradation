"""Tests del acceso a la memoria compartida de AC (Etapa 3)."""

from __future__ import annotations

import ctypes

import pytest

from telemetria.adquisicion.ac_info import (
    SPageFileGraphics,
    SPageFilePhysics,
    MemoriaAC,
    _normalizar_angulo,
    verificar_layout,
)


def test_offsets_del_layout():
    """Los offsets relevantes deben ser los documentados (no inventados)."""
    assert ctypes.sizeof(SPageFilePhysics) == 168
    assert SPageFilePhysics.packetId.offset == 0
    assert SPageFilePhysics.tyreWear.offset == 120
    assert SPageFilePhysics.tyreDirtyLevel.offset == 136
    assert SPageFilePhysics.tyreCoreTemperature.offset == 152
    assert SPageFileGraphics.completedLaps.offset == 28


def test_normalizar_angulo():
    assert _normalizar_angulo(0.0) == 0.0
    assert _normalizar_angulo(0.25) == pytest.approx(0.5)
    assert _normalizar_angulo(10.0) == 1.0
    assert _normalizar_angulo(-10.0) == -1.0


def test_memoria_cerrada_no_inventa_datos():
    """Si AC no esta en pista, no debe fabricar una seccion vacia."""
    mem = MemoriaAC()
    mem.abrir()
    try:
        if mem.disponible:
            pytest.skip("AC esta publicando datos: no se puede probar el camino cerrado")
        assert mem.leer_muestra() is None
        assert mem.error
        info = verificar_layout()
        assert info.disponible is False
        assert info.ok is False
    finally:
        mem.cerrar()


def test_doble_cierre_es_seguro():
    mem = MemoriaAC()
    mem.abrir()
    mem.cerrar()
    mem.cerrar()
    assert mem.disponible is False
