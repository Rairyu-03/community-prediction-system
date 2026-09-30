from __future__ import annotations

import shutil
import logging
from io import BytesIO
from contextlib import asynccontextmanager
from pathlib import Path
import os
import sys
from typing import Annotated, Any
from urllib.parse import quote, urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, get_db, init_db
from .models import Community, ParameterSet, PredictionResult, PredictionRun, Project
from .schemas import (
    CommunityCreate,
    CommunityImportReport,
    CommunityRead,
    DashboardRead,
    FacilityPredictionRequest,
    ParameterRead,
    ParameterUpdate,
    PredictionRequest,
    PredictionRunRead,
    ReportGenerationRequest,
    ProjectCreate,
    ProjectImport,
    ProjectRead,
    ProjectUpdate,
)
from .services.excel_service import (
    export_community_template,
    export_facility_parameters,
    export_population_parameters,
    finalize_facility_parameters,
    parse_community,
    parse_facility_parameters,
    parse_population_parameters,
    validate_community_workbook,
)
from .services.prediction_service import run_facility_prediction, run_population_prediction
from .services.project_service import archive_project, create_project, import_project, remove_legacy_builtin_project, rename_project, save_project_as
from .services.report_service import REPORT_FORMAT_VERSION, generate_facility_report
from .services.run_service import build_run_backup, delete_run, clear_project_runs
from .services.validation_service import validate_parameters
from .services.community_service import restore_population_details
from .services.calculation_service import explain_result
from .services.portability_service import build_project_archive, import_project_archive, build_system_backup, restore_system_backup
from .services.quality_service import inspect_project_quality


settings = get_settings()
build_id = os.environ.get("COMMUNITY_BUILD_ID", "development")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        remove_legacy_builtin_project(db)
        restore_population_details(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.1",
    description="完整社区设施需求预测与动态匹配模块 API",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prevent_stale_frontend_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    elif request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

def verify_host_token(
    authorization: Annotated[str | None, Header()] = None,
    access_token: Annotated[str | None, Query()] = None,
) -> None:
    if not settings.host_api_token:
        return
    if authorization != f"Bearer {settings.host_api_token}" and access_token != settings.host_api_token:
        raise HTTPException(status_code=401, detail="无效的宿主系统访问令牌")


ApiAuth = Annotated[None, Depends(verify_host_token)]
DbSession = Annotated[Session, Depends(get_db)]


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="工程不存在")
    return project


def get_parameter_or_404(db: Session, project_id: int, kind: str) -> ParameterSet:
    parameter = db.scalar(
        select(ParameterSet).where(ParameterSet.project_id == project_id, ParameterSet.kind == kind)
    )
    if not parameter:
        raise HTTPException(status_code=404, detail="参数集不存在")
    return parameter


@app.get(f"{settings.api_prefix}/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "community-prediction", "version": "1.0.1", "buildId": build_id}


@app.post(f"{settings.api_prefix}/client-errors", include_in_schema=False)
async def record_client_error(request: Request) -> dict[str, bool]:
    try:
        payload = await request.json()
    except Exception:
        payload = {"message": "无法解析浏览器错误内容"}
    logging.error(
        "浏览器前端异常；message=%s；stack=%s；url=%s",
        str(payload.get("message", ""))[:1000],
        str(payload.get("stack", ""))[:4000],
        str(payload.get("url", ""))[:1000],
    )
    return {"recorded": True}


@app.get(f"{settings.api_prefix}/module-config")
def module_config(_: ApiAuth) -> dict[str, Any]:
    return {
        "moduleId": "community-prediction",
        "name": settings.app_name,
        "apiPrefix": settings.api_prefix,
        "embedding": {"reactComponent": True, "iframe": True, "postMessage": True},
        "database": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
    }


@app.get(f"{settings.api_prefix}/storage-info")
def storage_info(_: ApiAuth) -> dict[str, Any]:
    database = Path(settings.database_url.split("///", 1)[1]).resolve() if settings.database_url.startswith("sqlite") else None
    return {"dataRoot": str(settings.projects_root.resolve().parent), "database": str(database) if database else "外部数据库", "projects": str(settings.projects_root.resolve()), "portable": True}


@app.get(f"{settings.api_prefix}/system/backup")
def backup_system(_: ApiAuth, db: DbSession) -> StreamingResponse:
    filename, content = build_system_backup(db)
    return StreamingResponse(BytesIO(content), media_type="application/zip", headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(filename)})


