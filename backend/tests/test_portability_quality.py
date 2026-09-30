from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
import json

from fastapi.testclient import TestClient

from app.defaults import DEFAULT_FACILITY_PARAMETERS, DEFAULT_POPULATION_PARAMETERS
from app.main import app


def _complete_facility_parameters() -> dict:
    data = deepcopy(DEFAULT_FACILITY_PARAMETERS)
    data["meal"].update({"demandRate": 35, "diningAreaPerPerson": 1.2, "deliveryAreaPerPerson": 0.4, "kitchenAreaPerPerson": 0.35, "preparationAreaPerPerson": 0.25, "diningSpaceAreaPerPerson": 0.6})
    data["elderly"].update({"stationDemandRate": 20, "stationAreaPerPerson": 3, "rehabilitationRates": {"60-69岁": 18, "70-79岁": 25, "80岁以上": 32}, "entertainmentRates": {"60-69岁": 30, "70-79岁": 36, "80岁以上": 40}, "transportRates": {"60-69岁": 8, "70-79岁": 16, "80岁以上": 28}})
    data["childcare"].update({"nurseryDemandRate": 40, "nurseryAreaPerPerson": 8, "kindergartenDemandRate": 85, "kindergartenBuildingAreaPerPerson": 8.8, "kindergartenLandAreaPerPerson": 15, "outdoorAreaPerPerson": 4, "sharedAreaPerPerson": 2, "combinedRoomAreaPerPerson": 5.5, "activityRoomAreaPerPerson": 3.2, "bedroomAreaPerPerson": 2.8})
    data["parking"].update({"chargersPerHousehold": 0.25, "parkingSpacesPerHousehold": 1, "newEnergyVehiclesPerCapita": {str(year): 0.12 for year in range(2026, 2037)}, "vehiclesPerCapita": {str(year): 0.32 for year in range(2026, 2037)}})
    data["activity"].update({"publicAreaPerCapita": 0.3, "sportsAreaPerCapita": 0.1})
    return data


VALID_COMMUNITY = {
    "code": "MOVE", "name": "迁移测试社区", "region": "全国", "households": 200,
    "average_household_size": 2.5, "population_base_year": 2026,
    "age_counts": {"2": 50, "30": 300, "65": 100, "75": 40, "85": 10},
    "migration_rates": {}, "facilities": {}, "idle_spaces": [],
}


def test_quality_project_archive_and_system_backup_roundtrip():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "迁移验收-" + uuid4().hex[:8]}).json()
        base = f"/api/projects/{project['id']}"
        imported_id = None
        restored_ids = []
        try:
            empty = client.get(base + "/quality", params={"kind": "population"})
            assert empty.status_code == 200
            assert empty.json()["ready"] is False
            assert any(row["code"] == "NO_COMMUNITIES" for row in empty.json()["issues"])

            assert client.put(base + "/parameters/population", json={"data": deepcopy(DEFAULT_POPULATION_PARAMETERS)}).status_code == 200
            assert client.put(base + "/parameters/facility", json={"data": _complete_facility_parameters()}).status_code == 200
            for index in (1, 2):
                community = deepcopy(VALID_COMMUNITY)
                community.update(code=f"MOVE-{index}", name=f"迁移测试社区{index}", population_base_year=2026)
                response = client.post(base + "/communities", json=community)
                assert response.status_code == 201, response.text

            quality = client.get(base + "/quality", params={"kind": "population"}).json()
            assert quality["ready"] is True
            assert quality["forecastYears"] == [2027, 2028, 2029, 2030, 2031]
            population = client.post(base + "/predictions/population", json={"seed": 260906})
            assert population.status_code == 200, population.text
            population_run = population.json()

            facility_quality = client.get(base + "/quality", params={"kind": "facility"}).json()
            assert facility_quality["ready"] is True
            facility = client.post(base + "/predictions/facility", json={
                "seed": 260906,
                "population_run_id": population_run["id"],
                "generate_report": True,
                "report_mode": "overall",
            })
            assert facility.status_code == 200, facility.text

            exported = client.get(base + "/export")
            assert exported.status_code == 200
            with ZipFile(BytesIO(exported.content)) as archive:
                assert "manifest.json" in archive.namelist()
                assert any(name.startswith("files/output/") for name in archive.namelist())

            imported = client.post(
                "/api/projects/import-archive",
                files={"file": ("project.ccproject.zip", exported.content, "application/zip")},
            )
            assert imported.status_code == 201, imported.text
            imported_id = imported.json()["id"]
            imported_base = f"/api/projects/{imported_id}"
            assert len(client.get(imported_base + "/communities").json()) == 2
            imported_runs = client.get(imported_base + "/runs").json()
            assert len(imported_runs) == 2
            assert all(Path(run["output_file"]).exists() for run in imported_runs)
            imported_facility = next(run for run in imported_runs if run["kind"] == "facility")
            assert imported_facility["report_available"] is True
            assert client.get(f"/api/runs/{imported_facility['id']}/report").content.startswith(b"PK")

            system_backup = client.get("/api/system/backup")
            assert system_backup.status_code == 200
            with ZipFile(BytesIO(system_backup.content)) as archive:
                assert "system-manifest.json" in archive.namelist()
                assert any(name.startswith("projects/") for name in archive.namelist())
            restore_buffer = BytesIO()
            with ZipFile(restore_buffer, "w", ZIP_DEFLATED) as archive:
                archive.writestr("system-manifest.json", json.dumps({
                    "format": "community-prediction-system", "version": 1, "projectCount": 1,
                }))
                archive.writestr("projects/000.ccproject.zip", exported.content)
            restored = client.post(
                "/api/system/restore",
                files={"file": ("system.zip", restore_buffer.getvalue(), "application/zip")},
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["restoredCount"] == 1
            restored_ids = [row["id"] for row in restored.json()["projects"]]
            assert len(client.get(f"/api/projects/{restored_ids[0]}/communities").json()) == 2
            storage = client.get("/api/storage-info").json()
            assert storage["database"] and storage["projects"]
        finally:
            for restored_id in restored_ids:
                client.delete(f"/api/projects/{restored_id}")
            if imported_id:
                client.delete(f"/api/projects/{imported_id}")
            client.delete(base)


def test_rejects_invalid_project_archive_without_leaving_project():
    with TestClient(app) as client:
        before = {row["id"] for row in client.get("/api/projects").json()}
        response = client.post(
            "/api/projects/import-archive",
            files={"file": ("broken.zip", b"not-a-zip", "application/zip")},
        )
        assert response.status_code == 422
        after = {row["id"] for row in client.get("/api/projects").json()}
        assert after == before
