from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    path: Mapped[str] = mapped_column(String(500), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    parameter_sets: Mapped[list[ParameterSet]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    communities: Mapped[list[Community]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    runs: Mapped[list[PredictionRun]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def is_demo(self) -> bool:
        return self.name == "默认预测项目"


class ParameterSet(Base):
    __tablename__ = "parameter_sets"
    __table_args__ = (UniqueConstraint("project_id", "kind", name="uq_project_parameter_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    project: Mapped[Project] = relationship(back_populates="parameter_sets")


class Community(Base):
    __tablename__ = "communities"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_project_community_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    region: Mapped[str] = mapped_column(String(120), default="全国")
    households: Mapped[int] = mapped_column(Integer, default=0)
    average_household_size: Mapped[float] = mapped_column(Float, default=2.5)
    migration_rates: Mapped[dict] = mapped_column(JSON, default=dict)
    migration_rate_unit: Mapped[str] = mapped_column(String(12), default="‰")
    age_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    population_records: Mapped[list] = mapped_column(JSON, default=list)
    population_base_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    facilities: Mapped[dict] = mapped_column(JSON, default=dict)
    idle_spaces: Mapped[list] = mapped_column(JSON, default=list)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    project: Mapped[Project] = relationship(back_populates="communities")
    results: Mapped[list[PredictionResult]] = relationship(
        back_populates="community", cascade="all, delete-orphan"
    )


class PredictionRun(Base):
    __tablename__ = "prediction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    parameters_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    output_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="runs")
    results: Mapped[list[PredictionResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    @property
    def project_name(self) -> str:
        return self.project.name if self.project else ""

    @property
    def community_names(self) -> list[str]:
        snapshot = self.parameters_snapshot.get("_communities", [])
        if snapshot:
            names = {item["id"]: f"{item['code']}-{item['name']}" for item in snapshot}
        else:
            names = {row.community_id: f"{row.community.code}-{row.community.name}" for row in self.results}
        return [names.get(identifier, f"社区 {identifier}") for identifier in self.community_ids]

    @property
    def community_ids(self) -> list[int]:
        return sorted({row.community_id for row in self.results})

    @property
    def forecast_years(self) -> list[int]:
        return sorted({row.year for row in self.results})

    @property
    def report_available(self) -> bool:
        if self.kind != "facility" or not self.project:
            return False
        return any((Path(self.project.path) / "output").glob(f"PreReport_run{self.id}_*.docx"))


class PredictionResult(Base):
    __tablename__ = "prediction_results"
    __table_args__ = (
        UniqueConstraint("run_id", "community_id", "year", name="uq_run_community_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("prediction_runs.id", ondelete="CASCADE"), index=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[PredictionRun] = relationship(back_populates="results")
    community: Mapped[Community] = relationship(back_populates="results")
