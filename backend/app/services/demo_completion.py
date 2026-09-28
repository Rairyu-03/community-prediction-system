"""Versioned, additive completion of the read-only example, never user projects."""
from copy import deepcopy
from pathlib import Path
import json

from sqlalchemy import select

from ..models import Community, ParameterSet
from ..defaults import DEFAULT_MIGRATION_RATES
from ..demo_data import DEMO_COMMUNITY
from .prediction_service import normalize_age_counts, run_population_prediction, run_facility_prediction
from .report_service import generate_facility_report


def complete_demo_data(db, project, *, generate_outputs=True):
    if not project.is_demo:
        return
    community = db.scalar(select(Community).where(Community.project_id == project.id, Community.code == "120101-A"))
    if not community:
        return
    if community.facilities.get("_completionVersion") == 1:
        complete_demo_migration(db, project, community, generate_outputs=generate_outputs)
        return
    backup = Path(project.path) / "backup" / "before_demo_completion_v1.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_text(json.dumps({k: getattr(community, k) for k in ("code", "name", "region", "households", "average_household_size", "migration_rates", "population_base_year", "age_counts", "population_records", "facilities", "idle_spaces")}, ensure_ascii=False, indent=2), encoding="utf-8")
    parameters = db.scalar(select(ParameterSet).where(ParameterSet.project_id == project.id, ParameterSet.kind == "population"))
    year = community.population_base_year or int(parameters.data["startYear"])
    community.population_base_year = year
    notes = ["原始资料以社区表内编号120101-A、名称庆有西里社区为准；上传文件名不作为社区名称。",
             "原表总户数及净迁入率未填：4150户按10375人/2.5人推算，净迁入率使用演示假设；不是实测统计。",
             "原表充电桩总数79个但仅1条明细；内置案例其余年份、缺失坐标为模拟补全。",
             "公共活动场地800㎡、多功能运动场地300㎡为缺失现状的模拟补值。原有非空现状值不覆盖。",
             "闲置空间坐标保留原资料，未做实地或行政区范围核验；选址仅作为面积初筛。"]
    if not community.population_records:
        records = []
        for age, count in enumerate(normalize_age_counts(community.age_counts)):
            for _ in range(count):
                records.append({"序号": len(records)+1, "性别": "男" if len(records)%2 == 0 else "女", "出生年份": year-age, "年龄": age, "数据来源": "根据原年龄汇总模拟性别，不是真实居民档案"})
        community.population_records = records
        notes.append("部署包未附原居民明细时，仅按已保存单岁年龄汇总生成演示记录，性别交替模拟；年龄分布和总人口保持不变。")
    else:
        rows = deepcopy(community.population_records)
        for index, row in enumerate(rows):
            if row.get("性别") not in ("男", "女"):
                row.setdefault("原始性别", row.get("性别", "未知"))
                row["性别"] = "男" if index%2 == 0 else "女"
                row["数据来源"] = "缺失或异常性别模拟补全，不影响当前年龄模型"
        community.population_records = rows
        notes.append("已保留原人口记录；缺失或异常性别交替模拟补全，原始值另存，不影响年龄模型。")
    community.migration_rates = {**DEFAULT_MIGRATION_RATES, **community.migration_rates}
    facilities = deepcopy(community.facilities)
    for category, fields in DEMO_COMMUNITY["facilities"].items():
        if isinstance(fields, dict):
            target = facilities.setdefault(category, {})
            for key, value in fields.items():
                if target.get(key) in (None, ""):
                    target[key] = value
    activity = facilities.setdefault("公共活动场地", {})
    for key, value in [("公共活动场地面积（平方米）", 800), ("多功能运动场地面积（平方米）", 300)]:
        if activity.get(key) in (None, ""):
            activity[key] = value
    chargers = facilities.setdefault("机动车充电桩列表", [])
    if chargers and (chargers[0].get("充电桩编号") or chargers[0].get("机动车充电桩编号")) == "120101-A-7-1" and chargers[0].get("建设年份") == 2019:
        # Replace only the former generated first row with the one supplied row.
        chargers[0] = {"机动车充电桩编号": "120101-A-3.2-1", "建设年份": 2025, "经度": 117.18251919, "纬度": 39.12901601, "数据来源": "上传社区工作簿原始充电桩记录（去除编号不可见字符）"}
    count = int(facilities.get("停车充电设施", {}).get("机动车充电桩数量（个）", 79))
    while len(chargers) < count:
        chargers.append({"机动车充电桩编号": f"120101-A-SIM-{len(chargers)+1}", "建设年份": 2019+len(chargers)%7, "数据来源": "模拟充电桩明细"})
    for index, row in enumerate(chargers):
        if "机动车充电桩编号" not in row:
            row["机动车充电桩编号"] = row.pop("充电桩编号", f"120101-A-SIM-{index+1}")
        for key, value in [("建设年份", 2019+index%7), ("经度", round(117.18251919+(index%10)*.00005,8)), ("纬度", round(39.12901601+(index//10)*.00005,8))]:
            if row.get(key) in (None, ""):
                row[key] = value
                row["数据来源"] = "缺失字段模拟补全；年份及坐标仅作演示"
    facilities["_dataNotes"] = notes
    facilities["_completionVersion"] = 1
    community.facilities = facilities
    if not community.idle_spaces:
        community.idle_spaces = deepcopy(DEMO_COMMUNITY["idle_spaces"])
    db.commit()
    complete_demo_migration(db, project, community, generate_outputs=generate_outputs)


DEMO_MIGRATION_RATES = dict(zip(DEFAULT_MIGRATION_RATES, [8, 6, 3, -2, 12, -3, -5, -6]))


def complete_demo_migration(db, project, community, *, generate_outputs=True):
    """Upgrade only the bundled example; preserve old runs and original assumptions."""
    if not project.is_demo or community.facilities.get("_migrationScenarioVersion") == 2:
        return
    backup = Path(project.path) / "backup" / "before_demo_migration_v2.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_text(json.dumps({"migration_rates": community.migration_rates, "facilities": community.facilities}, ensure_ascii=False, indent=2), encoding="utf-8")
    community.migration_rates = deepcopy(DEMO_MIGRATION_RATES)
    facilities = deepcopy(community.facilities)
    notes = [note for note in facilities.get("_dataNotes", []) if not str(note).startswith("分年龄段年均净迁入率为模拟情景")]
    notes.append("分年龄段年均净迁入率为模拟情景，不是当地统计：" + "、".join(f"{key} {value:+g}‰" for key, value in DEMO_MIGRATION_RATES.items()) + "。正数表示净迁入，负数表示净迁出；原零迁移历史批次保留。")
    facilities["_dataNotes"] = notes
    community.facilities = facilities
    db.commit()
    if generate_outputs:
        population_run = run_population_prediction(db, project, seed=20260825)
        facility_run = run_facility_prediction(db, project, seed=20260825, population_run_id=population_run.id)
        generate_facility_report(db, project, facility_run, mode="community", community_id=community.id)
        if population_run.status != "success" or facility_run.status != "success":
            raise RuntimeError("内置案例迁移情景重新预测失败，请检查后台日志")
    facilities = deepcopy(community.facilities)
    facilities["_migrationScenarioVersion"] = 2
    community.facilities = facilities
    db.commit()
