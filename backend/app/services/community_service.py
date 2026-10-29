"""Restore recoverable population details from retained source files."""
from pathlib import Path
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Community
from .age_distribution import MAX_AGE
from .excel_service import parse_community


def _cap_stored_population(community: Community) -> None:
    """Upgrade stored population data to the current terminal age."""
    base_year = community.population_base_year
    if community.population_records:
        records = []
        counts: dict[str, int] = {}
        for raw in community.population_records:
            row = dict(raw)
            if base_year is not None and row.get("出生年份") not in (None, ""):
                age = base_year - int(row["出生年份"])
            else:
                age = int(row.get("年龄") or 0)
            age = max(0, min(MAX_AGE, age))
            row["年龄"] = age
            if base_year is not None:
                row["出生年份"] = base_year - age
            counts[str(age)] = counts.get(str(age), 0) + 1
            records.append(row)
        community.population_records = records
        community.age_counts = counts
        return
    numeric_counts: dict[str, int] = {}
    grouped_counts: dict[str, int] = {}
    for key, value in (community.age_counts or {}).items():
        if str(key).isdigit():
            age = min(MAX_AGE, max(0, int(key)))
            numeric_counts[str(age)] = numeric_counts.get(str(age), 0) + int(value)
        else:
            grouped_counts[str(key)] = int(value)
    community.age_counts = numeric_counts if numeric_counts else grouped_counts


def restore_population_details(db: Session) -> None:
    for community in db.scalars(select(Community)).all():
        _cap_stored_population(community)
        source = Path(community.source_file) if community.source_file else None
        if source is None or not source.is_file():
            continue
        try:
            original = parse_community(source)
            stored = {str(k): int(v) for k, v in community.age_counts.items() if v}
            recovered = {str(k): int(v) for k, v in original["age_counts"].items() if v}
            notes = (community.facilities or {}).get("_dataNotes", [])
            simulated = any("非实名模拟人口" in str(note) for note in notes)
            if original["code"] == community.code and recovered == stored:
                community.population_records = original["population_records"]
                community.population_base_year = original["population_base_year"]
            elif (
                original["code"] == community.code
                and (not community.population_records or simulated)
                and recovered
                and all(key.isdigit() for key in recovered)
                and sum(recovered.values()) == sum(stored.values())
            ):
                # Older imports stored the survey in fixed forecast bands and
                # lost boundaries such as 18—35 / 36—59. Re-reading the retained
                # survey upgrades it to the new single-age uniform simulation.
                community.age_counts = recovered
                community.population_records = original["population_records"]
                community.population_base_year = original["population_base_year"]
                community.facilities = original["facilities"]
        except Exception:
            logging.getLogger(__name__).warning("社区 %s 的原始人口明细暂不可恢复，保留现有数据", community.id)
        _cap_stored_population(community)
    db.commit()
