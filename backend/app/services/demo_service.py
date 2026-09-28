from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..demo_data import (
    DEMO_COMMUNITY,
    DEMO_COMMUNITY_CODE,
    DEMO_FACILITY_PARAMETERS,
    DEMO_POPULATION_PARAMETERS,
    DEMO_PROJECT_NAME,
)
from ..models import Community, ParameterSet, PredictionRun, Project
from .prediction_service import run_facility_prediction, run_population_prediction
from .project_service import create_project
from .report_service import generate_facility_report


def ensure_default_demo_project(db: Session, *, generate_outputs: bool = True) -> Project:
    """Create or repair the built-in Qingyou Xili example without duplicating runs."""
    project = db.scalar(select(Project).where(Project.name == DEMO_PROJECT_NAME))
    if project is None:
        project = create_project(db, DEMO_PROJECT_NAME)
    elif project.communities and {item.kind for item in project.parameter_sets} >= {"population", "facility"}:
        # Seed once. User edits and explicit history clearing must survive restart.
        return project

    for kind, demo_data in (
        ("population", DEMO_POPULATION_PARAMETERS),
        ("facility", DEMO_FACILITY_PARAMETERS),
    ):
        parameter = db.scalar(
            select(ParameterSet).where(ParameterSet.project_id == project.id, ParameterSet.kind == kind)
        )
        if parameter is None:
            parameter = ParameterSet(project_id=project.id, kind=kind, data=deepcopy(demo_data))
            db.add(parameter)
        else:
            parameter.data = deepcopy(demo_data)
            parameter.source_file = None

    community = db.scalar(
        select(Community).where(
            Community.project_id == project.id,
            Community.code == DEMO_COMMUNITY_CODE,
        )
    )
    if community is None:
        community = Community(project_id=project.id, **deepcopy(DEMO_COMMUNITY))
        db.add(community)
    else:
        for field, value in DEMO_COMMUNITY.items():
            setattr(community, field, deepcopy(value))
        community.source_file = None
    db.commit()
    db.refresh(project)

    if not generate_outputs:
        return project

    population_run = db.scalar(
        select(PredictionRun)
        .where(
            PredictionRun.project_id == project.id,
            PredictionRun.kind == "population",
            PredictionRun.status == "success",
        )
        .order_by(PredictionRun.id.desc())
    )
    if population_run is None or not population_run.output_file or not Path(population_run.output_file).exists():
        population_run = run_population_prediction(db, project, seed=20260825)

    facility_run = db.scalar(
        select(PredictionRun)
        .where(
            PredictionRun.project_id == project.id,
            PredictionRun.kind == "facility",
            PredictionRun.status == "success",
        )
        .order_by(PredictionRun.id.desc())
    )
    report_exists = facility_run is not None and any(
        (Path(project.path) / "output").glob(f"PreReport_run{facility_run.id}_*.docx")
    )
    if facility_run is None or not facility_run.output_file or not Path(facility_run.output_file).exists():
        facility_run = run_facility_prediction(db, project, seed=20260825, population_run_id=population_run.id)
        report_exists = False
    if not report_exists:
        generate_facility_report(db, project, facility_run, mode="community", community_id=community.id)
    return project
