from __future__ import annotations

import os
from collections import Counter
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from docx import Document
import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(WORKSPACE_ROOT / 'backend' / 'data' / 'test_api.db').as_posix()}")
os.environ.setdefault("PROJECTS_ROOT", str(WORKSPACE_ROOT / "runtime" / "test_projects"))

from fastapi.testclient import TestClient  # noqa: E402

from app.defaults import DEFAULT_FACILITY_PARAMETERS  # noqa: E402
from app.main import app  # noqa: E402


def _complete_facility_parameters() -> dict:
    data = deepcopy(DEFAULT_FACILITY_PARAMETERS)
    data["status"] = "ready"
    data["meal"].update({"demandRate": 35, "diningAreaPerPerson": 1.2, "deliveryAreaPerPerson": 0.4, "kitchenAreaPerPerson": 0.35, "preparationAreaPerPerson": 0.25, "diningSpaceAreaPerPerson": 0.6})
    data["elderly"].update({
        "stationDemandRate": 20,
        "stationAreaPerPerson": 3,
        "rehabilitationRates": {"60-69岁": 18, "70-79岁": 25, "80岁以上": 32},
        "entertainmentRates": {"60-69岁": 30, "70-79岁": 36, "80岁以上": 40},
        "transportRates": {"60-69岁": 8, "70-79岁": 16, "80岁以上": 28},
    })
    data["childcare"].update(
        {
            "nurseryDemandRate": 40,
            "nurseryAreaPerPerson": 8,
            "kindergartenDemandRate": 85,
            "kindergartenBuildingAreaPerPerson": 8.8,
            "kindergartenLandAreaPerPerson": 15,
            "outdoorAreaPerPerson": 4,
            "sharedAreaPerPerson": 2,
            "combinedRoomAreaPerPerson": 5.5,
            "activityRoomAreaPerPerson": 3.2,
            "bedroomAreaPerPerson": 2.8,
        }
    )
    data["parking"].update({
        "chargersPerHousehold": 0.25,
        "parkingSpacesPerHousehold": 1,
        "newEnergyVehiclesPerCapita": {str(year): 0.12 + (year - 2026) * 0.01 for year in range(2026, 2037)},
        "vehiclesPerCapita": {str(year): 0.32 + (year - 2026) * 0.005 for year in range(2026, 2037)},
    })
    data["activity"].update({"publicAreaPerCapita": 0.3, "sportsAreaPerCapita": 0.1})
    data["references"] = {
        "meal.demandRate": {"source": "测试标准"},
        "activity.publicAreaPerCapita": {"source": "测试标准"},
    }
    return data


def test_single_workspace_entry_preserves_integration_parameters() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/workspace?projectId=9&token=temporary-token&hostOrigin=https%3A%2F%2Fhost.example",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert response.headers["location"] == (
            "/?projectId=9&token=temporary-token&hostOrigin=https%3A%2F%2Fhost.example&workspace=1"
        )


def test_no_builtin_project_is_created() -> None:
    with TestClient(app) as client:
        projects = client.get("/api/projects").json()
        assert all(project["name"] != "默认预测项目" for project in projects)
        assert all("is_demo" not in project for project in projects)


