"""Restore losslessly recoverable population details from retained source files."""
from pathlib import Path
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Community
from .excel_service import parse_community


def restore_population_details(db: Session) -> None:
    for community in db.scalars(select(Community)).all():
        if community.population_records:
            continue
        source = Path(community.source_file) if community.source_file else None
        if source is None or not source.is_file():
            continue
        try:
            original = parse_community(source)
            stored = {str(k): int(v) for k, v in community.age_counts.items() if v}
            recovered = {str(k): int(v) for k, v in original["age_counts"].items() if v}
            if original["code"] == community.code and recovered == stored:
                community.population_records = original["population_records"]
                community.population_base_year = original["population_base_year"]
        except Exception:
            logging.getLogger(__name__).warning("社区 %s 的原始人口明细暂不可恢复，保留现有数据", community.id)
    db.commit()
