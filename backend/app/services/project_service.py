from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..defaults import DEFAULT_FACILITY_PARAMETERS, DEFAULT_POPULATION_PARAMETERS
from ..models import ParameterSet, Project


LEGACY_BUILTIN_PROJECT_NAME = "默认预测项目"


def safe_directory_name(name: str) -> str:
    normalized = re.sub(r"\s+", "_", name.strip())
    normalized = re.sub(r"[^\w\u4e00-\u9fff.-]", "_", normalized)
    return normalized[:80] or "project"


def initialize_project_folders(project_path: Path, project_name: str) -> None:
    (project_path / "input").mkdir(parents=True, exist_ok=True)
    (project_path / "output").mkdir(parents=True, exist_ok=True)
    (project_path / "logs").mkdir(parents=True, exist_ok=True)
    metadata = {
        "name": project_name,
        "createdAt": datetime.now().astimezone().isoformat(),
        "schemaVersion": 1,
    }
    (project_path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_project(db: Session, name: str) -> Project:
    existing = db.scalar(select(Project).where(Project.name == name))
    if existing:
        raise ValueError(f"工程“{name}”已存在")

    settings = get_settings()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    project_path = settings.projects_root / f"{safe_directory_name(name)}_{timestamp}_{uuid4().hex[:8]}"
    initialize_project_folders(project_path, name)

    try:
        project = Project(name=name, path=str(project_path.resolve()))
        db.add(project)
        db.flush()
        db.add_all(
            [
                ParameterSet(
                    project_id=project.id,
                    kind="population",
                    data=deepcopy(DEFAULT_POPULATION_PARAMETERS),
                ),
                ParameterSet(
                    project_id=project.id,
                    kind="facility",
                    data=deepcopy(DEFAULT_FACILITY_PARAMETERS),
                ),
            ]
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        shutil.rmtree(project_path, ignore_errors=True)
        raise ValueError(f"工程“{name}”已存在") from exc
    except Exception:
        db.rollback()
        shutil.rmtree(project_path, ignore_errors=True)
        raise
    db.refresh(project)
    return project


def remove_legacy_builtin_project(db: Session) -> None:
    """Remove the former bundled example when an existing installation is upgraded."""
    project = db.scalar(select(Project).where(Project.name == LEGACY_BUILTIN_PROJECT_NAME))
    if project is None:
        return
    try:
        archive_project(db, project)
    except ValueError:
        db.delete(project)
        db.commit()


def rename_project(db: Session, project: Project, name: str) -> Project:
    existing = db.scalar(select(Project).where(Project.name == name, Project.id != project.id))
    if existing:
        raise ValueError(f"工程“{name}”已存在")
    project.name = name
    metadata_path = Path(project.path) / "project.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["name"] = name
        metadata["updatedAt"] = datetime.now().astimezone().isoformat()
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    db.commit()
    db.refresh(project)
    return project


def archive_project(db: Session, project: Project) -> Path | None:
    settings = get_settings()
    projects_root = settings.projects_root.resolve()
    project_path = Path(project.path).resolve()
    if not project_path.is_relative_to(projects_root):
        raise ValueError("工程目录不在允许的工程根目录中，禁止删除")

    archived_path: Path | None = None
    if project_path.exists():
        trash_root = projects_root.parent / "trash" / "projects"
        trash_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        archived_path = trash_root / f"{safe_directory_name(project.name)}_{project.id}_{timestamp}"
        shutil.move(str(project_path), str(archived_path))

    try:
        db.delete(project)
        db.commit()
    except Exception:
        db.rollback()
        if archived_path and archived_path.exists() and not project_path.exists():
            shutil.move(str(archived_path), str(project_path))
        raise
    return archived_path


def import_project(db: Session, source_path: Path, requested_name: str | None = None) -> Project:
    source_path = source_path.resolve()
    if not source_path.is_dir():
        raise ValueError("导入路径不是有效文件夹")
    if not (source_path / "input").is_dir():
        raise ValueError("工程目录缺少 input 文件夹")

    name = requested_name or source_path.name
    if db.scalar(select(Project).where(Project.name == name)):
        raise ValueError(f"工程“{name}”已存在")

    settings = get_settings()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    target = settings.projects_root / f"{safe_directory_name(name)}_{timestamp}"
    shutil.copytree(source_path, target)
    (target / "output").mkdir(exist_ok=True)
    (target / "logs").mkdir(exist_ok=True)

    project = Project(name=name, path=str(target.resolve()))
    db.add(project)
    db.flush()
    db.add_all(
        [
            ParameterSet(project_id=project.id, kind="population", data=deepcopy(DEFAULT_POPULATION_PARAMETERS)),
            ParameterSet(project_id=project.id, kind="facility", data=deepcopy(DEFAULT_FACILITY_PARAMETERS)),
        ]
    )
    db.commit()
    db.refresh(project)
    return project


def save_project_as(db: Session, project: Project, target_parent: Path, new_name: str) -> Project:
    target_parent = target_parent.resolve()
    target_parent.mkdir(parents=True, exist_ok=True)
    target = target_parent / safe_directory_name(new_name)
    if target.exists():
        raise ValueError("目标目录已存在")
    shutil.copytree(Path(project.path), target)
    copied = Project(name=new_name, path=str(target))
    db.add(copied)
    db.flush()
    for item in project.parameter_sets:
        db.add(ParameterSet(project_id=copied.id, kind=item.kind, data=deepcopy(item.data), source_file=item.source_file))
    db.commit()
    db.refresh(copied)
    return copied
