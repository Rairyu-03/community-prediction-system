from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..defaults import AGE_GROUPS, MORTALITY_GROUPS
from ..models import Community, ParameterSet, PredictionResult, PredictionRun, Project
from .excel_service import export_facility_results, export_population_results
from .validation_service import finite_number, validate_parameters


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5)) if value >= 0 else int(math.ceil(value - 0.5))


def group_for_age(age: int, groups: dict[str, tuple[int, int]]) -> str:
    for name, (minimum, maximum) in groups.items():
        if minimum <= age <= maximum:
            return name
    return next(reversed(groups))


def normalize_age_counts(raw: dict[str, int]) -> list[int]:
    counts = [0] * 121
    if all(str(key).isdigit() for key in raw):
        for key, value in raw.items():
            counts[max(0, min(120, int(key)))] += max(0, int(value))
        return counts

    for group_name, value in raw.items():
        if group_name not in AGE_GROUPS:
            continue
        minimum, maximum = AGE_GROUPS[group_name]
        maximum = min(120, maximum)
        total = max(0, int(value))
        width = maximum - minimum + 1
        base, remainder = divmod(total, width)
        for age in range(minimum, maximum + 1):
            counts[age] += base + (1 if age - minimum < remainder else 0)
    return counts


def distribute_change(counts: list[int], minimum: int, maximum: int, change: int, rng: random.Random) -> None:
    ages = list(range(minimum, min(120, maximum) + 1))
    if not ages or change == 0:
        return
    if change > 0:
        for _ in range(change):
            counts[rng.choice(ages)] += 1
        return
    for _ in range(min(-change, sum(counts[age] for age in ages))):
        choice = rng.randrange(sum(counts[age] for age in ages))
        for age in ages:
            if choice < counts[age]:
                counts[age] -= 1
                break
            choice -= counts[age]


def summarize_population(year: int, counts: list[int], average_household_size: float) -> dict[str, Any]:
    age_groups = {
        name: sum(counts[minimum : min(120, maximum) + 1])
        for name, (minimum, maximum) in AGE_GROUPS.items()
    }
    total = sum(counts)
    return {
        "year": year,
        "ageGroups": age_groups,
        "totalPopulation": total,
        "households": round_half_up(total / average_household_size),
        "ageCounts": {str(age): value for age, value in enumerate(counts)},
    }


def advance_population(counts: list[int], births: int, death_rates: dict[str, float], rng: random.Random) -> list[int]:
    """Deaths use year-t cohorts; retain the open-ended 120+ bucket when ageing."""
    survivors = counts.copy()
    for group, rate in death_rates.items():
        minimum, maximum = MORTALITY_GROUPS[group]
        population = sum(counts[minimum:min(maximum, 120) + 1])
        distribute_change(survivors, minimum, maximum, -round_half_up(population * rate / 1000), rng)
    aged = [births] + survivors[:120]
    aged[120] += survivors[120]
    return aged


def _birth_rate(parameters: dict, region: str, year: int) -> float:
    regions = parameters.get("birthRates", {})
    series = regions.get(region) or regions.get("全国（中预测）") or regions.get("全国") or {}
    value = series.get(str(year))
    if value is None:
        raise ValueError(f"{region} 缺少 {year} 年出生率")
    return float(value)


def _death_rates(parameters: dict, year: int) -> dict[str, float]:
    values = parameters.get("deathRates", {}).get(str(year))
    if not values:
        raise ValueError(f"缺少 {year} 年死亡率")
    missing = [group for group in MORTALITY_GROUPS if group not in values]
    if missing:
        raise ValueError(f"{year} 年死亡率缺少年龄段：{', '.join(missing)}")
    return {key: float(value) for key, value in values.items()}


