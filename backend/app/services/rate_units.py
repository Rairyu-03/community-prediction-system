"""Convert legacy percent community inputs once, without rewriting historical runs."""
from copy import deepcopy
from decimal import Decimal
from sqlalchemy import select


def percent_to_permille(value):
    return float(Decimal(str(value)) * 10)


def migrate_community_rate_units(db):
    from ..models import Community
    for community in db.scalars(select(Community).where(Community.migration_rate_unit == "%")):
        old = deepcopy(community.migration_rates)
        facilities = deepcopy(community.facilities or {})
        facilities.setdefault("_migrationUnitBackup", {"unit": "%", "values": old})
        notes = [n for n in facilities.get("_dataNotes", []) if not str(n).startswith("分年龄段年均净迁入率为模拟情景")]
        notes.append("净迁入率已由百分率等价换算为千分率（原值×10），人口变化幅度不变；历史预测批次保留原始单位和结果。")
        facilities["_dataNotes"] = notes
        community.migration_rates = {k: percent_to_permille(v) for k, v in old.items()}
        community.migration_rate_unit = "‰"
        community.facilities = facilities
    db.commit()