@app.post(f"{settings.api_prefix}/system/restore")
async def restore_system(file: Annotated[UploadFile, File()], _: ApiAuth, db: DbSession) -> dict:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="只支持系统备份 ZIP")
    try:
        projects = restore_system_backup(db, await file.read())
        return {"restoredCount":len(projects),"projects":[ProjectRead.model_validate(p) for p in projects]}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/projects", response_model=list[ProjectRead])
def list_projects(_: ApiAuth, db: DbSession) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.updated_at.desc())).all())


@app.post(f"{settings.api_prefix}/projects", response_model=ProjectRead, status_code=201)
def add_project(payload: ProjectCreate, _: ApiAuth, db: DbSession) -> Project:
    try:
        return create_project(db, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch(f"{settings.api_prefix}/projects/{{project_id}}", response_model=ProjectRead)
def edit_project(project_id: int, payload: ProjectUpdate, _: ApiAuth, db: DbSession) -> Project:
    project = get_project_or_404(db, project_id)
    try:
        return rename_project(db, project, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete(f"{settings.api_prefix}/projects/{{project_id}}", status_code=204)
def remove_project(project_id: int, _: ApiAuth, db: DbSession) -> None:
    project = get_project_or_404(db, project_id)
    try:
        archive_project(db, project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/export")
def export_project(project_id: int, _: ApiAuth, db: DbSession) -> StreamingResponse:
    project=get_project_or_404(db,project_id)
    filename,content=build_project_archive(db,project)
    return StreamingResponse(BytesIO(content),media_type="application/zip",headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(filename)})


@app.post(f"{settings.api_prefix}/projects/import-archive", response_model=ProjectRead, status_code=201)
async def import_project_zip(file: Annotated[UploadFile, File()], _: ApiAuth, db: DbSession, name: str | None = Form(default=None)) -> Project:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400,detail="只支持工程备份 ZIP")
    try:
        return import_project_archive(db,await file.read(),name)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/projects/import", response_model=ProjectRead, status_code=201)
def add_imported_project(payload: ProjectImport, _: ApiAuth, db: DbSession) -> Project:
    try:
        return import_project(db, Path(payload.source_path), payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/save-as", response_model=ProjectRead, status_code=201)
def project_save_as(
    project_id: int,
    target_parent: str,
    new_name: str,
    _: ApiAuth,
    db: DbSession,
) -> Project:
    project = get_project_or_404(db, project_id)
    try:
        return save_project_as(db, project, Path(target_parent), new_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/parameters/{{kind}}", response_model=ParameterRead)
def get_parameters(project_id: int, kind: str, _: ApiAuth, db: DbSession) -> ParameterRead:
    if kind not in {"population", "facility"}:
        raise HTTPException(status_code=400, detail="未知参数类型")
    parameter = get_parameter_or_404(db, project_id, kind)
    return ParameterRead(kind=parameter.kind, data=parameter.data, source_file=parameter.source_file, updated_at=parameter.updated_at)


@app.put(f"{settings.api_prefix}/projects/{{project_id}}/parameters/{{kind}}", response_model=ParameterRead)
def update_parameters(project_id: int, kind: str, payload: ParameterUpdate, _: ApiAuth, db: DbSession) -> ParameterRead:
    parameter = get_parameter_or_404(db, project_id, kind)
    try:
        validate_parameters(kind, payload.data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parameter.data = finalize_facility_parameters(payload.data) if kind == "facility" else payload.data
    project = get_project_or_404(db, project_id)
    filename = "PopPre_Parameters.xlsx" if kind == "population" else "FacPre_Parameters.xlsx"
    target = Path(project.path) / "input" / filename
    temporary = target.with_name(f"{target.stem}_{uuid4().hex}.xlsx")
    try:
        exporter = export_population_parameters if kind == "population" else export_facility_parameters
        exporter(temporary, parameter.data)
        temporary.replace(target)
    except OSError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="参数文件无法保存，请关闭占用该文件的 Excel 后重试") from exc
    finally:
        temporary.unlink(missing_ok=True)
    parameter.source_file = str(target)
    db.commit()
    db.refresh(parameter)
    return ParameterRead(kind=parameter.kind, data=parameter.data, source_file=parameter.source_file, updated_at=parameter.updated_at)


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/parameters/{{kind}}/template")
def download_parameter_template(project_id: int, kind: str, _: ApiAuth, db: DbSession) -> FileResponse:
    project = get_project_or_404(db, project_id)
    if kind not in {"population", "facility"}:
        raise HTTPException(status_code=400, detail="未知参数类型")
    parameter = get_parameter_or_404(db, project_id, kind)
    filename = "PopPre_Parameters.xlsx" if kind == "population" else "FacPre_Parameters.xlsx"
    target = Path(project.path) / "input" / filename
    if kind == "population":
        export_population_parameters(target, parameter.data)
    else:
        export_facility_parameters(target, parameter.data)
    return FileResponse(target, filename=filename)


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/parameters/{{kind}}/import", response_model=ParameterRead)
async def import_parameters_file(
    project_id: int,
    kind: str,
    file: Annotated[UploadFile, File()],
    _: ApiAuth,
    db: DbSession,
) -> ParameterRead:
    project = get_project_or_404(db, project_id)
    if kind not in {"population", "facility"}:
        raise HTTPException(status_code=400, detail="未知参数类型")
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 参数文件")
    target_name = "PopPre_Parameters.xlsx" if kind == "population" else "FacPre_Parameters.xlsx"
    target = Path(project.path) / "input" / target_name
    temp_target = Path(project.path) / "input" / f".upload_{kind}_{uuid4().hex}.xlsx"
    with temp_target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    try:
        data = parse_population_parameters(temp_target) if kind == "population" else parse_facility_parameters(temp_target)
        validate_parameters(kind, data)
    except Exception as exc:
        temp_target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    temp_target.replace(target)
    parameter = get_parameter_or_404(db, project_id, kind)
    parameter.data = data
    parameter.source_file = str(target)
    db.commit()
    db.refresh(parameter)
    return ParameterRead(kind=parameter.kind, data=parameter.data, source_file=parameter.source_file, updated_at=parameter.updated_at)


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/communities", response_model=list[CommunityRead])
def list_communities(project_id: int, _: ApiAuth, db: DbSession, q: str = Query(default="")) -> list[Community]:
    get_project_or_404(db, project_id)
    query = select(Community).where(Community.project_id == project_id)
    if q:
        query = query.where((Community.code.contains(q)) | (Community.name.contains(q)) | (Community.region.contains(q)))
    return list(db.scalars(query.order_by(Community.code)).all())


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/communities/template")
def download_community_template(project_id: int, _: ApiAuth, db: DbSession, community_id: int | None = None, blank: bool = False):
    project = get_project_or_404(db, project_id)
    parameters = get_parameter_or_404(db, project_id, "population")
    community = None
    if not blank:
        if community_id is not None:
            community = db.get(Community, community_id)
            if not community or community.project_id != project_id:
                raise HTTPException(status_code=404, detail="所选社区不属于当前工程")
        elif len(project.communities) == 1:
            community = project.communities[0]
        elif len(project.communities) > 1:
            raise HTTPException(status_code=400, detail="请先选择要导出的社区，或下载空白模板")
    stream = BytesIO()
    export_community_template(stream, int(parameters.data["startYear"]), community)
    stream.seek(0)
    name = f"{community.code}-{community.name}.xlsx" if community else "Community_Data_Template.xlsx"
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/communities", response_model=CommunityRead, status_code=201)
def add_community(project_id: int, payload: CommunityCreate, _: ApiAuth, db: DbSession) -> Community:
    get_project_or_404(db, project_id)
    community = Community(project_id=project_id, **payload.model_dump())
    db.add(community)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="社区编号已存在") from exc
    db.refresh(community)
    return community


@app.put(f"{settings.api_prefix}/projects/{{project_id}}/communities/{{community_id}}", response_model=CommunityRead)
def update_community(
    project_id: int,
    community_id: int,
    payload: CommunityCreate,
    _: ApiAuth,
    db: DbSession,
) -> Community:
    community = db.get(Community, community_id)
    if not community or community.project_id != project_id:
        raise HTTPException(status_code=404, detail="社区不存在")
    for key, value in payload.model_dump().items():
        setattr(community, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="社区编号已存在") from exc
    db.refresh(community)
    return community


@app.delete(f"{settings.api_prefix}/projects/{{project_id}}/communities/{{community_id}}", status_code=204)
def remove_community(project_id: int, community_id: int, _: ApiAuth, db: DbSession) -> None:
    community = db.get(Community, community_id)
    if not community or community.project_id != project_id:
        raise HTTPException(status_code=404, detail="社区不存在")
    result_count = db.scalar(select(func.count()).select_from(PredictionResult).where(PredictionResult.community_id == community_id)) or 0
    if result_count:
        raise HTTPException(status_code=409, detail="该社区已有历史预测结果，请先删除相关预测批次后再删除社区")
    db.delete(community)
    db.commit()


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/communities/import", response_model=CommunityImportReport)
async def import_community_file(
    project_id: int,
    file: Annotated[UploadFile, File()],
    _: ApiAuth,
    db: DbSession,
) -> CommunityImportReport:
    project = get_project_or_404(db, project_id)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 社区文件")
    safe_filename = Path(file.filename).name
    temp_target = Path(project.path) / "input" / f".upload_community_{uuid4().hex}.xlsx"
    with temp_target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    issues = validate_community_workbook(temp_target)
    if issues:
        temp_target.unlink(missing_ok=True)
        return CommunityImportReport(filename=safe_filename, failed_count=1, issues=issues)
    try:
        data = parse_community(temp_target)
        import_warnings = data.pop("_import_warnings", [])
        data = CommunityCreate.model_validate(data).model_dump()
    except Exception as exc:
        temp_target.unlink(missing_ok=True)
        return CommunityImportReport(
            filename=safe_filename,
            failed_count=1,
            issues=[{"field": "文件结构", "message": str(exc)}],
        )
    final_target = Path(project.path) / "input" / f"{data['code']}-{data['name']}.xlsx"
    if final_target != temp_target:
        temp_target.replace(final_target)
    community = db.scalar(
        select(Community).where(Community.project_id == project_id, Community.code == data["code"])
    )
    is_update = community is not None
    if is_update:
        for key, value in data.items():
            setattr(community, key, value)
    else:
        community = Community(project_id=project_id, **data)
        db.add(community)
    community.source_file = str(final_target)
    db.commit()
    db.refresh(community)
    return CommunityImportReport(
        filename=safe_filename,
        success_count=1,
        created_count=0 if is_update else 1,
        updated_count=1 if is_update else 0,
        warnings=[*import_warnings, *[f"人口序号{row.get('序号')}性别原值“{row['原始性别']}”无效，暂记为未知；原值保留，请在社区人口列表核实。" for row in data.get("population_records", []) if "原始性别" in row]],
        community=community,
    )


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/dashboard", response_model=DashboardRead)
def get_dashboard(project_id: int, _: ApiAuth, db: DbSession) -> DashboardRead:
    get_project_or_404(db, project_id)
    communities = list(db.scalars(select(Community).where(Community.project_id == project_id)).all())
    regions: dict[str, int] = {}
    total_population = 0
    for community in communities:
        regions[community.region] = regions.get(community.region, 0) + 1
        total_population += sum(int(value) for value in community.age_counts.values())
    return DashboardRead(
        community_count=len(communities),
        total_households=sum(item.households for item in communities),
        total_population=total_population,
        regions=regions,
    )


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/quality")
def project_quality(project_id: int, kind: str, _: ApiAuth, db: DbSession) -> dict:
    try:
        return inspect_project_quality(db,get_project_or_404(db,project_id),kind)
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/predictions/population", response_model=PredictionRunRead)
def predict_population(project_id: int, payload: PredictionRequest, _: ApiAuth, db: DbSession) -> PredictionRun:
    project = get_project_or_404(db, project_id)
    try:
        return run_population_prediction(db, project, payload.seed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/predictions/facility", response_model=PredictionRunRead)
def predict_facility(project_id: int, payload: FacilityPredictionRequest, _: ApiAuth, db: DbSession) -> PredictionRun:
    project = get_project_or_404(db, project_id)
    try:
        if payload.generate_report and payload.report_mode == "community" and payload.community_id is not None:
            source = db.get(PredictionRun, payload.population_run_id) if payload.population_run_id else db.scalar(
                select(PredictionRun).where(PredictionRun.project_id == project_id, PredictionRun.kind == "population", PredictionRun.status == "success").order_by(PredictionRun.id.desc())
            )
            if not source or source.project_id != project_id or not db.scalar(select(PredictionResult.id).where(PredictionResult.run_id == source.id, PredictionResult.community_id == payload.community_id).limit(1)):
                raise ValueError("所选社区不在本次人口预测结果中，请重新执行人口预测或选择对应批次")
        run = run_facility_prediction(db, project, payload.seed, payload.population_run_id)
        if payload.generate_report:
            generate_facility_report(db, project, run, payload.report_mode, payload.community_id)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/runs", response_model=list[PredictionRunRead])
def list_runs(project_id: int, _: ApiAuth, db: DbSession, kind: str | None = None) -> list[PredictionRun]:
    query = select(PredictionRun).where(PredictionRun.project_id == project_id)
    if kind:
        query = query.where(PredictionRun.kind == kind)
    return list(db.scalars(query.order_by(PredictionRun.id.desc())).all())


@app.get(f"{settings.api_prefix}/runs/{{run_id}}/calculation")
def get_run_calculation(run_id: int, community_id: int, year: int, _: ApiAuth, db: DbSession):
    run = db.get(PredictionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="预测批次不存在")
    result = db.scalar(select(PredictionResult).where(PredictionResult.run_id == run_id, PredictionResult.community_id == community_id, PredictionResult.year == year))
    if not result:
        raise HTTPException(status_code=404, detail="此批次没有所选社区及年份的结果")
    return explain_result(run, result)


@app.get(f"{settings.api_prefix}/runs/{{run_id}}/results")
def get_run_results(run_id: int, _: ApiAuth, db: DbSession) -> list[dict[str, Any]]:
    run = db.get(PredictionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="预测批次不存在")
    rows = db.execute(
        select(PredictionResult, Community)
        .join(Community, PredictionResult.community_id == Community.id)
        .where(PredictionResult.run_id == run_id)
        .order_by(Community.code, PredictionResult.year)
    ).all()
    return [
        {
            "communityId": community.id,
            "communityCode": result.data.get("communitySnapshot", {}).get("code", community.code),
            "communityName": result.data.get("communitySnapshot", {}).get("name", community.name),
            "year": result.year,
            "data": result.data,
        }
        for result, community in rows
    ]


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/runs/clear")
def clear_runs(project_id: int, run_ids: list[int], _: ApiAuth, db: DbSession) -> dict:
    project = get_project_or_404(db, project_id)
    try:
        return {"deleted_count": clear_project_runs(db, project, run_ids)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/runs/{{run_id}}/download")
def download_run_output(run_id: int, _: ApiAuth, db: DbSession) -> FileResponse:
    run = db.get(PredictionRun, run_id)
    if not run or not run.output_file:
        raise HTTPException(status_code=404, detail="结果文件不存在")
    output_path = Path(run.output_file)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="结果文件已被移动或删除")
    return FileResponse(output_path, filename=output_path.name)


@app.get(f"{settings.api_prefix}/runs/{{run_id}}/report")
def download_run_report(run_id: int, _: ApiAuth, db: DbSession) -> FileResponse:
    run = db.get(PredictionRun, run_id)
    if not run or run.kind != "facility":
        raise HTTPException(status_code=404, detail="设施预测批次不存在")
    project = db.get(Project, run.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="工程不存在")
    reports = sorted((Path(project.path) / "output").glob(f"PreReport_run{run_id}_*.docx"), reverse=True)
    if not reports:
        raise HTTPException(status_code=404, detail="该批次未生成 Word 报告")
    report_path = reports[0]
    if f"_{REPORT_FORMAT_VERSION}_" not in report_path.name:
        try:
            report_path = generate_facility_report(db, project, run, "overall")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(report_path, filename=report_path.name)


@app.post(f"{settings.api_prefix}/runs/{{run_id}}/report")
def create_run_report(run_id: int, payload: ReportGenerationRequest, _: ApiAuth, db: DbSession) -> dict[str, Any]:
    run = db.get(PredictionRun, run_id)
    if not run or run.kind != "facility" or run.status != "success":
        raise HTTPException(status_code=404, detail="可用于生成报告的设施预测批次不存在")
    project = db.get(Project, run.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="工程不存在")
    if payload.report_mode == "community" and payload.community_id is None:
        raise HTTPException(status_code=422, detail="生成分社区报告时必须选择社区")
    try:
        report_path = generate_facility_report(db, project, run, payload.report_mode, payload.community_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": run.id, "filename": report_path.name, "report_available": True}


@app.get(f"{settings.api_prefix}/runs/{{run_id}}/backup")
def backup_run(run_id: int, _: ApiAuth, db: DbSession) -> StreamingResponse:
    run = db.get(PredictionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="预测批次不存在")
    filename, content = build_run_backup(db, run)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.delete(f"{settings.api_prefix}/runs/{{run_id}}", status_code=204)
def remove_run(run_id: int, _: ApiAuth, db: DbSession) -> None:
    run = db.get(PredictionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="预测批次不存在")
    try:
        delete_run(db, run)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/stats")
def stats(_: ApiAuth, db: DbSession) -> dict[str, int]:
    return {
        "projects": db.scalar(select(func.count()).select_from(Project)) or 0,
        "communities": db.scalar(select(func.count()).select_from(Community)) or 0,
        "runs": db.scalar(select(func.count()).select_from(PredictionRun)) or 0,
    }


@app.get("/workspace", include_in_schema=False)
def single_workspace_entry(request: Request) -> RedirectResponse:
    """为上级系统提供稳定、简洁的单界面入口，并保留其传入的工程与鉴权参数。"""
    params = dict(request.query_params)
    params["workspace"] = "1"
    return RedirectResponse(url=f"/?{urlencode(params)}", status_code=307)


# 前端构建完成后，后端可直接托管静态文件，形成单进程独立模块。
bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
frontend_dist = bundle_root / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
