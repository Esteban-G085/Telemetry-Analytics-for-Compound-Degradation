"""Dependencias compartidas por los routers."""

from __future__ import annotations

from fastapi import Request

from backend.servicios.cache_memoria import CacheMemoria
from backend.servicios.vivo import VivoSesion


def cache_actual(request: Request) -> CacheMemoria:
    return request.app.state.cache


def vivo_actual(request: Request) -> VivoSesion:
    return request.app.state.vivo