def test_full_project_import_and_prediction_flow() -> None:
    with TestClient(app) as client:
        project_name = f"接口联调-{uuid4().hex[:8]}"
        project_response = client.post("/api/projects", json={"name": project_name})
        assert project_response.status_code == 201, project_response.text
        project = project_response.json()
        project_id = project["id"]

        population_file = WORKSPACE_ROOT / "测试数据" / "预测参数" / "PopPre_Parameters (3).xlsx"
        with population_file.open("rb") as stream:
            response = client.post(
                f"/api/projects/{project_id}/parameters/population/import",
                files={"file": (population_file.name, stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["duration"] == 5
        birth_rates = response.json()["data"]["birthRates"]
        assert set(birth_rates) == {"全国（中预测）", "天津市"}
        assert birth_rates["全国（中预测）"]["2031"] == 4.43
        assert birth_rates["天津市"]["2027"] == 4.89
        response = client.get(f"/api/projects/{project_id}/parameters/population/template")
        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        saved_population_file = Path(project["path"]) / "input" / "PopPre_Parameters.xlsx"
        saved_population_content = saved_population_file.read_bytes()
        response = client.post(
            f"/api/projects/{project_id}/parameters/population/import",
            files={"file": ("损坏参数.xlsx", b"not-an-excel-file", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == 422, response.text
        assert saved_population_file.read_bytes() == saved_population_content

        facility_file = WORKSPACE_ROOT / "测试数据" / "预测参数" / "FacPre_Parameters (1).xlsx"
        with facility_file.open("rb") as stream:
            response = client.post(
                f"/api/projects/{project_id}/parameters/facility/import",
                files={"file": (facility_file.name, stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "ready"
        assert response.json()["data"]["missingRequired"] == []
        response = client.get(f"/api/projects/{project_id}/parameters/facility/template")
        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        response = client.get(f"/api/projects/{project_id}/communities/template")
        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        community_template = load_workbook(BytesIO(response.content), data_only=True)
        assert {"填写说明", "社区基本信息", "社区人口列表", "助餐设施", "养老设施", "托育设施", "停车充电设施", "公共活动场地", "机动车充电桩列表", "闲置空间列表"} <= set(community_template.sheetnames)
        assert [cell.value for cell in community_template["社区人口列表"][1]] == ["序号", "性别", "出生年份", "年龄"]
        community_template.close()

        community_file = WORKSPACE_ROOT / "测试数据" / "610103-D 《社区基本信息与服务设施信息调研表》.xlsx"
        with community_file.open("rb") as stream:
            response = client.post(
                f"/api/projects/{project_id}/communities/import",
                files={"file": (community_file.name, stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 200, response.text
        import_report = response.json()
        assert import_report["success_count"] == 1
        assert import_report["created_count"] == 1
        assert import_report["updated_count"] == 0
        assert import_report["failed_count"] == 0
        assert import_report["issues"] == []
        community = import_report["community"]
        assert community["code"]
        assert community["facilities"]["停车充电设施"]["停车位数量（个）"] == 1318
        assert len(community["facilities"]["机动车充电桩列表"]) == 3

        with community_file.open("rb") as stream:
            response = client.post(
                f"/api/projects/{project_id}/communities/import",
                files={"file": (community_file.name, stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 200, response.text
        update_report = response.json()
        assert update_report["success_count"] == 1
        assert update_report["created_count"] == 0
        assert update_report["updated_count"] == 1

        response = client.post(f"/api/projects/{project_id}/predictions/population", json={"seed": 20260825})
        assert response.status_code == 200, response.text
        population_run = response.json()
        assert population_run["status"] == "success"

        response = client.get(f"/api/runs/{population_run['id']}/results")
        assert response.status_code == 200
        assert len(response.json()) == 5

        response = client.get(f"/api/runs/{population_run['id']}/download")
        assert response.status_code == 200
        assert response.content.startswith(b"PK")

        response = client.put(
            f"/api/projects/{project_id}/parameters/facility",
            json={"data": _complete_facility_parameters()},
        )
        assert response.status_code == 200, response.text

        response = client.post(
            f"/api/projects/{project_id}/predictions/facility",
            json={
                "seed": 20260825,
                "population_run_id": population_run["id"],
                "generate_report": True,
                "report_mode": "overall",
            },
        )
        assert response.status_code == 200, response.text
        facility_run = response.json()
        assert facility_run["status"] == "success"
        first_facility_output = Path(facility_run["output_file"])
        facility_workbook = load_workbook(first_facility_output, data_only=True, read_only=True)
        facility_sheet = facility_workbook[facility_workbook.sheetnames[0]]
        exported_category_counts = Counter(
            row[0]
            for row in facility_sheet.iter_rows(min_row=2, values_only=True)
            if row[0] and row[1] != "选址建议"
        )
        assert exported_category_counts == {
            "助餐设施": 7,
            "养老服务设施": 9,
            "托育服务设施": 8,
            "停车充电设施": 4,
            "公共活动场地": 2,
        }
        facility_workbook.close()

        response = client.post(f"/api/runs/{facility_run['id']}/report", json={"report_mode": "overall"})
        assert response.status_code == 200, response.text
        assert response.json()["report_available"] is True
        assert response.json()["filename"].endswith(".docx")

        response = client.get(f"/api/runs/{facility_run['id']}/results")
        assert response.status_code == 200
        first_metrics = response.json()[0]["data"]["metrics"]
        assert "停车充电设施/机动车充电桩缺口数量（户均法）" in first_metrics
        assert "停车充电设施/机动车充电桩缺口数量（新能源车保有量法）" in first_metrics
        assert "养老服务设施/保健康复服务需求人数" in first_metrics
        assert "托育服务设施/幼儿园室外活动场地面积" in first_metrics
        first_result_data = response.json()[0]["data"]
        assert first_result_data["siteSuggestions"]["助餐设施"]
        assert first_result_data["siteAnalysis"]["助餐设施"]["targetYear"] == 2027
        assert first_result_data["siteAnalysis"]["助餐设施"]["candidateCount"] == len(community["idle_spaces"])
        assert "未录入闲置空间" in first_result_data["siteSuggestions"]["助餐设施"]
        assert list(Path(project["path"]).glob(f"output/PreReport_run{facility_run['id']}_整体_*.docx"))
        response = client.get(f"/api/runs/{facility_run['id']}/report")
        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        generated_report = Document(BytesIO(response.content))
        chart_descriptions = [shape._inline.docPr.get("descr", "") for shape in generated_report.inline_shapes]
        assert any("人口年度分组柱状图" in description for description in chart_descriptions)
        assert all("折线图" not in description for description in chart_descriptions)
        report_cells = {cell.text for table in generated_report.tables for row in table.rows for cell in row.cells}
        assert {"2027年", "2028年", "2029年", "2030年", "2031年"} <= report_cells
        report_text = "\n".join(paragraph.text for paragraph in generated_report.paragraphs)
        assert f"设施预测批次 #{facility_run['id']}" in report_text
        assert "正值进入新增选址分析，负值表示现有供给富余" in report_text
        assert "缺口类指标为正值时表示供给不足，负值表示供给富余" in report_text

        second_community_payload = {
            "code": "TEST-SECOND",
            "name": "第二测试社区",
            "region": community["region"],
            "households": 800,
            "average_household_size": 2.4,
            "migration_rates": community["migration_rates"],
            "age_counts": community["age_counts"],
            "facilities": community["facilities"],
            "idle_spaces": community["idle_spaces"],
        }
        response = client.post(f"/api/projects/{project_id}/communities", json=second_community_payload)
        assert response.status_code == 201, response.text
        second_community = response.json()
        response = client.post(f"/api/projects/{project_id}/predictions/population", json={"seed": 20260825})
        assert response.status_code == 200, response.text
        second_population_run = response.json()
        response = client.post(
            f"/api/projects/{project_id}/predictions/facility",
            json={
                "seed": 20260825,
                "population_run_id": second_population_run["id"],
                "generate_report": True,
                "report_mode": "community",
                "community_id": second_community["id"],
            },
        )
        assert response.status_code == 200, response.text
        second_facility_run = response.json()
        second_facility_output = Path(second_facility_run["output_file"])
        assert second_facility_output != first_facility_output
        assert first_facility_output.exists() and second_facility_output.exists()
        response = client.get(f"/api/runs/{second_facility_run['id']}/report")
        assert response.status_code == 200
        second_report = Document(BytesIO(response.content))
        second_report_text = "\n".join(paragraph.text for paragraph in second_report.paragraphs)
        assert "TEST-SECOND-第二测试社区" in second_report_text
        assert f"设施预测批次 #{second_facility_run['id']}" in second_report_text

        response = client.get(f"/api/runs/{second_facility_run['id']}/backup")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/zip")
        with ZipFile(BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            assert {"manifest.json", "results.json"} <= names
            assert any(name.startswith("files/PreResult_fac_run") for name in names)
            assert any(name.startswith("files/PreReport_run") for name in names)

        response = client.delete(f"/api/runs/{second_population_run['id']}")
        assert response.status_code == 409
        assert f"#{second_facility_run['id']}" in response.json()["detail"]

        response = client.delete(f"/api/runs/{second_facility_run['id']}")
        assert response.status_code == 204, response.text
        assert not second_facility_output.exists()
        assert first_facility_output.exists()
        assert client.get(f"/api/runs/{second_facility_run['id']}/results").status_code == 404
        assert list((WORKSPACE_ROOT / "runtime" / "trash" / "runs").glob(f"预测批次_{second_facility_run['id']}_*.zip"))

        response = client.delete(f"/api/projects/{project_id}/communities/{community['id']}")
        assert response.status_code == 409

        response = client.get("/api/projects/99999999/dashboard")
        assert response.status_code == 404

        renamed = f"已重命名-{uuid4().hex[:8]}"
        response = client.patch(f"/api/projects/{project_id}", json={"name": renamed})
        assert response.status_code == 200, response.text
        assert response.json()["name"] == renamed

        response = client.delete(f"/api/projects/{project_id}")
        assert response.status_code == 204, response.text
        response = client.get("/api/projects")
        assert all(item["id"] != project_id for item in response.json())
        assert list((WORKSPACE_ROOT / "runtime" / "trash" / "projects").glob(f"*-{project_id}-*")) or list(
            (WORKSPACE_ROOT / "runtime" / "trash" / "projects").glob(f"*_{project_id}_*")
        )


def test_community_import_returns_field_validation_report() -> None:
    workbook = Workbook()
    base_sheet = workbook.active
    base_sheet.title = "社区基本信息"
    base_sheet.append(["字段", "值"])
    base_sheet.append(["社区编号", "异常/编号"])
    base_sheet.append(["社区名称", ""])
    base_sheet.append(["总户数", -3])
    population_sheet = workbook.create_sheet("社区人口列表")
    population_sheet.append(["姓名", "年龄"])
    population_sheet.append(["测试居民", 130])
    content = BytesIO()
    workbook.save(content)
    workbook.close()

    with TestClient(app) as client:
        project_response = client.post("/api/projects", json={"name": f"导入校验-{uuid4().hex[:8]}"})
        project_id = project_response.json()["id"]
        response = client.post(
            f"/api/projects/{project_id}/communities/import",
            files={"file": ("异常社区.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["success_count"] == 0
        assert report["failed_count"] == 1
        assert report["community"] is None
        assert {issue["field"] for issue in report["issues"]} >= {"社区编号", "社区名称", "总户数", "年龄"}
        assert client.get(f"/api/projects/{project_id}/communities").json() == []
        client.delete(f"/api/projects/{project_id}")


def test_audit_validation_and_failed_run_state() -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": f"审计回归-{uuid4().hex[:8]}"}).json()
        pid = project["id"]
        try:
            assert client.post("/api/projects", json={"name": "   "}).status_code == 422
            base = f"/api/projects/{pid}"
            first = client.post(base + "/communities", json={"code": "A", "name": "甲"}).json()
            second = client.post(base + "/communities", json={"code": "B", "name": "乙"}).json()
            response = client.put(base + f"/communities/{second['id']}", json={"code": "A", "name": "乙"})
            assert response.status_code == 409, response.text
            assert client.post(base + "/predictions/population", json={}).status_code == 422
            runs = client.get(base + "/runs").json()
            assert runs[0]["status"] == "failed"
            parameter_url = base + "/parameters/population"
            original = client.get(parameter_url).json()["data"]
            invalid = {**original, "duration": 0}
            assert client.put(parameter_url, json={"data": invalid}).status_code == 422
            assert client.get(parameter_url).json()["data"] == original
            assert client.put(parameter_url, json={"data": original}).status_code == 200
            saved = load_workbook(Path(project["path"]) / "input" / "PopPre_Parameters.xlsx", data_only=True)
            assert saved["基础参数"].cell(3, 2).value == original["duration"]
            saved.close()
            response = client.post(base + "/predictions/facility", json={"generate_report": True, "community_id": first["id"]})
            assert response.status_code == 422
            assert len(client.get(base + "/runs").json()) == len(runs)
        finally:
            client.delete(f"/api/projects/{pid}")


@pytest.mark.parametrize("duration", [1, 10])
def test_report_covers_configured_horizon(duration):
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": f"年度回归-{uuid4().hex[:8]}"}).json()
        base = f"/api/projects/{project['id']}"
        try:
            response = client.post(base + "/communities", json={"code": "YEAR", "name": "年度测试社区", "age_counts": {"30": 1000, "65": 100}})
            assert response.status_code == 201, response.text
            population = client.get(base + "/parameters/population").json()["data"]
            population["duration"] = duration
            assert client.put(base + "/parameters/population", json={"data": population}).status_code == 200
            response = client.post(base + "/predictions/population", json={})
            assert response.status_code == 200, response.text
            pop_run = response.json()
            assert client.put(base + "/parameters/facility", json={"data": _complete_facility_parameters()}).status_code == 200
            response = client.post(base + "/predictions/facility", json={"population_run_id": pop_run["id"], "generate_report": True, "report_mode": "overall"})
            assert response.status_code == 200, response.text
            run = response.json()
            results = client.get(f"/api/runs/{run['id']}/results").json()
            assert len(results) == duration
            report = Document(BytesIO(client.get(f"/api/runs/{run['id']}/report").content))
            cells = {cell.text for table in report.tables for row in table.rows for cell in row.cells}
            assert {f"{2027 + i}年" for i in range(duration)} <= cells
            assert len(report.inline_shapes) >= 1
            chart_descriptions = [shape._inline.docPr.get("descr", "") for shape in report.inline_shapes]
            assert any("总人口、总户数及8个年龄段" in description for description in chart_descriptions)
        finally:
            client.delete(base)


def test_community_details_timestamps_and_project_history_clear():
    from datetime import datetime, timezone
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": f"社区详情验收-{uuid4().hex[:8]}"}).json()
        base = f"/api/projects/{project['id']}"
        try:
            stamp = datetime.fromisoformat(project["created_at"].replace("Z", "+00:00"))
            assert stamp.tzinfo is not None
            assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60
            payload = {"code":"DETAIL", "name":"详情测试", "region":"全国", "population_base_year":2026,
                       "population_records":[{"序号":1,"性别":"男","出生年份":1990}, {"序号":2,"性别":"女","出生年份":2025}],
                       "facilities":{"助餐设施":{"社区食堂建筑面积（平方米）":100},"机动车充电桩列表":[{"机动车充电桩编号":"C1","建设年份":2025,"经度":117,"纬度":39}]},
                       "idle_spaces":[{"闲置空间编号":"S1","待分配建筑面积（平方米）":200,"待分配用地面积（平方米）":300,"经度":117,"纬度":39}]}
            response=client.post(base+"/communities",json=payload)
            assert response.status_code==201,response.text
            community=response.json()
            assert community["age_counts"]=={"36":1,"1":1}
            assert len(community["population_records"])==2
            payload["population_records"].append({"序号":3,"性别":"女","出生年份":2000})
            payload["facilities"]["助餐设施"]["社区食堂建筑面积（平方米）"]=150
            response=client.put(base+f"/communities/{community['id']}",json=payload)
            assert response.status_code==200,response.text
            assert response.json()["age_counts"]["26"]==1
            assert client.get(base+"/communities").json()[0]["facilities"]["助餐设施"]["社区食堂建筑面积（平方米）"]==150
            invalid={**payload,"population_records":[{"序号":1,"性别":"男","出生年份":2027}]}
            assert client.put(base+f"/communities/{community['id']}",json=invalid).status_code==422
            wrong_year={**payload,"population_base_year":2025}
            assert client.put(base+f"/communities/{community['id']}",json=wrong_year).status_code==200
            assert client.post(base+"/predictions/population",json={}).status_code==422
            assert client.put(base+f"/communities/{community['id']}",json=payload).status_code==200
            response=client.post(base+"/predictions/population",json={})
            assert response.status_code==200,response.text
            population=response.json()
            assert population["community_names"]==["DETAIL-详情测试"]
            assert population["forecast_years"]==[2027,2028,2029,2030,2031]
            assert population["project_name"]==project["name"]
            assert client.put(base+"/parameters/facility",json={"data":_complete_facility_parameters()}).status_code==200
            response=client.post(base+"/predictions/facility",json={"population_run_id":population["id"]})
            assert response.status_code==200,response.text
            # Renaming the current community must not relabel newly snapshotted history.
            payload["name"]="已更名"
            assert client.put(base+f"/communities/{community['id']}",json=payload).status_code==200
            assert client.get(f"/api/runs/{population['id']}/results").json()[0]["communityName"]=="详情测试"
            assert client.post(base+"/runs/clear",json=[]).status_code==409
            runs=client.get(base+"/runs").json()
            response=client.post(base+"/runs/clear",json=[run["id"] for run in runs])
            assert response.status_code==200,response.text
            assert response.json()["deleted_count"]==len(runs)
            assert client.get(base+"/runs").json()==[]
            assert len(client.get(base+"/communities").json())==1
            assert client.get(base+"/parameters/population").status_code==200
            assert list((WORKSPACE_ROOT/"runtime"/"trash"/"runs").glob(f"clear_*_预测批次_{population['id']}_*.zip"))
        finally:
            client.delete(base)


def test_uploaded_survey_workbook_preserves_population_and_all_sections():
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"name":f"八项导入-{uuid4().hex[:8]}"}).json()
        base=f"/api/projects/{project['id']}"
        try:
            survey_file=WORKSPACE_ROOT/"测试数据"/"复兴社区调研数据.xlsx"
            with survey_file.open("rb") as stream:
                response=client.post(base+"/communities/import",files={"file":(survey_file.name,stream,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
            assert response.status_code==200,response.text
            report=response.json()
            assert report["success_count"]==1,report
            community=report["community"]
            assert community["name"]=="复兴社区"
            assert community["population_base_year"]==2026
            assert len(community["population_records"])==sum(community["age_counts"].values())
            assert len(community["population_records"])==20000
            assert len(community["idle_spaces"])==0
            assert len(community["facilities"]["机动车充电桩列表"])==8
            assert {"助餐设施","养老设施","托育设施","停车充电设施"} <= community["facilities"].keys()
        finally:
            client.delete(base)


def test_nonstandard_community_survey_is_recognized_and_converted():
    workbook = Workbook()
    main = workbook.active
    main.title = "社区基本信息与设施信息调研表 "
    main.cell(3, 1, "填表日期：2026年8月")
    for row, label, value in (
        (5, "省级行政区", "陕西省"),
        (6, "社区编号", "610103-D"),
        (7, "社区名称", "文艺路街道建科大社区"),
        (8, "社区总户数", 2),
        (9, "常住人口数量", 4),
    ):
        main.cell(row, 4, label)
        main.cell(row, 5, value)
    sections = (
        (20, "1.2 幼儿园", (("建筑面积（单位：平方米）", 800), ("用地面积（单位：平方米）", 1200), ("托育人数（单位：人）", 90))),
        (26, "1.3 托儿所", (("建筑面积（单位：平方米）", 300), ("托育人数（单位：人）", 30))),
        (31, "1.4 老年服务站", (("建筑面积（单位：平方米）", 500), ("容纳量（单位：人）", 60))),
        (36, "2.3 社区食堂", (("建筑面积（单位：平方米）", 200),)),
        (39, "3.2 停车及充电设施", (("机动车停车位数量（单位：个）", 100), ("机动车充电桩（单位：个）", 12))),
    )
    for start, heading, rows in sections:
        main.cell(start, 1, heading)
        for offset, (label, value) in enumerate(rows, 1):
            main.cell(start + offset, 4, label)
            main.cell(start + offset, 5, value)

    population = workbook.create_sheet("7.2 社区人口性别和出生年月统计")
    population.append(["序号", "性别", "出生年月", "年龄"])
    population.append([None, None, None, None])
    population.append([1, "男", None, 20])
    population.append([2, "女", None, 40])
    population.append([3, "未知", None, 70])
    population.append([4, "女", None, None])

    chargers = workbook.create_sheet("3.2停车及充电设施")
    chargers.append([])
    chargers.append([])
    chargers.append(["设施编号", "设施类别", "经度", "纬度"])
    chargers.append(["CH-1", "机动车充电桩", 108.96, 34.23])
    activity = workbook.create_sheet("4.1公共活动场地")
    activity.append([])
    activity.append([])
    activity.append(["设施编号", "类型", "备注", "公共活动面积", "运动场地面积"])
    activity.append(["A-1", "广场", None, 120, 80])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": f"调研表转换-{uuid4().hex[:8]}"}).json()
        base = f"/api/projects/{project['id']}"
        try:
            response = client.post(
                base + "/communities/import",
                files={"file": ("综合调研表.xlsx", stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            assert response.status_code == 200, response.text
            report = response.json()
            assert report["success_count"] == 1, report
            assert report["created_count"] == 1
            assert len(report["warnings"]) >= 3
            community = report["community"]
            assert community["code"] == "610103-D"
            assert community["region"] == "陕西省"
            assert community["population_base_year"] == 2026
            assert community["age_counts"] == {"20": 1, "40": 1, "70": 1}
            assert community["facilities"]["托育设施"]["现有托儿所托育人数（人）"] == 30
            assert community["facilities"]["托育设施"]["现有幼儿园托育人数（人）"] == 90
            assert community["facilities"]["机动车充电桩列表"][0]["机动车充电桩编号"] == "CH-1"
            assert community["facilities"]["公共活动场地"]["公共活动场地面积（平方米）"] == 120
        finally:
            client.delete(base)


def test_survey_age_summary_is_used_when_resident_rows_are_blank():
    workbook = Workbook()
    main = workbook.active
    main.title = "社区基本信息与设施信息调研表 "
    main.cell(3, 1, "填写时间：2026年9月17日")
    values = (
        (5, "省级行政区", "天津市"),
        (6, "社区编号", "120104-A"),
        (7, "社区名称", "晨光社区"),
        (8, "社区总户数（单位：户）", 3200),
        (9, "常住人口数量（单位：人）", 8516),
        (10, "0-6岁（单位：人）", 325),
        (11, "7-12岁（单位：人）", 583),
        (12, "13-17岁（单位：人）", 437),
        (13, "18-35岁（单位：人）", 2536),
        (14, "36-59岁（单位：人）", 3715),
        (15, "60-69岁（单位：人）", 632),
        (16, "70-79岁（单位：人）", 206),
        (17, "80岁以上（单位：人）", 82),
        (18, "男性人口数量（单位：人）", 3986),
        (19, "女性人口数量（单位：人）", 4530),
    )
    for row, label, value in values:
        main.cell(row, 4, label)
        main.cell(row, 5, value)

    population = workbook.create_sheet("7.2 社区人口性别和出生年月统计")
    population.append(["序号", "性别", "出生年份", "年龄"])
    population.append(["例：", "女", 1967, 59])
    population.append([1, None, None, None])
    population.append([2, None, None, None])

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": f"年龄汇总转换-{uuid4().hex[:8]}"}).json()
        base = f"/api/projects/{project['id']}"
        try:
            response = client.post(
                base + "/communities/import",
                files={"file": ("年龄汇总调研表.xlsx", stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            assert response.status_code == 200, response.text
            report = response.json()
            community = report["community"]
            assert len(community["population_records"]) == 8516
            assert sum(row["性别"] == "男" for row in community["population_records"]) == 4363
            assert sum(row["性别"] == "女" for row in community["population_records"]) == 4153
            assert max(row["年龄"] for row in community["population_records"]) == 100
            assert all(row["出生年份"] + row["年龄"] == 2026 for row in community["population_records"])
            assert all(key.isdigit() for key in community["age_counts"])
            assert sum(community["age_counts"].values()) == 8516
            assert sum(community["age_counts"].get(str(age), 0) for age in range(0, 7)) == 325
            assert sum(community["age_counts"].get(str(age), 0) for age in range(18, 36)) == 2536
            assert sum(community["age_counts"].get(str(age), 0) for age in range(36, 60)) == 3715
            assert max(community["age_counts"].get(str(age), 0) for age in range(18, 36)) - min(community["age_counts"].get(str(age), 0) for age in range(18, 36)) <= 1
            assert not any("非实名模拟人口" in warning for warning in report["warnings"])
            assert not any("已识别为综合调研表" in warning for warning in report["warnings"])
        finally:
            client.delete(base)


def test_survey_import_tolerates_shifted_columns_fuzzy_sheet_names_and_empty_fill_style():
    workbook = Workbook()
    main = workbook.active
    main.title = "社区基本信息及服务设施调研"
    main.cell(1, 1, "社区基本信息与服务设施调研表")
    main.cell(3, 1, "填写时间：2026年10月")
    main.cell(4, 2, "信息数据")
    main.cell(4, 3, "指标值")
    for row, label, value in (
        (5, "省级行政区", "安徽省"),
        (6, "社区编号", "340100-Z"),
        (7, "社区名称", "弹性格式社区"),
        (8, "社区总户数（单位：户）", 40),
        (9, "常住人口数量（单位：人）", 101),
    ):
        main.cell(row, 2, label)
        main.cell(row, 3, value)

    population = workbook.create_sheet("居民人口性别出生年龄")
    population.append(["说明"])
    population.append(["序号", "性别", "出生年份", "年龄"])
    population.append([1, None, None, None])
    chargers = workbook.create_sheet("3.2 停车及充电设施")
    chargers.append([])
    chargers.append([])
    chargers.append(["设施编号", "类型", "经度", "纬度"])
    chargers.append(["340100-Z-3.2-1", "机动车充电桩", "117.1234°E", "31.5678°N"])

    original = BytesIO()
    workbook.save(original)
    malformed = BytesIO()
    with ZipFile(BytesIO(original.getvalue())) as source, ZipFile(malformed, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "xl/styles.xml":
                content = content.replace(b"</fills>", b"<fill/></fills>")
            target.writestr(item, content)
    malformed.seek(0)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": f"弹性调研表-{uuid4().hex[:8]}"}).json()
        base = f"/api/projects/{project['id']}"
        try:
            response = client.post(
                base + "/communities/import",
                files={"file": ("弹性格式.xlsx", malformed, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            assert response.status_code == 200, response.text
            report = response.json()
            assert report["success_count"] == 1, report
            community = report["community"]
            assert community["code"] == "340100-Z"
            assert sum(community["age_counts"].values()) == 101
            assert len(community["population_records"]) == 101
            assert {row["年龄"] for row in community["population_records"]} == set(range(101))
            assert community["facilities"]["机动车充电桩列表"][0]["经度"] == pytest.approx(117.1234)
            assert community["facilities"]["机动车充电桩列表"][0]["纬度"] == pytest.approx(31.5678)
        finally:
            client.delete(base)
