"""Dependencias compartidas por los routers."""

from __future__ import annotations

from fastapi import Request

from backend.servicios.cache_memoria import CacheMemoria


def cache_actual(request: Request) -> CacheMemoria:
    return request.app.state.cache
