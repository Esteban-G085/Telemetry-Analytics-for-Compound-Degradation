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


def test_sensores_individuales_tienen_resultado_propio(cliente):
    caidos = [
        {"canal": "wheel_slip", "rueda": "fl"},
        {"canal": "temp_core_c", "rueda": "fl"},
    ]
    r = cliente.post(
        "/api/modelos/sensores", json={"caidos": caidos, "modo": "individual"}
    )
    assert r.status_code == 200
    datos = r.json()
    assert datos["modo"] == "individual"
    assert len(datos["resultados"]) == 2
    assert [f["caidos"][0]["canal"] for f in datos["resultados"]] == [
        "wheel_slip",
        "temp_core_c",
    ]
    assert all(f["mae_base"] == datos["mae_base"] for f in datos["resultados"])
    assert all(f["laps_test"] == datos["laps_test"] for f in datos["resultados"])
    slip, temp = datos["resultados"]
    assert any(c.startswith("slip_") for c in slip["columnas_quitadas"])
    assert any(c.startswith("temp_") for c in temp["columnas_quitadas"])
    assert not set(slip["columnas_quitadas"]) & set(temp["columnas_quitadas"])
    assert "mae" in slip and "mae" in temp
    assert "delta" in slip and "delta" in temp


def test_sensores_combinado_no_se_reparte_entre_sensores(cliente):
    caidos = [
        {"canal": "wheel_slip", "rueda": "fl"},
        {"canal": "temp_core_c", "rueda": "fl"},
    ]
    individual = cliente.post(
        "/api/modelos/sensores", json={"caidos": caidos, "modo": "individual"}
    ).json()
    combinado = cliente.post(
        "/api/modelos/sensores", json={"caidos": caidos, "modo": "combinado"}
    ).json()
    assert combinado["modo"] == "combinado"
    assert len(combinado["resultados"]) == 1
    quitadas_individual = set()
    for fila in individual["resultados"]:
        quitadas_individual.update(fila["columnas_quitadas"])
    assert set(combinado["columnas_quitadas"]) == quitadas_individual
    assert combinado["n_features"] < min(
        f["n_features"] for f in individual["resultados"]
    )
    assert combinado["mae"] == combinado["resultados"][0]["mae"]


def test_sensores_individual_presion_es_inocuo(cliente):
    datos = cliente.post(
        "/api/modelos/sensores",
        json={
            "caidos": [{"canal": "pressure_psi", "rueda": "fr"}],
            "modo": "individual",
        },
    ).json()
    fila = datos["resultados"][0]
    assert fila["columnas_quitadas"] == []
    assert fila["n_features"] == datos["n_features_base"]
    assert abs(fila["delta"]) < 1e-12
    assert fila["error"] is None


def test_sensores_modo_invalido(cliente):
    r = cliente.post("/api/modelos/sensores", json={"modo": "inexistente"})
    assert r.status_code == 422
