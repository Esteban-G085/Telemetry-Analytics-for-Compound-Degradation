"""Cache en memoria de sesiones procesadas (D7).

Una vez procesado un CSV, el DataFrame limpio queda en RAM; las peticiones
posteriores solo leen rebanadas de memoria, sin volver a tocar el disco.
"""

from __future__ import annotations

from pathlib import Path

from telemetria.pipeline.config import RUTA_CONFIG_POR_DEFECTO, cargar_config, fusionar

from telemetria.api.servicios import adaptador_pipeline as adaptador

RAIZ = Path(__file__).resolve().parents[3]


class CacheMemoria:
    def __init__(self, dir_raw: str | Path | None = None, overrides: dict | None = None):
        self.dir_raw = Path(dir_raw) if dir_raw is not None else RAIZ / "data" / "raw"
        self.overrides = overrides or {}
        self._sesiones: dict[str, adaptador.Sesion] = {}
        self.activa: str | None = None

    # --- configuracion ---
    def config(self) -> dict:
        return cargar_config(RUTA_CONFIG_POR_DEFECTO, overrides=self.overrides)

    def actualizar_overrides(self, overrides: dict) -> dict:
        self.overrides = fusionar(self.overrides, overrides or {})
        return self.config()

    def reiniciar_overrides(self) -> dict:
        """Vuelve a los valores de fábrica de config.yaml (§3.4, botón reset)."""
        self.overrides = {}
        return self.config()

    # --- sesiones ---
    def listar(self) -> list[dict]:
        """CSVs disponibles en `data/raw/` con metadatos ligeros."""
        self.dir_raw.mkdir(parents=True, exist_ok=True)
        salida = []
        for ruta in sorted(self.dir_raw.glob("*.csv")):
            if ruta.stem.endswith("_verdad"):
                continue
            verdad = ruta.with_name(ruta.stem + "_verdad.csv")
            salida.append(
                {
                    "id": ruta.stem,
                    "nombre": ruta.name,
                    "kb": round(ruta.stat().st_size / 1024.0, 1),
                    "tiene_verdad": verdad.exists(),
                    "cargada": ruta.stem in self._sesiones,
                }
            )
        return salida

    def obtener(self, sid: str) -> adaptador.Sesion | None:
        return self._sesiones.get(sid)

    def activa_o_error(self) -> adaptador.Sesion:
        if self.activa is None or self.activa not in self._sesiones:
            raise ValueError("No hay sesion activa: carga una con /api/sesiones/cargar")
        return self._sesiones[self.activa]

    def cargar_archivo(self, nombre: str) -> adaptador.Sesion:
        ruta = (self.dir_raw / nombre).resolve()
        if ruta.parent != self.dir_raw.resolve() or not ruta.exists():
            raise FileNotFoundError(f"CSV no encontrado en data/raw: {nombre}")
        sesion = adaptador.procesar_csv(ruta, self.config())
        return self._guardar(sesion)

    def cargar_contenido(self, datos: bytes, nombre: str) -> adaptador.Sesion:
        sesion = adaptador.procesar_contenido(datos, self.config(), nombre)
        return self._guardar(sesion)

    def _guardar(self, sesion: adaptador.Sesion) -> adaptador.Sesion:
        self._sesiones[sesion.id] = sesion
        self.activa = sesion.id
        return sesion
