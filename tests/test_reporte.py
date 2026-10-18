"""Tests del reporte HTML (trazabilidad y tablas)."""

from telemetria.pipeline import reporte


def _datos_minimos():
    return {
        "metricas": {"Ridge": {"mae": 0.1, "rmse": 0.2, "r2": 0.9}},
        "registro": {"valido": 3},
        "importancias": __import__("pandas").DataFrame(
            {"feature": ["slip_mean_fl", "grados_segundo_rr"], "coeficiente": [0.12, 0.34]}
        ),
        "fisica": [
            {"grupo": "grados_segundo", "n": 4, "esperado": "positivo", "aciertos": 3, "suma": 0.15, "coincide": True}
        ],
        "cobertura": 0.9,
        "error_caida": {"Ridge (ventana->vuelta)": 0.0, "Kalman (vuelta)": 1.0},
        "sensibilidad_kalman": [{"r": 0.001, "mae": 0.01, "cobertura": 0.9}],
        "hash_entrada": "abc123def456",
        "config_yaml": "fs: 100\nmodelo:\n  prop_test: 0.25\n",
        "entrada": "data/raw/x.csv",
    }


def test_reporte_incrusta_hash_y_config(tmp_path, cfg):
    ruta = reporte.generar_reporte(_datos_minimos(), tmp_path / "r.html", cfg)
    texto = ruta.read_text(encoding="utf-8")
    assert "abc123def456" in texto
    assert "fs: 100" in texto
    assert "data/raw/x.csv" in texto
    assert "Trazabilidad" in texto


def test_reporte_incluye_tablas_de_features(tmp_path, cfg):
    ruta = reporte.generar_reporte(_datos_minimos(), tmp_path / "r.html", cfg)
    texto = ruta.read_text(encoding="utf-8")
    assert "Importancias" in texto
    assert "grados_segundo_rr" in texto
    assert "Verificacion fisica" in texto
    assert "Cobertura y vuelta de caida" in texto
    assert "Sensibilidad de Kalman a R" in texto
