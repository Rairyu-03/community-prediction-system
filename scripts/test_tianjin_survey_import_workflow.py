r"""Retain an acceptance project created from the Tianjin aggregate survey workbook."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402
from workflow_sample_data import SAMPLE_FACILITY_PARAMETERS, SAMPLE_POPULATION_PARAMETERS  # noqa: E402


SOURCE = ROOT / "测试数据" / "测试-《社区基本信息与服务设施信息调研表.xlsx"


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence = ROOT / "runtime" / "acceptance" / f"tianjin_survey_import_{stamp}"
    evidence.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as client:
        population_parameters = deepcopy(SAMPLE_POPULATION_PARAMETERS)
        facility_parameters = deepcopy(SAMPLE_FACILITY_PARAMETERS)

        project_name = f"测试工程-晨光社区调研数据-{stamp}"
        response = client.post("/api/projects", json={"name": project_name})
        assert response.status_code == 201, response.text
        project = response.json()
        base = f"/api/projects/{project['id']}"

        with SOURCE.open("rb") as stream:
            response = client.post(
                base + "/communities/import",
                files={"file": (SOURCE.name, stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 200, response.text
        import_report = response.json()
        assert import_report["created_count"] == 1 and import_report["success_count"] == 1, import_report
        community = import_report["community"]
        assert community["code"] == "120104-A"
        assert community["name"] == "晨光社区"
        assert community["region"] == "天津市"
        assert community["households"] == 3200
        assert sum(community["age_counts"].values()) == 8516
        assert community["facilities"]["助餐设施"]["社区食堂建筑面积（平方米）"] == 590.72
        assert community["facilities"]["停车充电设施"]["机动车充电桩数量（个）"] == 16

        for kind, data in (("population", population_parameters), ("facility", facility_parameters)):
            saved = client.put(base + f"/parameters/{kind}", json={"data": data})
            assert saved.status_code == 200, saved.text
            assert client.get(base + f"/parameters/{kind}").json()["data"] == data

        population_quality = client.get(base + "/quality", params={"kind": "population"}).json()
        assert population_quality["ready"] is True, population_quality
        population_response = client.post(base + "/predictions/population", json={"seed": 20260917})
        assert population_response.status_code == 200, population_response.text
        population_run = population_response.json()
        population_results = client.get(f"/api/runs/{population_run['id']}/results").json()
        assert len(population_results) == population_parameters["duration"]
        assert all(row["data"].get("totalPopulation") for row in population_results)

        facility_quality = client.get(base + "/quality", params={"kind": "facility"}).json()
        assert facility_quality["ready"] is True, facility_quality
        facility_response = client.post(
            base + "/predictions/facility",
            json={"population_run_id": population_run["id"], "seed": 20260917, "generate_report": True, "report_mode": "overall"},
        )
        assert facility_response.status_code == 200, facility_response.text
        facility_run = facility_response.json()
        facility_results = client.get(f"/api/runs/{facility_run['id']}/results").json()
        assert len(facility_results) == len(population_results)
        assert all(row["data"].get("metrics") for row in facility_results)

        converted = client.get(base + "/communities/template", params={"community_id": community["id"]})
        assert converted.status_code == 200 and converted.content.startswith(b"PK")
        (evidence / "晨光社区-系统社区数据.xlsx").write_bytes(converted.content)

        report = client.get(f"/api/runs/{facility_run['id']}/report")
        assert report.status_code == 200 and report.content.startswith(b"PK")
        (evidence / "晨光社区-预测报告.docx").write_bytes(report.content)

        summary = {
            "project": project,
            "source": str(SOURCE),
            "community": {
                "id": community["id"],
                "code": community["code"],
                "name": community["name"],
                "population": sum(community["age_counts"].values()),
                "households": community["households"],
            },
            "parametersCopiedFromProject": {"id": demo["id"], "name": demo["name"]},
            "populationRunId": population_run["id"],
            "facilityRunId": facility_run["id"],
            "warnings": import_report["warnings"],
        }
        (evidence / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"EVIDENCE={evidence}")


if __name__ == "__main__":
    main()
