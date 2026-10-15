"""Configuracion de pytest: agrega la raiz del proyecto al sys.path."""

import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