def run_population_prediction(db: Session, project: Project, seed: int) -> PredictionRun:
    parameters = db.scalar(
        select(ParameterSet).where(ParameterSet.project_id == project.id, ParameterSet.kind == "population")
    )
    communities = list(db.scalars(select(Community).where(Community.project_id == project.id)).all())
    if not parameters:
        raise ValueError("缺少人口预测参数")
    if not communities:
        raise ValueError("工程中没有社区")

    run = PredictionRun(
        project_id=project.id,
        kind="population",
        status="running",
        seed=seed,
        parameters_snapshot={**parameters.data, "_algorithmVersion": "2026.09-permille-v2", "migrationRateUnit": "‰", "_communities": [{"id": c.id, "code": c.code, "name": c.name, "migration_rates": c.migration_rates, "migration_rate_unit": "‰"} for c in communities]},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    result_map: dict[str, list[dict[str, Any]]] = {}
    try:
        validate_parameters("population", parameters.data)
        start_year = int(parameters.data["startYear"])
        duration = int(parameters.data["duration"])
        for community in communities:
            if community.population_base_year is not None and community.population_base_year != start_year:
                raise ValueError(f"{community.name}人口数据基准年为{community.population_base_year}，与预测基准年{start_year}不一致，请校准参数或人口数据")
            digest = hashlib.sha256(f"{seed}:{community.code}".encode()).digest()
            rng = random.Random(int.from_bytes(digest[:8], "big"))
            counts = normalize_age_counts(community.age_counts)
            if not sum(counts):
                raise ValueError(f"{community.code}-{community.name}缺少有效年龄人口数据")
            yearly: list[dict[str, Any]] = []
            for year in range(start_year + 1, start_year + duration + 1):
                previous_total = sum(counts)
                birth_rate = _birth_rate(parameters.data, community.region, year)
                births = round_half_up(previous_total * birth_rate / 1000)
                death_rates = _death_rates(parameters.data, year)
                death_details = [{"年龄段": group, "上一年人数": sum(counts[lo:min(hi,120)+1]), "死亡率（‰）": death_rates[group], "死亡人数": round_half_up(sum(counts[lo:min(hi,120)+1])*death_rates[group]/1000)} for group, (lo, hi) in MORTALITY_GROUPS.items()]
                counts = advance_population(counts, births, death_rates, rng)
                migration_details = []

                for group, (minimum, maximum) in AGE_GROUPS.items():
                    rate = float(community.migration_rates.get(group, 0))
                    group_population = sum(counts[minimum : min(maximum, 120) + 1])
                    finite_number(rate, f"{group}净迁入率（‰）", -1000, 1000)
                    migration = round_half_up(group_population * rate / 1000)
                    distribute_change(counts, minimum, maximum, migration, rng)
                    migration_details.append({"年龄段": group, "基础存活人数": group_population, "净迁入率（‰）": rate, "净迁移人数": migration})

                summary = summarize_population(year, counts, community.average_household_size)
                summary["communitySnapshot"] = {"code": community.code, "name": community.name}
                available_regions = parameters.data.get("birthRates", {})
                birth_source = community.region if available_regions.get(community.region) else "全国（中预测）" if available_regions.get("全国（中预测）") else "全国"
                summary["calculationAudit"] = {"previousPopulation": previous_total, "birthRate": birth_rate, "birthRegion": birth_source, "requestedRegion": community.region, "births": births, "deaths": death_details, "migration": migration_details, "averageHouseholdSize": community.average_household_size, "baseYear": start_year, "dataNotes": community.facilities.get("_dataNotes", [])}
                yearly.append(summary)
                db.add(PredictionResult(run_id=run.id, community_id=community.id, year=year, data=summary))
            result_map[f"{community.code}-{community.name}"] = yearly

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_path = Path(project.path) / "output" / f"PreResult_pop_run{run.id}_{timestamp}.xlsx"
        export_population_results(output_path, result_map)
        run.status = "success"
        run.output_file = str(output_path)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        failed_run = db.get(PredictionRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.error_message = str(exc)
            failed_run.completed_at = datetime.now(timezone.utc)
            db.commit()
        raise


def _require_number(data: dict, path: str) -> float:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"设施参数缺少：{path}")
        current = current[part]
    if current is None or current == "":
        raise ValueError(f"设施参数缺少：{path}")
    return finite_number(current, path, 0, 100 if "Rate" in path or "Rates." in path else None)


def _series_value(data: dict, path: str, year: int) -> float:
    current: Any = data
    for part in path.split("."):
        current = current.get(part) if isinstance(current, dict) else None
    if not isinstance(current, dict) or not current:
        raise ValueError(f"设施参数缺少：{path}")
    points = sorted((int(key), float(value)) for key, value in current.items() if value not in (None, ""))
    if not points:
        raise ValueError(f"设施参数缺少：{path}")
    exact = next((value for point_year, value in points if point_year == year), None)
    if exact is not None:
        return exact
    lower = [point for point in points if point[0] < year]
    upper = [point for point in points if point[0] > year]
    if lower and upper:
        left_year, left_value = lower[-1]
        right_year, right_value = upper[0]
        return left_value + (right_value - left_value) * (year - left_year) / (right_year - left_year)
    return (lower[-1] if lower else upper[0])[1]


def _parameter_reference(parameters: dict, paths: list[str]) -> dict[str, str]:
    references = parameters.get("references", {})
    standards: list[str] = []
    sources: list[str] = []
    for path in paths:
        try:
            value = _require_number(parameters, path)
            suffix = "%" if "Rate" in path or "Rates." in path else "㎡/人" if "AreaPerPerson" in path or "PerCapita" in path and "parking." not in path else "个/户" if "PerHousehold" in path else "年" if path.endswith("Lifetime") else ""
            standards.append(f"{value:g}{suffix}")
        except ValueError:
            continue
        source = references.get(path, {}).get("source")
        if source and str(source).strip() and str(source).strip() not in sources:
            sources.append(str(source).strip())
    return {
        "standard": "；".join(standards) or "按用户录入参数测算",
        "source": "；".join(sources) or "用户录入，来源未填写",
    }


def _site_analysis(
    community: Community,
    facility_name: str,
    year: int,
    *,
    required_building: float = 0,
    existing_building: float = 0,
    required_land: float = 0,
    existing_land: float = 0,
    review_focus: str,
) -> dict[str, Any]:
    building_gap = round(max(required_building - existing_building, 0), 2)
    land_gap = round(max(required_land - existing_land, 0), 2)
    inventory: list[dict[str, Any]] = []
    for raw_space in community.idle_spaces:
        building_area = float(raw_space.get("待分配建筑面积（平方米）", 0) or 0)
        land_area = float(raw_space.get("待分配用地面积（平方米）", 0) or 0)
        coverages = []
        if building_gap:
            coverages.append(building_area / building_gap)
        if land_gap:
            coverages.append(land_area / land_gap)
        coverage = min(coverages) if coverages else 1
        inventory.append({
            "space": raw_space,
            "buildingArea": round(building_area, 2),
            "landArea": round(land_area, 2),
            "coverageRate": round(min(coverage, 1) * 100, 2),
            "qualified": building_area >= building_gap and land_area >= land_gap,
        })

    basis = {
        "targetYear": year,
        "requiredBuildingArea": round(required_building, 2),
        "existingBuildingArea": round(existing_building, 2),
        "buildingGap": building_gap,
        "requiredLandArea": round(required_land, 2),
        "existingLandArea": round(existing_land, 2),
        "landGap": land_gap,
        "candidateCount": len(inventory),
        "qualifiedCount": sum(1 for item in inventory if item["qualified"]),
        "selectedSpace": None,
        "coverageRate": 0,
        "reviewFocus": review_focus,
    }
    requirement_text = "、".join(part for part in (
        f"新增建筑面积缺口{building_gap:.2f}㎡（需求{required_building:.2f}㎡－现状{existing_building:.2f}㎡）" if required_building else "",
        f"新增用地面积缺口{land_gap:.2f}㎡（需求{required_land:.2f}㎡－现状{existing_land:.2f}㎡）" if required_land else "",
    ) if part)
    if building_gap <= 0 and land_gap <= 0:
        basis["coverageRate"] = 100
        basis["conclusion"] = f"{year}年{facility_name}{requirement_text}，现有供给已覆盖预测需求，暂不建议新增选址；后续重点复核{review_focus}。"
        return basis
    if not inventory:
        basis["conclusion"] = f"{year}年{facility_name}{requirement_text}。当前未录入闲置空间，无法形成候选地匹配结果；请补充空间面积和坐标后再评估，并复核{review_focus}。"
        return basis

    qualified = [item for item in inventory if item["qualified"]]
    if qualified:
        selected = min(qualified, key=lambda item: (item["buildingArea"] - building_gap) + (item["landArea"] - land_gap))
        status = "满足面积门槛"
    else:
        selected = max(inventory, key=lambda item: item["coverageRate"])
        status = "仅能部分覆盖缺口"
    space = selected["space"]
    code = str(space.get("闲置空间编号") or "未编号空间")
    longitude = space.get("经度")
    latitude = space.get("纬度")
    coordinate = f"坐标({longitude}, {latitude})" if longitude not in (None, "") and latitude not in (None, "") else "坐标待补充"
    basis["selectedSpace"] = code
    basis["coverageRate"] = selected["coverageRate"]
    if selected["qualified"]:
        action = "可作为优先候选地进入现场复核"
    else:
        action = "不能单独承载全部缺口，建议与其他空间组合或跨社区统筹"
    basis["conclusion"] = (
        f"{year}年{facility_name}{requirement_text}。对{len(inventory)}处闲置空间逐一进行面积匹配，"
        f"其中{basis['qualifiedCount']}处达标；{code}（{coordinate}，建筑{selected['buildingArea']:.2f}㎡、用地{selected['landArea']:.2f}㎡）"
        f"{status}，覆盖率{selected['coverageRate']:.2f}%，{action}。落地前复核{review_focus}。"
    )
    return basis


def _facility_metrics(population: dict, parameters: dict, community: Community, year: int) -> tuple[dict[str, float], dict[str, dict[str, str]], dict[str, str], dict[str, dict[str, Any]]]:
    ages = population["ageGroups"]
    total = population["totalPopulation"]
    households = population["households"]
    elderly_total = ages["60-69岁"] + ages["70-79岁"] + ages["80岁以上"]
    meal_people = round_half_up(elderly_total * _require_number(parameters, "meal.demandRate") / 100)
    station_capacity = round_half_up(elderly_total * _require_number(parameters, "elderly.stationDemandRate") / 100)
    nursery_people = ages["0-3岁"] * _require_number(parameters, "childcare.nurseryDemandRate") / 100
    kindergarten_people = ages["4-6岁"] * _require_number(parameters, "childcare.kindergartenDemandRate") / 100
    weighted = lambda prefix: sum(ages[group] * _require_number(parameters, f"elderly.{prefix}.{group}") / 100 for group in ("60-69岁", "70-79岁", "80岁以上"))
    disabled_people = weighted("disabilityRates")
    rehabilitation_people = weighted("rehabilitationRates")
    entertainment_people = weighted("entertainmentRates")
    transport_people = weighted("transportRates")
    existing_meal = float(community.facilities.get("助餐设施", {}).get("社区食堂建筑面积（平方米）", 0) or 0)
    elderly_facilities = community.facilities.get("养老设施", {})
    existing_station_capacity = float(elderly_facilities.get("老年服务站容纳量（人）", 0) or 0)
    existing_station_area = float(elderly_facilities.get("老年服务站建筑面积（平方米）", 0) or 0)
    activity_facilities = community.facilities.get("公共活动场地", community.facilities.get("公共活动设施", {}))
    existing_public_area = float(activity_facilities.get("公共活动场地面积（平方米）", 0) or 0)
    existing_sports_area = float(activity_facilities.get("多功能运动场地面积（平方米）", 0) or 0)
    parking_facilities = community.facilities.get("停车充电设施", {})
    current_chargers = float(
        parking_facilities.get("机动车充电桩数量（个）", community.facilities.get("充电桩数量", 0)) or 0
    )
    charger_lifetime = _require_number(parameters, "parking.chargerLifetime")
    expired = sum(
        1 for charger in community.facilities.get("机动车充电桩列表", [])
        if charger.get("建设年份") not in (None, "") and float(charger["建设年份"]) + charger_lifetime <= year
    )
    active_chargers = max(0, current_chargers - expired)
    current_parking_spaces = float(
        parking_facilities.get("停车位数量（个）", community.facilities.get("停车位数量", 0)) or 0
    )
    dining_area = round(meal_people * _require_number(parameters, "meal.diningAreaPerPerson"), 2)
    station_area = round(station_capacity * _require_number(parameters, "elderly.stationAreaPerPerson"), 2)
    public_area = round(total * _require_number(parameters, "activity.publicAreaPerCapita"), 2)
    sports_area = round(total * _require_number(parameters, "activity.sportsAreaPerCapita"), 2)
    new_energy_rate = _series_value(parameters, "parking.newEnergyVehiclesPerCapita", year)
    vehicle_rate = _series_value(parameters, "parking.vehiclesPerCapita", year)
    metrics: dict[str, float] = {
        "助餐设施/未来助餐服务需求人数": meal_people,
        "助餐设施/社区食堂建筑面积（堂食模式）": dining_area,
        "助餐设施/社区食堂建筑面积缺口（堂食模式）": round(dining_area - existing_meal, 2),
        "助餐设施/社区食堂建筑面积（送餐模式）": round(meal_people * _require_number(parameters, "meal.deliveryAreaPerPerson"), 2),
        "助餐设施/社区食堂厨房建筑面积（堂食模式）": round(meal_people * _require_number(parameters, "meal.kitchenAreaPerPerson"), 2),
        "助餐设施/社区食堂配餐空间建筑面积（堂食模式）": round(meal_people * _require_number(parameters, "meal.preparationAreaPerPerson"), 2),
        "助餐设施/社区食堂用餐空间建筑面积（堂食模式）": round(meal_people * _require_number(parameters, "meal.diningSpaceAreaPerPerson"), 2),
        "养老服务设施/生活不能完全自理老年人占比": round(disabled_people / elderly_total * 100, 2) if elderly_total else 0,
        "养老服务设施/老年服务站容纳量": station_capacity,
        "养老服务设施/老年服务站容纳量缺口": round(station_capacity - existing_station_capacity, 2),
        "养老服务设施/老年服务站配置建筑面积": station_area,
        "养老服务设施/老年服务站建筑面积缺口": round(station_area - existing_station_area, 2),
        "养老服务设施/日间服务需求人数": round_half_up(disabled_people),
        "养老服务设施/保健康复服务需求人数": round_half_up(rehabilitation_people),
        "养老服务设施/文化娱乐服务需求人数": round_half_up(entertainment_people),
        "养老服务设施/交通接送服务需求人数": round_half_up(transport_people),
        "托育服务设施/托儿所建筑面积": round(nursery_people * _require_number(parameters, "childcare.nurseryAreaPerPerson"), 2),
        "托育服务设施/幼儿园建筑面积": round(kindergarten_people * _require_number(parameters, "childcare.kindergartenBuildingAreaPerPerson"), 2),
        "托育服务设施/幼儿园用地面积": round(kindergarten_people * _require_number(parameters, "childcare.kindergartenLandAreaPerPerson"), 2),
        "托育服务设施/幼儿园室外活动场地面积": round(kindergarten_people * _require_number(parameters, "childcare.outdoorAreaPerPerson"), 2),
        "托育服务设施/幼儿园全园共用活动场地面积": round(kindergarten_people * _require_number(parameters, "childcare.sharedAreaPerPerson"), 2),
        "托育服务设施/幼儿园活动室与寝室使用面积（合并建设）": round(kindergarten_people * _require_number(parameters, "childcare.combinedRoomAreaPerPerson"), 2),
        "托育服务设施/幼儿园活动室使用面积（分开设置）": round(kindergarten_people * _require_number(parameters, "childcare.activityRoomAreaPerPerson"), 2),
        "托育服务设施/幼儿园寝室使用面积（分开设置）": round(kindergarten_people * _require_number(parameters, "childcare.bedroomAreaPerPerson"), 2),
        "停车充电设施/机动车充电桩缺口数量（户均法）": round_half_up(households * _require_number(parameters, "parking.chargersPerHousehold") - active_chargers),
        "停车充电设施/机动车充电桩缺口数量（新能源车保有量法）": round_half_up(total * new_energy_rate - active_chargers),
        "停车充电设施/停车位缺口数量（户均法）": round_half_up(households * _require_number(parameters, "parking.parkingSpacesPerHousehold") - current_parking_spaces),
        "停车充电设施/停车位缺口数量（机动车保有量法）": round_half_up(total * vehicle_rate - current_parking_spaces),
        "公共活动场地/公共活动场地面积": public_area,
        "公共活动场地/多功能运动场地面积": sports_area,
    }
    elderly_paths = lambda prefix: [f"elderly.{prefix}.{group}" for group in ("60-69岁", "70-79岁", "80岁以上")]
    metric_paths: dict[str, list[str]] = {}
    for metric in metrics:
        label = metric.split("/", 1)[1]
        if metric.startswith("助餐设施/"):
            paths = ["meal.demandRate"]
            paths += ["meal.deliveryAreaPerPerson"] if "送餐" in label else ["meal.kitchenAreaPerPerson"] if "厨房" in label else ["meal.preparationAreaPerPerson"] if "配餐空间" in label else ["meal.diningSpaceAreaPerPerson"] if "用餐空间" in label else ["meal.diningAreaPerPerson"] if "建筑面积" in label else []
        elif metric.startswith("养老服务设施/"):
            paths = elderly_paths("disabilityRates") if "不能完全自理" in label or "日间" in label else elderly_paths("rehabilitationRates") if "保健康复" in label else elderly_paths("entertainmentRates") if "文化娱乐" in label else elderly_paths("transportRates") if "交通接送" in label else ["elderly.stationDemandRate", "elderly.stationAreaPerPerson"] if "建筑面积" in label else ["elderly.stationDemandRate"]
        elif metric.startswith("托育服务设施/"):
            paths = ["childcare.nurseryDemandRate", "childcare.nurseryAreaPerPerson"] if "托儿所" in label else ["childcare.kindergartenDemandRate", "childcare.outdoorAreaPerPerson"] if "室外" in label else ["childcare.kindergartenDemandRate", "childcare.sharedAreaPerPerson"] if "全园共用" in label else ["childcare.kindergartenDemandRate", "childcare.combinedRoomAreaPerPerson"] if "合并建设" in label else ["childcare.kindergartenDemandRate", "childcare.activityRoomAreaPerPerson"] if "活动室使用" in label else ["childcare.kindergartenDemandRate", "childcare.bedroomAreaPerPerson"] if "寝室使用" in label else ["childcare.kindergartenDemandRate", "childcare.kindergartenLandAreaPerPerson"] if "用地" in label else ["childcare.kindergartenDemandRate", "childcare.kindergartenBuildingAreaPerPerson"]
        elif metric.startswith("停车充电设施/"):
            paths = ["parking.chargerLifetime", "parking.chargersPerHousehold"] if "充电桩" in label and "户均" in label else ["parking.parkingSpacesPerHousehold"] if "停车位" in label and "户均" in label else ["parking.chargerLifetime"] if "充电桩" in label else []
        else:
            paths = ["activity.sportsAreaPerCapita"] if "多功能" in label else ["activity.publicAreaPerCapita"]
        metric_paths[metric] = paths
    references = {metric: _parameter_reference(parameters, metric_paths[metric]) for metric in metrics}
    vehicle_source = parameters.get("vehicleSources", {}).get(str(year), "用户录入，来源未填写")
    for metric in metrics:
        if "保有量法" in metric:
            references[metric] = {"standard": f"{new_energy_rate:g}辆/人" if "充电桩" in metric else f"{vehicle_rate:g}辆/人", "source": vehicle_source}
    site_analysis = {
        "助餐设施": _site_analysis(community, "社区食堂", year, required_building=dining_area, existing_building=existing_meal, review_focus="首层无障碍、送餐动线、消防与食品安全条件"),
        "养老服务设施": _site_analysis(community, "老年服务站", year, required_building=station_area, existing_building=existing_station_area, review_focus="老年人口服务半径、无障碍、急救通达与权属条件"),
        "公共活动场地": _site_analysis(community, "公共活动场地", year, required_land=public_area, existing_land=existing_public_area, review_focus="开放可达性、日照、安全和规划兼容性"),
        "多功能运动场地": _site_analysis(community, "多功能运动场地", year, required_land=sports_area, existing_land=existing_sports_area, review_focus="噪声影响、居民步行可达性、安全缓冲和规划条件"),
    }
    suggestions = {category: analysis["conclusion"] for category, analysis in site_analysis.items()}
    return metrics, references, suggestions, site_analysis


def run_facility_prediction(
    db: Session,
    project: Project,
    seed: int,
    population_run_id: int | None,
) -> PredictionRun:
    parameters = db.scalar(
        select(ParameterSet).where(ParameterSet.project_id == project.id, ParameterSet.kind == "facility")
    )
    if not parameters:
        raise ValueError("缺少设施预测参数")
    population_run = db.get(PredictionRun, population_run_id) if population_run_id else db.scalar(
        select(PredictionRun)
        .where(PredictionRun.project_id == project.id, PredictionRun.kind == "population", PredictionRun.status == "success")
        .order_by(PredictionRun.id.desc())
    )
    if not population_run:
        raise ValueError("没有可用的人口预测结果")
    if population_run.project_id != project.id or population_run.kind != "population" or population_run.status != "success":
        raise ValueError("指定的人口预测批次不属于当前工程或尚未成功")

    run = PredictionRun(
        project_id=project.id,
        kind="facility",
        status="running",
        seed=seed,
        parameters_snapshot={**parameters.data, "_algorithmVersion": "2026.09-audit1", "_populationRunId": population_run.id, "_communities": population_run.parameters_snapshot.get("_communities", [])},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    result_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        validate_parameters("facility", parameters.data)
        population_results = list(
            db.scalars(
                select(PredictionResult)
                .where(PredictionResult.run_id == population_run.id)
                .order_by(PredictionResult.community_id, PredictionResult.year)
            ).all()
        )
        for population_result in population_results:
            community = population_result.community
            metrics, references, suggestions, site_analysis = _facility_metrics(
                population_result.data, parameters.data, community, population_result.year
            )
            summary = {
                "communitySnapshot": population_result.data.get("communitySnapshot", {"code": community.code, "name": community.name}),
                "year": population_result.year,
                "metrics": metrics,
                "references": references,
                "siteSuggestions": suggestions,
                "siteAnalysis": site_analysis,
                "calculationAudit": {"population": population_result.data, "facilities": community.facilities, "idleSpaces": community.idle_spaces, "populationRunId": population_run.id},
            }
            db.add(
                PredictionResult(
                    run_id=run.id,
                    community_id=community.id,
                    year=population_result.year,
                    data=summary,
                )
            )
            result_map[f"{community.code}-{community.name}"].append(summary)

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_path = Path(project.path) / "output" / f"PreResult_fac_run{run.id}_{timestamp}.xlsx"
        export_facility_results(output_path, result_map)
        run.status = "success"
        run.output_file = str(output_path)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        failed_run = db.get(PredictionRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.error_message = str(exc)
            failed_run.completed_at = datetime.now(timezone.utc)
            db.commit()
        raise
