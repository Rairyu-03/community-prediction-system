from copy import deepcopy
import random

import pytest
from pydantic import ValidationError

from app.defaults import DEFAULT_POPULATION_PARAMETERS, DEFAULT_FACILITY_PARAMETERS
from app.schemas import CommunityCreate, ProjectCreate
from app.services.prediction_service import advance_population
from app.services.validation_service import validate_parameters


@pytest.mark.parametrize("name", [" ", "\t\n", "bad/name"])
def test_invalid_project_name(name):
    with pytest.raises(ValidationError):
        ProjectCreate(name=name)


@pytest.mark.parametrize("fields", [
    {"age_counts": {"20": -1}},
    {"age_counts": {"121": 1}},
    {"age_counts": {"20": 1, "0-3岁": 1}},
    {"migration_rates": {"0-3岁": 1001}},
    {"migration_rates": {"0-3岁": float("nan")}},
    {"idle_spaces": [{"待分配建筑面积（平方米）": -1}]},
    {"idle_spaces": [{"纬度": 91}]},
    {"facilities": {"助餐设施": {"建筑面积": -1}}},
    {"facilities": {"机动车充电桩列表": [{"建设年份": 2026.5}]}},
])
def test_invalid_community(fields):
    with pytest.raises(ValidationError):
        CommunityCreate(code="TEST", name="测试", **fields)


@pytest.mark.parametrize("field,value", [("duration", 0), ("duration", 2.5), ("duration", 101), ("startYear", ""), ("startYear", float("inf"))])
def test_invalid_population_parameters(field, value):
    data = deepcopy(DEFAULT_POPULATION_PARAMETERS)
    data[field] = value
    with pytest.raises(ValueError):
        validate_parameters("population", data)


@pytest.mark.parametrize("field,value", [("demandRate", 101), ("demandRate", -1), ("diningAreaPerPerson", float("nan"))])
def test_invalid_facility_parameters(field, value):
    data = deepcopy(DEFAULT_FACILITY_PARAMETERS)
    data["meal"][field] = value
    with pytest.raises(ValueError):
        validate_parameters("facility", data)


def test_ageing_preserves_oldest_population():
    counts = [0] * 121
    counts[119], counts[120] = 3, 7
    result = advance_population(counts, 2, {}, random.Random(1))
    assert result[120] == 10
    assert sum(result) == 12


def test_mortality_uses_previous_cohort_not_newborns():
    counts = [0] * 121
    counts[4] = 10
    result = advance_population(counts, 5, {"0-4岁": 1000}, random.Random(1))
    assert result[0] == 5
    assert sum(result) == 5


def test_empty_optional_region_can_be_imported():
    data = deepcopy(DEFAULT_POPULATION_PARAMETERS)
    data["birthRates"]["未填写地区"] = {}
    validate_parameters("population", data)


def test_excel_sheet_names_are_safe_and_unique():
    from openpyxl import Workbook
    from app.services.excel_service import result_sheet_title
    workbook = Workbook()
    name = "社区/名称:测试" * 8
    first = result_sheet_title(workbook, name)
    workbook.create_sheet(first)
    second = result_sheet_title(workbook, name)
    assert len(first) <= 31 and len(second) <= 31
    assert first != second
    assert "/" not in first and ":" not in first


def test_demo_initialization_does_not_overwrite_existing_edits_or_recreate_history(tmp_path):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Project, Community, ParameterSet, PredictionRun
    from app.services.demo_service import ensure_default_demo_project
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="默认预测项目", path=str(tmp_path))
        db.add(project)
        db.flush()
        db.add_all([ParameterSet(project_id=project.id, kind="population", data={"duration": 9}), ParameterSet(project_id=project.id, kind="facility", data={})])
        db.add(Community(project_id=project.id, code="EDIT", name="用户修改后的社区"))
        db.commit()
        ensure_default_demo_project(db)
        assert db.scalar(select(Community)).name == "用户修改后的社区"
        assert db.scalar(select(ParameterSet).where(ParameterSet.kind == "population")).data["duration"] == 9
        assert list(db.scalars(select(PredictionRun))) == []


def test_clear_rejects_running_prediction(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Project, PredictionRun
    from app.services.run_service import clear_project_runs
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="运行中工程", path=str(tmp_path))
        db.add(project)
        db.flush()
        run = PredictionRun(project_id=project.id, kind="population", status="running")
        db.add(run)
        db.commit()
        with pytest.raises(ValueError, match="正在运行"):
            clear_project_runs(db, project, [run.id])
        assert db.get(PredictionRun, run.id) is not None
