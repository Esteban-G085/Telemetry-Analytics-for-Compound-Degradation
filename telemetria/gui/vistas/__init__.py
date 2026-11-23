"""Pestañas de la interfaz de escritorio. Una clase por pantalla."""

from telemetria.gui.vistas.v_espectro import VistaEspectro
from telemetria.gui.vistas.v_laboratorio import VistaLaboratorio
from telemetria.gui.vistas.v_prediccion import VistaPrediccion
from telemetria.gui.vistas.v_robustez import VistaRobustez
from telemetria.gui.vistas.v_replay import VistaReplay
from telemetria.gui.vistas.v_sesiones import VistaSesiones
from telemetria.gui.vistas.v_telemetria import VistaTelemetria
from telemetria.gui.vistas.v_vivo import VistaVivo

__all__ = [
    "VistaEspectro",
    "VistaLaboratorio",
    "VistaPrediccion",
    "VistaRobustez",
    "VistaReplay",
    "VistaSesiones",
    "VistaTelemetria",
    "VistaVivo",
]
