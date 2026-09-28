from __future__ import annotations

from sqlalchemy import select

from ..defaults import AGE_GROUPS, MORTALITY_GROUPS, REQUIRED_FACILITY_PATHS
from ..models import Community, ParameterSet, PredictionRun, Project


def _get(data, path):
    for part in path.split("."):
        data = data.get(part) if isinstance(data, dict) else None
    return data


def inspect_project_quality(db, project: Project, kind: str):
    if kind not in {"population", "facility"}: raise ValueError("未知预测类型")
    issues=[]
    def add(level, code, message, page, community_id=None):
        issues.append({"level":level,"code":code,"message":message,"page":page,"communityId":community_id})
    communities=list(db.scalars(select(Community).where(Community.project_id==project.id)).all())
    params={p.kind:p.data for p in db.scalars(select(ParameterSet).where(ParameterSet.project_id==project.id)).all()}
    population=params.get("population",{}); start=population.get("startYear"); duration=population.get("duration")
    try: years=[str(y) for y in range(int(start)+1,int(start)+int(duration)+1)]
    except (TypeError,ValueError): years=[]; add("error","INVALID_RANGE","人口预测基准年或时长无效","population")
    if not communities: add("error","NO_COMMUNITIES","尚未录入社区数据","dashboard")
    for c in communities:
        total=sum(int(v) for v in (c.age_counts or {}).values())
        label=f"{c.code}-{c.name}"
        if not total: add("error","NO_POPULATION",f"{label}没有有效人口数据","communities",c.id)
        if years and c.population_base_year is None: add("warning","BASE_YEAR_EMPTY",f"{label}未记录人口基准年，当前按{start}年使用；建议补录","communities",c.id)
        elif years and c.population_base_year != int(start): add("error","BASE_YEAR",f"{label}人口基准年为{c.population_base_year}，应为{start}","communities",c.id)
        missing=[g for g in AGE_GROUPS if g not in (c.migration_rates or {})]
        if missing: add("warning","MIGRATION_DEFAULT_ZERO",f"{label}有{len(missing)}组净迁入率未填写，计算时按0‰处理","communities",c.id)
        if total and c.households:
            inferred=total/c.households
            if abs(inferred-c.average_household_size)/c.average_household_size > .25:
                add("warning","HOUSEHOLD_MISMATCH",f"{label}人口/户数={inferred:.2f}，与预测户均人数{c.average_household_size:.2f}相差超过25%","communities",c.id)
        if any("模拟" in str(n) for n in (c.facilities or {}).get("_dataNotes",[])):
            add("warning","SIMULATED_DATA",f"{label}包含模拟数据，正式预测前请替换或核实","communities",c.id)
    if not population: add("error","NO_POPULATION_PARAMETERS","缺少人口参数","population")
    elif years:
        births=population.get("birthRates",{}); deaths=population.get("deathRates",{})
        for c in communities:
            series=births.get(c.region) or births.get("全国（中预测）") or births.get("全国") or {}
            missing=[y for y in years if series.get(y) in (None,"")]
            if missing: add("error","BIRTH_MISSING",f"{c.region}缺少出生率：{','.join(missing)}年","population")
        for year in years:
            missing=[g for g in MORTALITY_GROUPS if deaths.get(year,{}).get(g) in (None,"")]
            if missing: add("error","DEATH_MISSING",f"{year}年缺少{len(missing)}组死亡率","population")
    if kind=="facility":
        facility=params.get("facility",{})
        missing=[path for path in REQUIRED_FACILITY_PATHS if _get(facility,path) in (None,"")]
        if missing: add("error","FACILITY_MISSING",f"还有{len(missing)}项设施标准未填写","facility")
        parking=facility.get("parking",{})
        if not parking.get("newEnergyVehiclesPerCapita") or not parking.get("vehiclesPerCapita"):
            add("error","VEHICLE_MISSING","停车充电缺少两类机动车人均保有量参考值","facility")
        population_run=db.scalar(select(PredictionRun.id).where(PredictionRun.project_id==project.id,PredictionRun.kind=="population",PredictionRun.status=="success").limit(1))
        if not population_run: add("error","NO_POPULATION_RUN","设施预测前必须先完成人口预测","population")
    errors=sum(i["level"]=="error" for i in issues); warnings=sum(i["level"]=="warning" for i in issues)
    return {"kind":kind,"ready":errors==0,"errorCount":errors,"warningCount":warnings,"checkedCommunities":len(communities),"forecastYears":[int(y) for y in years],"issues":issues}


def assert_project_ready(db, project, kind):
    report=inspect_project_quality(db,project,kind)
    if not report["ready"]:
        raise ValueError("预测前检查未通过："+"；".join(i["message"] for i in report["issues"] if i["level"]=="error"))
    return report
