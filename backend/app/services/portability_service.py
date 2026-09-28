from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from sqlalchemy import select

from ..config import get_settings
from ..models import Community, ParameterSet, PredictionResult, PredictionRun, Project
from .project_service import create_project


FORMAT = "community-prediction-project"
VERSION = 1


def _iso(value):
    return value.isoformat() if value else None


def _relative(root: Path, raw: str | None):
    if not raw:
        return None
    try:
        return Path(raw).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def build_project_archive(db, project: Project) -> tuple[str, bytes]:
    root = Path(project.path)
    communities = list(db.scalars(select(Community).where(Community.project_id == project.id)).all())
    runs = list(db.scalars(select(PredictionRun).where(PredictionRun.project_id == project.id)).all())
    results = list(db.scalars(select(PredictionResult).where(PredictionResult.run_id.in_([r.id for r in runs] or [-1]))).all())
    manifest = {
        "format": FORMAT, "version": VERSION, "exportedAt": datetime.now().astimezone().isoformat(),
        "project": {"id": project.id, "name": project.name, "created_at": _iso(project.created_at), "updated_at": _iso(project.updated_at)},
        "parameters": [{"kind": p.kind, "data": p.data, "source_file": _relative(root, p.source_file)} for p in project.parameter_sets],
        "communities": [{"id": c.id, "code": c.code, "name": c.name, "region": c.region, "households": c.households,
            "average_household_size": c.average_household_size, "migration_rates": c.migration_rates, "migration_rate_unit": c.migration_rate_unit,
            "age_counts": c.age_counts, "population_records": c.population_records, "population_base_year": c.population_base_year,
            "facilities": c.facilities, "idle_spaces": c.idle_spaces, "source_file": _relative(root, c.source_file)} for c in communities],
        "runs": [{"id": r.id, "kind": r.kind, "status": r.status, "seed": r.seed, "parameters_snapshot": r.parameters_snapshot,
            "output_file": _relative(root, r.output_file), "error_message": r.error_message, "started_at": _iso(r.started_at), "completed_at": _iso(r.completed_at)} for r in runs],
        "results": [{"run_id": r.run_id, "community_id": r.community_id, "year": r.year, "data": r.data} for r in results],
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    archive.write(path, "files/" + path.relative_to(root).as_posix())
    return f"{project.name}.ccproject.zip", buffer.getvalue()


def _unique_name(db, requested: str) -> str:
    base = requested.strip()[:100] or "导入工程"
    if not db.scalar(select(Project.id).where(Project.name == base)):
        return base
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{base}（导入_{stamp}）"[:120]
    index = 2
    while db.scalar(select(Project.id).where(Project.name == candidate)):
        candidate = f"{base}（导入_{stamp}_{index}）"[:120]; index += 1
    return candidate


def _parse_datetime(value):
    if value in (None, "") or isinstance(value, datetime):
        return value or None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _safe_extract(archive: ZipFile, target: Path):
    for info in archive.infolist():
        if not info.filename.startswith("files/") or info.is_dir():
            continue
        relative = Path(info.filename[6:])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("工程包包含不安全路径")
        destination = (target / relative).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise ValueError("工程包包含越界路径")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(info))


