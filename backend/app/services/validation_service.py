"""Validate editable parameters before persisting or running a prediction."""
from math import isfinite
from typing import Any

from ..defaults import REQUIRED_FACILITY_PATHS
from .age_distribution import validate_age_band_partition


def finite_number(value: Any, label: str, minimum: float = 0, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label}必须是有效数字") from exc
    if isinstance(value, bool) or not isfinite(number) or number < minimum or (maximum is not None and number > maximum):
        raise ValueError(f"{label}超出允许范围（最小{minimum:g}" + (f"，最大{maximum:g}" if maximum is not None else "") + "）")
    return number


def validate_parameters(kind: str, data: dict) -> None:
    if kind == "population":
        for unit in ("birthRateUnit", "deathRateUnit"):
            if data.get(unit, "‰") != "‰":
                raise ValueError("出生率与死亡率必须使用千分率（‰），请先换算数值")
        if "_pendingUniformDeath" in data:
            raise ValueError("统一死亡率尚未应用，请先确认应用到预测年度，或取消统一编辑")
        for field, minimum, maximum in (("startYear", 1900, 9900), ("duration", 1, 100)):
            number = finite_number(data.get(field), field, minimum, maximum)
            if not number.is_integer():
                raise ValueError(f"{field}必须为整数")
        if int(data["startYear"]) + int(data["duration"]) > 9999:
            raise ValueError("预测结束年份不能超过9999年")
        for field in ("birthRates", "deathRates"):
            groups = data.get(field)
            if not isinstance(groups, dict) or not groups:
                raise ValueError(f"人口参数缺少：{field}")
            for group, series in groups.items():
                if field == "deathRates" and (not str(group).isdigit() or not 1900 <= int(group) <= 9999):
                    raise ValueError(f"死亡率年份无效：{group}")
                if not isinstance(series, dict):
                    raise ValueError(f"{field}.{group}格式错误")
                for key, value in series.items():
                    if field == "birthRates" and (not str(key).isdigit() or not 1900 <= int(key) <= 9999):
                        raise ValueError(f"出生率年份无效：{key}")
                    finite_number(value, f"{field}.{group}.{key}", 0, 1000)
                if field == "deathRates":
                    validate_age_band_partition(series, field=f"{group}年死亡率年龄段")
    else:
        for path in REQUIRED_FACILITY_PATHS:
            current: Any = data
            for part in path.split("."):
                current = current.get(part) if isinstance(current, dict) else None
            # Incomplete facility drafts can be saved; execution checks completeness.
            if current in (None, ""):
                continue
            number = finite_number(current, path, 0, 100 if "Rate" in path or "Rates." in path else None)
            if path == "parking.chargerLifetime" and number <= 0:
                raise ValueError("充电桩寿命必须大于0")
        parking = data.get("parking", {})
        if not isinstance(parking, dict):
            raise ValueError("停车充电参数格式错误")
        for field in ("newEnergyVehiclesPerCapita", "vehiclesPerCapita"):
            series = parking.get(field, {})
            if not isinstance(series, dict):
                raise ValueError(f"{field}必须为年度数值表")
            for year, value in series.items():
                if not str(year).isdigit() or not 1900 <= int(year) <= 9999:
                    raise ValueError(f"车辆数据年份无效：{year}")
                if value not in (None, ""):
                    finite_number(value, f"{field}.{year}")
