"""Tests del simulador de fallo de sensores y de la lista de features (§3.5)."""

from __future__ import annotations


def test_features_lista_no_vacia(cliente):
    lista = cliente.get("/api/modelos/features").json()["features"]
    assert len(lista) > 10
    assert "slip_mean_fl" in lista
    assert "degradacion" not in lista


def test_sensores_baseline_sin_fallos(cliente):
    s = cliente.post("/api/modelos/sensores", json={"caidos": []}).json()
    assert s["n_features"] == s["n_features_base"]
    assert s["columnas_quitadas"] == []
    assert abs(s["delta"]) < 1e-12
    assert s["mae_base"] == s["mae"]


def test_sensores_presion_no_afecta_al_modelo(cliente):
    """`pressure_psi` no alimenta ninguna feature: su fallo es inocuo."""
    s = cliente.post(
        "/api/modelos/sensores", json={"caidos": [{"canal": "pressure_psi", "rueda": "fr"}]}
    ).json()
    assert s["columnas_quitadas"] == []
    assert s["n_features"] == s["n_features_base"]


def test_sensores_temperatura_quita_features(cliente):
    s = cliente.post(
        "/api/modelos/sensores",
        json={"caidos": [{"canal": "temp_core_c", "rueda": "fl"}]},
    ).json()
    assert s["columnas_quitadas"]
    assert all(c.endswith("_fl") for c in s["columnas_quitadas"])
    assert s["n_features"] < s["n_features_base"]
    assert s["mae"] >= 0.0


def test_sensores_todas_las_features_falla(cliente):
    """Quitar todas las features debe dar 422, no un 500."""
    caidos = [
        {"canal": c}
        for c in (
            "wheel_slip",
            "temp_core_c",
            "wheel_load_n",
            "speed_kmh",
            "throttle",
            "brake",
            "steering",
        )
    ]
    r = cliente.post("/api/modelos/sensores", json={"caidos": caidos})
    assert r.status_code == 422