def import_project_archive(db, content: bytes, requested_name: str | None = None) -> Project:
    try:
        archive = ZipFile(BytesIO(content))
        manifest = json.loads(archive.read("manifest.json"))
    except (BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("不是有效的工程备份包") from exc
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise ValueError("工程备份包格式或版本不受支持")
    name = _unique_name(db, requested_name or manifest.get("project", {}).get("name", "导入工程"))
    project = create_project(db, name)
    root = Path(project.path)
    try:
        _safe_extract(archive, root)
        for p in list(project.parameter_sets): db.delete(p)
        db.flush()
        for item in manifest.get("parameters", []):
            source = root / item["source_file"] if item.get("source_file") else None
            db.add(ParameterSet(project_id=project.id, kind=item["kind"], data=item.get("data", {}), source_file=str(source) if source else None))
        community_map = {}
        for item in manifest.get("communities", []):
            old_id = item.pop("id"); source = item.pop("source_file", None)
            community = Community(project_id=project.id, **item, source_file=str(root/source) if source else None)
            db.add(community); db.flush(); community_map[old_id] = community.id
        run_map = {}
        pending = []
        for item in manifest.get("runs", []):
            old_id = item.pop("id"); output = item.pop("output_file", None)
            item["started_at"] = _parse_datetime(item.get("started_at"))
            item["completed_at"] = _parse_datetime(item.get("completed_at"))
            snapshot = deepcopy(item.get("parameters_snapshot", {}))
            snapshot["_communities"] = [{**c, "id": community_map.get(c.get("id"), c.get("id"))} for c in snapshot.get("_communities", [])]
            run = PredictionRun(project_id=project.id, **{**item, "parameters_snapshot": snapshot}, output_file=str(root/output) if output else None)
            db.add(run); db.flush(); run_map[old_id] = run.id; pending.append(run)
        for run in pending:
            snapshot = deepcopy(run.parameters_snapshot)
            if snapshot.get("_populationRunId") in run_map: snapshot["_populationRunId"] = run_map[snapshot["_populationRunId"]]
            run.parameters_snapshot = snapshot
        for item in manifest.get("results", []):
            data = deepcopy(item.get("data", {}))
            audit = data.get("calculationAudit", {})
            if audit.get("populationRunId") in run_map: audit["populationRunId"] = run_map[audit["populationRunId"]]
            db.add(PredictionResult(run_id=run_map[item["run_id"]], community_id=community_map[item["community_id"]], year=item["year"], data=data))
        # Report discovery and output links include run ids. Rename through neutral
        # temporary names so overlapping old/new ids cannot rename the same file twice.
        staged_files = []
        for old_id, new_id in run_map.items():
            for path in list((root/"output").glob(f"*run{old_id}_*")):
                final_name = re.sub(f"run{old_id}(?=_)", f"run{new_id}", path.name)
                temporary = path.with_name(f".import-{new_id}-{len(staged_files)}-{path.name}")
                path.replace(temporary)
                staged_files.append((temporary, path.with_name(final_name)))
            run = db.get(PredictionRun, new_id)
            if run and run.output_file:
                output = Path(run.output_file)
                candidate = output.with_name(re.sub(f"run{old_id}(?=_)", f"run{new_id}", output.name))
                run.output_file = str(candidate)
        for temporary, target in staged_files:
            temporary.replace(target)
        metadata = {"name": name, "importedAt": datetime.now().astimezone().isoformat(), "schemaVersion": VERSION}
        (root/"project.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        db.commit(); db.refresh(project); return project
    except Exception:
        db.rollback()
        from .project_service import archive_project
        persisted = db.get(Project, project.id)
        if persisted: archive_project(db, persisted)
        raise


def build_system_backup(db) -> tuple[str, bytes]:
    buffer = BytesIO(); projects = list(db.scalars(select(Project).order_by(Project.id)).all())
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("system-manifest.json", json.dumps({"format":"community-prediction-system","version":1,"projectCount":len(projects),"exportedAt":datetime.now().astimezone().isoformat()}, ensure_ascii=False))
        for index, project in enumerate(projects):
            _, content = build_project_archive(db, project)
            archive.writestr(f"projects/{index:03d}.ccproject.zip", content)
    return f"社区预测系统全部数据_{datetime.now():%Y%m%d_%H%M%S}.zip", buffer.getvalue()


def restore_system_backup(db, content: bytes) -> list[Project]:
    try:
        archive = ZipFile(BytesIO(content)); manifest=json.loads(archive.read("system-manifest.json"))
    except (BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("不是有效的系统备份包") from exc
    if manifest.get("format") != "community-prediction-system" or manifest.get("version") != 1:
        raise ValueError("系统备份包格式或版本不受支持")
    members=[n for n in archive.namelist() if re.fullmatch(r"projects/\d+\.ccproject\.zip",n)]
    if len(members) != manifest.get("projectCount"): raise ValueError("系统备份包工程数量校验失败")
    return [import_project_archive(db,archive.read(name)) for name in sorted(members)]
