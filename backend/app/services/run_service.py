from __future__ import annotations

from io import BytesIO
from datetime import datetime
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import PredictionResult, PredictionRun, Project


def _artifact_paths(run: PredictionRun, project: Project) -> list[Path]:
    project_root = Path(project.path).resolve()
    candidates: list[Path] = []
    if run.output_file:
        candidates.append(Path(run.output_file))
    candidates.extend((project_root / "output").glob(f"PreReport_run{run.id}_*.docx"))
    artifacts: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and resolved.is_relative_to(project_root) and resolved not in artifacts:
            artifacts.append(resolved)
    return artifacts


def build_run_backup(db: Session, run: PredictionRun) -> tuple[str, bytes]:
    project = db.get(Project, run.project_id)
    if not project:
        raise ValueError("工程不存在")
    rows = list(
        db.scalars(
            select(PredictionResult)
            .where(PredictionResult.run_id == run.id)
            .order_by(PredictionResult.community_id, PredictionResult.year)
        ).all()
    )
    manifest = {
        "backupVersion": 1,
        "generatedAt": datetime.now().astimezone().isoformat(),
        "project": {"id": project.id, "name": project.name},
        "run": {
            "id": run.id,
            "kind": run.kind,
            "status": run.status,
            "seed": run.seed,
            "parametersSnapshot": run.parameters_snapshot,
            "errorMessage": run.error_message,
            "startedAt": run.started_at.isoformat(),
            "completedAt": run.completed_at.isoformat() if run.completed_at else None,
        },
        "resultCount": len(rows),
        "artifacts": [path.name for path in _artifact_paths(run, project)],
    }
    result_data = [
        {
            "communityId": row.community_id,
            "communityCode": row.community.code,
            "communityName": row.community.name,
            "year": row.year,
            "data": row.data,
        }
        for row in rows
    ]
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("results.json", json.dumps(result_data, ensure_ascii=False, indent=2))
        for artifact in _artifact_paths(run, project):
            archive.write(artifact, f"files/{artifact.name}")
    filename = f"预测批次_{run.id}_{run.kind}_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    return filename, buffer.getvalue()


def delete_run(db: Session, run: PredictionRun) -> Path:
    if run.status == "running":
        raise ValueError("正在运行的预测批次不能删除")
    if run.kind == "population":
        facility_runs = list(
            db.scalars(
                select(PredictionRun).where(
                    PredictionRun.project_id == run.project_id,
                    PredictionRun.kind == "facility",
                )
            ).all()
        )
        dependents = [item.id for item in facility_runs if item.parameters_snapshot.get("_populationRunId") == run.id]
        if dependents:
            raise ValueError(f"该人口批次仍被设施批次 #{', #'.join(map(str, dependents))} 使用，请先删除这些设施批次")

    project = db.get(Project, run.project_id)
    if not project:
        raise ValueError("工程不存在")
    artifacts = _artifact_paths(run, project)
    filename, backup = build_run_backup(db, run)
    trash_root = get_settings().projects_root.parent / "trash" / "runs"
    trash_root.mkdir(parents=True, exist_ok=True)
    backup_path = trash_root / filename
    backup_path.write_bytes(backup)

    shared_outputs = {
        Path(item).resolve()
        for item in db.scalars(
            select(PredictionRun.output_file).where(
                PredictionRun.id != run.id,
                PredictionRun.output_file.is_not(None),
            )
        ).all()
        if item
    }
    db.delete(run)
    db.commit()
    for artifact in artifacts:
        if artifact.resolve() not in shared_outputs:
            artifact.unlink(missing_ok=True)
    return backup_path


def clear_project_runs(db: Session, project: Project, expected_ids: list[int]) -> int:
    runs = list(db.scalars(select(PredictionRun).where(PredictionRun.project_id == project.id)).all())
    if set(expected_ids) != {run.id for run in runs}:
        raise ValueError("历史记录已变化，请刷新后重新确认清除")
    if any(run.status == "running" for run in runs):
        raise ValueError("有预测正在运行，请完成后再清除")
    trash = get_settings().projects_root.parent / "trash" / "runs"
    trash.mkdir(parents=True, exist_ok=True)
    artifacts = {path for run in runs for path in _artifact_paths(run, project)}
    # Finish every recoverable backup before deleting any database record.
    for run in runs:
        name, content = build_run_backup(db, run)
        (trash / f"clear_{uuid4().hex}_{name}").write_bytes(content)
    for run in runs:
        db.delete(run)
    db.commit()
    for path in artifacts:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # Backup exists; locked output is an orphan, not lost data.
    return len(runs)
