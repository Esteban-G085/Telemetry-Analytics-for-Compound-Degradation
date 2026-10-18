"""Respuesta JSON de alto rendimiento basada en `orjson`.

FastAPI 0.143 marca su `ORJSONResponse` como deprecado, así que definimos la
nuestra. Serializa `numpy` (arrays y escalares) y convierte `NaN`/`Inf` en
`null`, que es justo lo que necesita la telemetría (D4/D7).
"""

from __future__ import annotations

import orjson
from starlette.responses import Response

OPCIONES = orjson.OPT_SERIALIZE_NUMPY  # numpy + NaN -> null


def dumps(obj) -> bytes:
    """JSON bytes con el mismo serializador que las respuestas REST."""
    return orjson.dumps(obj, option=OPCIONES)


class RespuestaJSON(Response):
    media_type = "application/json"

    def render(self, content) -> bytes:
        return dumps(content)
