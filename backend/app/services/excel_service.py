from __future__ import annotations

import re
import math
from collections import Counter
from copy import copy
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook, load_workbook

from ..defaults import (
    AGE_GROUPS,
    DEFAULT_MIGRATION_RATES,
    FACILITY_PARAMETER_GROUPS,
    MORTALITY_GROUPS,
    REQUIRED_FACILITY_PATHS,
)
from .age_distribution import MAX_AGE, distribute_age_bands_uniformly, simulate_population_records, validate_age_band_partition


_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _repair_invalid_excel_fills(content: bytes) -> bytes:
    """Repair empty OOXML fill records that Excel/WPS accepts but openpyxl rejects.

    The source upload is never changed.  Empty ``<fill/>`` entries are kept at
    the same index and converted to a neutral pattern fill, so existing style
    references remain valid.
    """
    source = BytesIO(content)
    with ZipFile(source) as archive:
        if "xl/styles.xml" not in archive.namelist():
            return content
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        fills = styles.find(f"{{{_SPREADSHEET_NS}}}fills")
        if fills is None:
            return content
        changed = False
        for fill in fills.findall(f"{{{_SPREADSHEET_NS}}}fill"):
            children = list(fill)
            if children and children[0].tag.rsplit("}", 1)[-1] in {"patternFill", "gradientFill"}:
                continue
            fill.clear()
            ET.SubElement(fill, f"{{{_SPREADSHEET_NS}}}patternFill", {"patternType": "none"})
            changed = True
        if not changed:
            return content
        repaired_styles = ET.tostring(styles, encoding="utf-8", xml_declaration=True)
        target = BytesIO()
        with ZipFile(target, "w", ZIP_DEFLATED) as output:
            output.comment = archive.comment
            for item in archive.infolist():
                output.writestr(item, repaired_styles if item.filename == "xl/styles.xml" else archive.read(item.filename))
        return target.getvalue()


def _load_workbook(path: Path, **kwargs):
    """Open user workbooks through a non-destructive OOXML compatibility layer."""
    content = Path(path).read_bytes()
    return load_workbook(BytesIO(_repair_invalid_excel_fills(content)), **kwargs)


def clean_text(value: Any) -> str:
    return str(value or "").replace("\u200b", "").replace("\u200c", "").replace("\ufeff", "").strip()


def _compact_text(value: Any) -> str:
    return re.sub(r"[\s\u3000]+", "", clean_text(value)).replace("（", "(").replace("）", ")")


def _key_value_sheet(workbook, sheet_name: str) -> dict[str, Any]:
    if sheet_name not in workbook.sheetnames:
        raise ValueError(f"缺少工作表：{sheet_name}")
    sheet = workbook[sheet_name]
    return {clean_text(row[0].value): row[1].value for row in sheet.iter_rows(min_row=2) if clean_text(row[0].value)}


def _migration_rate_fields(group: str) -> list[str]:
    return [
        f"社区{group}常住人口复合年均净迁入率（‰）",
        f"社区{group}常住人口年均净迁入率（‰）",
        f"社区{group}常住人口复合年均净迁入率（%）",
        f"社区{group}常住人口年均净迁入率（%）",
    ]


def _reject_percentage_cells(workbook, sheet_names):
    for name in sheet_names:
        sheet = workbook[name]
        for row in sheet.iter_rows(min_row=2):
            if name == "社区基本信息" and "净迁入率" not in str(row[0].value):
                continue
            for cell in row[1:]:
                if cell.value is not None and "%" in cell.number_format:
                    raise ValueError(f"{name}!{cell.coordinate}使用了Excel百分比格式，请改成普通数字并按表头单位填写，避免比例被缩小100倍")


def parse_population_parameters(path: Path) -> dict[str, Any]:
    workbook = _load_workbook(path, data_only=True, read_only=True)
    for required in ("基础参数", "出生率", "死亡率"):
        if required not in workbook.sheetnames:
            raise ValueError(f"人口参数文件缺少工作表：{required}")
    _reject_percentage_cells(workbook, ("出生率", "死亡率"))

    base = _key_value_sheet(workbook, "基础参数")
    for key in ("出生率单位", "死亡率单位"):
        if base.get(key, "‰") != "‰":
            workbook.close()
            raise ValueError(f"{key}必须为‰，请先换算为千分率")
    start_year = int(base.get("预测开始年份") or 2026)
    duration = int(base.get("预测时长（年）") or 5)

    birth_sheet = workbook["出生率"]
    birth_headers = [clean_text(cell.value) for cell in next(birth_sheet.iter_rows(min_row=1, max_row=1))]
    if any("%" in header for header in birth_headers):
        workbook.close()
        raise ValueError("出生率必须为千分率‰，不能直接导入百分率表")
    birth_headers = [re.sub(r"[（(]‰[）)]$", "", header) for header in birth_headers]
    birth_rates: dict[str, dict[str, float]] = {header: {} for header in birth_headers[1:] if header}
    for row in birth_sheet.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        year = str(int(row[0]))
        for index, header in enumerate(birth_headers[1:], start=1):
            if header and index < len(row) and row[index] is not None:
                birth_rates[header][year] = float(row[index])

    # A parameter workbook may contain optional scenario/reference columns whose
    # forecast cells are intentionally blank (for example high/low scenarios).
    # They must not become required regions in the editor.  Keep only series
    # that actually provide at least one value for this forecast window; retain
    # the old behaviour when none of the columns covers the window so the user
    # can still see and repair genuinely incomplete input.
    forecast_years = {str(year) for year in range(start_year + 1, start_year + duration + 1)}
    usable_birth_rates = {
        region: series
        for region, series in birth_rates.items()
        if any(year in series for year in forecast_years)
    }
    if usable_birth_rates:
        birth_rates = usable_birth_rates

    death_sheet = workbook["死亡率"]
    raw_headers = [clean_text(cell.value) for cell in next(death_sheet.iter_rows(min_row=1, max_row=1))]
    if any("%" in header for header in raw_headers):
        workbook.close()
        raise ValueError("死亡率必须为千分率‰，不能直接导入百分率表")
    death_headers = [re.sub(r"死亡率.*$", "", item).strip("（）() ") for item in raw_headers[1:]]
    if "6-9岁" in death_headers:
        death_headers[death_headers.index("6-9岁")] = "5-9岁"
    validate_age_band_partition(death_headers, field="死亡率年龄段")
    death_rates: dict[str, dict[str, float]] = {}
    for row in death_sheet.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        death_rates[str(int(row[0]))] = {
            death_headers[index - 1]: float(row[index])
            for index in range(1, min(len(row), len(death_headers) + 1))
            if row[index] is not None
        }

    result = {
        "startYear": start_year,
        "duration": duration,
        "birthRateUnit": "‰",
        "deathRateUnit": "‰",
        "birthRates": birth_rates,
        "deathRates": death_rates,
        "sourceNotes": {
            "birth": clean_text(base.get("出生率参考来源说明")),
            "death": clean_text(base.get("死亡率参考来源说明")),
        },
    }
    workbook.close()
    return result


FACILITY_SHEET_MAPPING = {
    "助餐": "meal",
    "养老": "elderly",
    "托育": "childcare",
    "停车充电": "parking",
    "乘用机动车保有量": "vehicleOwnership",
    "公共活动场地": "activity",
}


FACILITY_PARAMETER_MAPPING = {
    "助餐": {
        "老年人助餐服务需求率（%）": "meal.demandRate",
        "堂食模式下社区食堂人均配置建筑面积（平方米）": "meal.diningAreaPerPerson",
        "堂食模式下社区食堂厨房人均配置建筑面积（平方米）": "meal.kitchenAreaPerPerson",
        "堂食模式下社区食堂配餐空间人均配置建筑面积（平方米）": "meal.preparationAreaPerPerson",
        "堂食模式下社区食堂用餐空间人均配置建筑面积（平方米）": "meal.diningSpaceAreaPerPerson",
        "送餐模式下社区食堂人均配置建筑面积（平方米）": "meal.deliveryAreaPerPerson",
    },
    "养老": {
        "生活不能完全自理的60-69岁老年人比例（%）": "elderly.disabilityRates.60-69岁",
        "生活不能完全自理的70-79岁老年人比例（%）": "elderly.disabilityRates.70-79岁",
        "生活不能完全自理的80岁以上老年人比例（%）": "elderly.disabilityRates.80岁以上",
        "老年服务站需求率": "elderly.stationDemandRate",
        "老年服务站需求率（%）": "elderly.stationDemandRate",
        "老年服务站人均配置建筑面积（平方米）": "elderly.stationAreaPerPerson",
        "60-69岁老年人保健康复服务需求率（%）": "elderly.rehabilitationRates.60-69岁",
        "70-79岁老年人保健康复服务需求率（%）": "elderly.rehabilitationRates.70-79岁",
        "80岁以上老年人保健康复服务需求率（%）": "elderly.rehabilitationRates.80岁以上",
        "60-69岁老年人文化娱乐服务需求率（%）": "elderly.entertainmentRates.60-69岁",
        "70-79岁老年人文化娱乐服务需求率（%）": "elderly.entertainmentRates.70-79岁",
        "80岁以上老年人文化娱乐服务需求率（%）": "elderly.entertainmentRates.80岁以上",
        "60-69岁老年人交通接送服务需求率（%）": "elderly.transportRates.60-69岁",
        "70-79岁老年人交通接送服务需求率（%）": "elderly.transportRates.70-79岁",
        "80岁以上老年人交通接送服务需求率（%）": "elderly.transportRates.80岁以上",
    },
    "托育": {
        "托儿所人均配置建筑面积（平方米）": "childcare.nurseryAreaPerPerson",
        "托儿所入托需求率（%）": "childcare.nurseryDemandRate",
        "幼儿园人均配置建筑面积（平方米）": "childcare.kindergartenBuildingAreaPerPerson",
        "幼儿园人均配置用地面积（平方米）": "childcare.kindergartenLandAreaPerPerson",
        "幼儿园人均配置室外活动场地面积（平方米）": "childcare.outdoorAreaPerPerson",
        "幼儿园人均配置全园共用活动场地面积（平方米）": "childcare.sharedAreaPerPerson",
        "幼儿园入园需求率（%）": "childcare.kindergartenDemandRate",
        "幼儿园人均活动室与寝室使用面积（活动室与寝室合并建设）（平方米）": "childcare.combinedRoomAreaPerPerson",
        "幼儿园人均活动室使用面积（活动室与寝室分开建设）（平方米）": "childcare.activityRoomAreaPerPerson",
        "幼儿园人均寝室使用面积（活动室与寝室分开建设）（平方米）": "childcare.bedroomAreaPerPerson",
    },
    "停车充电": {
        "充电桩寿命（年）": "parking.chargerLifetime",
        "充电桩配比（个/户）": "parking.chargersPerHousehold",
        "停车位配比（个/户）": "parking.parkingSpacesPerHousehold",
    },
    "公共活动场地": {
        "人均公共活动场地面积（平方米）": "activity.publicAreaPerCapita",
        "人均多功能运动场地面积（平方米）": "activity.sportsAreaPerCapita",
    },
}


def _set_nested(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    current = target
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _get_nested(target: dict[str, Any], dotted_path: str) -> Any:
    current: Any = target
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def finalize_facility_parameters(data: dict[str, Any]) -> dict[str, Any]:
    """Refresh readiness metadata while preserving user-entered values and sources."""
    missing = [path for path in REQUIRED_FACILITY_PATHS if _get_nested(data, path) in (None, "")]
    vehicle_values = data.get("parking", {}) if isinstance(data.get("parking"), dict) else {}
    new_energy_series = vehicle_values.get("newEnergyVehiclesPerCapita")
    vehicle_series = vehicle_values.get("vehiclesPerCapita")
    if not isinstance(new_energy_series, dict) or not any(value not in (None, "") for value in new_energy_series.values()):
        missing.append("parking.newEnergyVehiclesPerCapita")
    if not isinstance(vehicle_series, dict) or not any(value not in (None, "") for value in vehicle_series.values()):
        missing.append("parking.vehiclesPerCapita")
    data["missingRequired"] = missing
    data["status"] = "ready" if not missing else "incomplete"
    return data


def parse_facility_parameters(path: Path) -> dict[str, Any]:
    workbook = _load_workbook(path, data_only=True, read_only=True)
    result: dict[str, Any] = {"status": "imported", "raw": {}, "references": {}}
    for sheet_name, key in FACILITY_SHEET_MAPPING.items():
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"设施参数文件缺少工作表：{sheet_name}")
        sheet = workbook[sheet_name]
        headers = [clean_text(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        rows = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0] is None:
                continue
            row_data = {headers[index] or f"column_{index + 1}": value for index, value in enumerate(row)}
            rows.append(row_data)
            label = clean_text(row[0])
            if sheet_name == "乘用机动车保有量":
                year = str(int(row[0]))
                if len(row) > 1 and row[1] not in (None, ""):
                    _set_nested(result, f"parking.newEnergyVehiclesPerCapita.{year}", float(row[1]))
                if len(row) > 2 and row[2] not in (None, ""):
                    _set_nested(result, f"parking.vehiclesPerCapita.{year}", float(row[2]))
                if len(row) > 3 and row[3] not in (None, ""):
                    result.setdefault("vehicleSources", {})[year] = clean_text(row[3])
                continue
            canonical_path = FACILITY_PARAMETER_MAPPING.get(sheet_name, {}).get(label)
            if canonical_path and len(row) > 1:
                _set_nested(result, canonical_path, row[1])
                result["references"][canonical_path] = {
                    "standard": row[1],
                    "source": row[2] if len(row) > 2 else None,
                }
        result["raw"][key] = rows
    finalize_facility_parameters(result)
    workbook.close()
    return result


def _age_counts_from_population_sheet(workbook) -> dict[str, int]:
    if "社区人口列表" not in workbook.sheetnames:
        raise ValueError("社区文件缺少工作表：社区人口列表")
    sheet = workbook["社区人口列表"]
    headers = [clean_text(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    try:
        age_index = headers.index("年龄")
    except ValueError as exc:
        raise ValueError("社区人口列表缺少“年龄”列") from exc
    counter: Counter[int] = Counter()
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if age_index < len(row) and row[age_index] is not None:
            counter[max(0, min(MAX_AGE, int(row[age_index])))] += 1
    return {str(age): counter.get(age, 0) for age in range(MAX_AGE + 1)}


def _read_age_summary(workbook) -> dict[str, int]:
    if "人口年龄汇总" not in workbook.sheetnames:
        return {}
    result = {}
    for row in workbook["人口年龄汇总"].iter_rows(min_row=2, values_only=True):
        if not any(v not in (None, "") for v in row):
            continue
        key = clean_text(row[0])
        count = float(row[1])
        if not (key in AGE_GROUPS or key.isdigit() and 0 <= int(key) <= MAX_AGE) or not math.isfinite(count) or count < 0 or not count.is_integer():
            raise ValueError("人口年龄汇总的年龄或人数无效")
        if key in result:
            raise ValueError("人口年龄汇总存在重复年龄")
        result[key] = int(count)
    if result and any(k.isdigit() for k in result) and not all(k.isdigit() for k in result):
        raise ValueError("不能混用单岁年龄与年龄段汇总")
    return result


SURVEY_MAIN_SHEET = "社区基本信息与设施信息调研表"
SURVEY_POPULATION_SHEET_PREFIX = "7.2 社区人口性别和出生年月统计"


def _sheet_by_clean_name(workbook, expected: str, *, prefix: bool = False):
    expected_name = _compact_text(expected)
    for sheet in workbook.worksheets:
        title = _compact_text(sheet.title)
        matches = title.startswith(expected_name) if prefix else title == expected_name
        if matches:
            return sheet
    return None


def _find_survey_main_sheet(workbook):
    exact = _sheet_by_clean_name(workbook, SURVEY_MAIN_SHEET)
    if exact is not None:
        return exact
    for sheet in workbook.worksheets:
        title = _compact_text(sheet.title)
        first_cell = _compact_text(sheet.cell(1, 1).value)
        candidate = title + first_cell
        if "社区基本信息" in candidate and "设施" in candidate and "调研表" in candidate:
            return sheet
    return None


def _find_survey_population_sheet(workbook):
    exact = _sheet_by_clean_name(workbook, SURVEY_POPULATION_SHEET_PREFIX, prefix=True)
    if exact is not None:
        return exact
    for sheet in workbook.worksheets:
        title = _compact_text(sheet.title)
        rows = list(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 20), values_only=True))
        has_population_header = any(
            "序号" in {_compact_text(value) for value in row}
            and any("年龄" in _compact_text(value) for value in row)
            for row in rows
        )
        first_rows = "".join(_compact_text(value) for row in rows for value in row)
        candidate = title + first_rows
        if has_population_header and "人口" in candidate and "性别" in candidate and ("出生" in candidate or "年龄" in candidate):
            return sheet
    return None


def _is_community_survey_workbook(workbook) -> bool:
    return _find_survey_main_sheet(workbook) is not None


def _survey_label_columns(sheet) -> tuple[int, int]:
    for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 40)):
        normalized = [_compact_text(cell.value) for cell in row]
        if "信息数据" in normalized and "指标值" in normalized:
            return normalized.index("信息数据") + 1, normalized.index("指标值") + 1
    return 4, 5


def _survey_main_values(sheet) -> dict[str, Any]:
    result: dict[str, Any] = {}
    label_column, value_column = _survey_label_columns(sheet)
    for row in sheet.iter_rows(values_only=True):
        label = clean_text(row[label_column - 1] if len(row) >= label_column else None)
        value = row[value_column - 1] if len(row) >= value_column else None
        if label and value not in (None, ""):
            result[label] = value
    return result


def _survey_section_values(sheet, section_prefix: str) -> dict[str, Any]:
    label_column, value_column = _survey_label_columns(sheet)
    start = next((row for row in range(1, sheet.max_row + 1) if any(_compact_text(cell.value).startswith(section_prefix) for cell in sheet[row])), None)
    if start is None:
        return {}
    result: dict[str, Any] = {}
    for row_number in range(start + 1, sheet.max_row + 1):
        heading = next((_compact_text(cell.value) for cell in sheet[row_number] if re.match(r"^\d+\.\d+", _compact_text(cell.value))), "")
        if heading:
            break
        label = clean_text(sheet.cell(row_number, label_column).value)
        value = sheet.cell(row_number, value_column).value
        if label and value not in (None, ""):
            result[label] = value
    return result


def _survey_number(values: dict[str, Any], label_fragment: str, default: float = 0) -> float:
    value = next((value for label, value in values.items() if label_fragment in label), default)
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _survey_coordinate(value: Any, limit: float) -> float | None:
    if value in (None, "", "/"):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = clean_text(value).upper().replace(",", "")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(match.group())
        if ("W" in text or "西" in text or "S" in text or "南" in text) and number > 0:
            number = -number
    return number if math.isfinite(number) and -limit <= number <= limit else None


def _survey_population_records(sheet, base_year: int) -> tuple[list[dict[str, Any]], int, int]:
    records: list[dict[str, Any]] = []
    missing_age = 0
    unknown_gender = 0
    header_row = None
    columns: dict[str, int] = {}
    for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 20), values_only=True), 1):
        values = [_compact_text(value) for value in row]
        if any(value == "序号" for value in values) and any("年龄" in value for value in values):
            header_row = row_number
            for index, value in enumerate(values):
                if value == "序号": columns["sequence"] = index
                elif "性别" in value and "结构" not in value: columns["gender"] = index
                elif "出生" in value: columns["birth"] = index
                elif "年龄" in value and "年龄段" not in value: columns["age"] = index
            break
    if header_row is None or "sequence" not in columns:
        return records, 0, 0
    for row in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        sequence = row[columns["sequence"]] if len(row) > columns["sequence"] else None
        try:
            sequence_number = int(sequence)
            if float(sequence) != sequence_number:
                raise ValueError
        except (TypeError, ValueError):
            continue
        age_value = row[columns["age"]] if "age" in columns and len(row) > columns["age"] else None
        birth_value = row[columns["birth"]] if "birth" in columns and len(row) > columns["birth"] else None
        try:
            if age_value not in (None, ""):
                age = int(age_value)
                if float(age_value) != age:
                    raise ValueError
            else:
                birth_year = int(birth_value)
                if float(birth_value) != birth_year:
                    raise ValueError
                age = base_year - birth_year
            if not 0 <= age <= MAX_AGE:
                raise ValueError
        except (TypeError, ValueError):
            missing_age += 1
            continue
        gender = clean_text(row[columns["gender"]] if "gender" in columns and len(row) > columns["gender"] else None)
        gender = "男" if gender.startswith("男") else "女" if gender.startswith("女") else gender
        if gender not in ("男", "女"):
            unknown_gender += 1
            gender = "未知"
        records.append({"序号": sequence_number, "性别": gender or "未知", "出生年份": base_year - age, "年龄": age})
    return records, missing_age, unknown_gender


def _survey_population_summary(main: dict[str, Any], population_sheet=None) -> dict[str, int]:
    """Expand the survey's original broad bands into reusable single-age counts."""
    source = {
        "0-6岁": int(_survey_number(main, "0-6岁", 0)),
        "7-12岁": int(_survey_number(main, "7-12岁", 0)),
        "13-17岁": int(_survey_number(main, "13-17岁", 0)),
        "18-35岁": int(_survey_number(main, "18-35岁", 0)),
        "36-59岁": int(_survey_number(main, "36-59岁", 0)),
        "60-69岁": int(_survey_number(main, "60-69岁", 0)),
        "70-79岁": int(_survey_number(main, "70-79岁", 0)),
        "80岁以上": int(_survey_number(main, "80岁以上", 0)),
    }
    if population_sheet is not None:
        count_column = None
        for row in population_sheet.iter_rows(min_row=1, max_row=min(population_sheet.max_row, 12), values_only=True):
            for index, value in enumerate(row):
                if _compact_text(value) == "人数":
                    count_column = index
                    break
            if count_column is not None:
                break
        for row in population_sheet.iter_rows(values_only=True):
            values = list(row)
            for index, value in enumerate(values):
                label = _compact_text(value)
                for group in tuple(source):
                    if label.startswith(_compact_text(group)):
                        candidate = values[count_column] if count_column is not None and len(values) > count_column else None
                        if isinstance(candidate, (int, float)) and math.isfinite(float(candidate)):
                            source[group] = int(candidate)
                        break
    if not sum(source.values()):
        return {}

    return distribute_age_bands_uniformly(source)


def _survey_chargers(workbook) -> list[dict[str, Any]]:
    sheet = _sheet_by_clean_name(workbook, "3.2停车及充电设施")
    if sheet is None:
        return []
    result = []
    for row in sheet.iter_rows(min_row=4, values_only=True):
        if clean_text(row[1] if len(row) > 1 else None) != "机动车充电桩":
            continue
        identifier = clean_text(row[0] if row else None)
        if identifier:
            result.append({
                "机动车充电桩编号": identifier,
                "经度": _survey_coordinate(row[2] if len(row) > 2 else None, 180),
                "纬度": _survey_coordinate(row[3] if len(row) > 3 else None, 90),
            })
    return result


def _survey_activity_areas(workbook) -> tuple[float, float]:
    sheet = _sheet_by_clean_name(workbook, "4.1公共活动场地")
    if sheet is None:
        return 0, 0
    totals = [0.0, 0.0]
    for row in sheet.iter_rows(min_row=4, values_only=True):
        if not clean_text(row[0] if row else None):
            continue
        for total_index, column_index in enumerate((3, 4)):
            try:
                value = float(row[column_index])
            except (IndexError, TypeError, ValueError):
                value = 0
            if math.isfinite(value) and value >= 0:
                totals[total_index] += value
    return round(totals[0], 2), round(totals[1], 2)


def _parse_community_survey_workbook(workbook) -> dict[str, Any]:
    main_sheet = _find_survey_main_sheet(workbook)
    population_sheet = _find_survey_population_sheet(workbook)
    if main_sheet is None or population_sheet is None:
        raise ValueError("综合调研表缺少社区主表或社区人口明细表")
    main = _survey_main_values(main_sheet)
    code = clean_text(main.get("社区编号"))
    name = clean_text(main.get("社区名称"))
    if not code or not name:
        raise ValueError("综合调研表缺少社区编号或社区名称")

    date_text = clean_text(main_sheet.cell(3, 1).value)
    year_match = re.search(r"(19|20)\d{2}", date_text)
    population_base_year = int(year_match.group()) if year_match else 2026
    records, missing_age, unknown_gender = _survey_population_records(population_sheet, population_base_year)
    age_counts: dict[str, int] = {}
    used_summary = False
    used_total_only = False
    if records:
        total_population = len(records)
        age_counts = {str(age): count for age, count in sorted(Counter(int(row["年龄"]) for row in records).items())}
    else:
        age_counts = _survey_population_summary(main, population_sheet)
        stated_population = int(_survey_number(main, "常住人口数量", 0))
        if not age_counts:
            if stated_population <= 0:
                raise ValueError("综合调研表没有可用的居民年龄明细、年龄段汇总或常住人口总数")
            age_counts = distribute_age_bands_uniformly({"0-100岁": stated_population})
            used_total_only = True
        total_population = sum(age_counts.values())
        used_summary = True
        # Empty numbered template rows are not resident records.
        missing_age = 0
        unknown_gender = 0
    stated_population = int(_survey_number(main, "常住人口数量", 0))
    households = int(_survey_number(main, "社区总户数", 0)) or round(total_population / 2.5)

    if used_summary:
        records = simulate_population_records(age_counts, population_base_year)

    meal = _survey_section_values(main_sheet, "2.3")
    elderly = _survey_section_values(main_sheet, "1.4")
    nursery = _survey_section_values(main_sheet, "1.3")
    kindergarten = _survey_section_values(main_sheet, "1.2")
    parking = _survey_section_values(main_sheet, "3.2")
    public_area, sports_area = _survey_activity_areas(workbook)
    notes = [
        "已从《社区基本信息与服务设施信息调研表》自动识别并转换；原始上传文件完整保留在工程 input 目录。",
        "原表未提供分年龄段净迁入率，已按0‰导入，可在预测前按当地数据调整。",
        "原表没有社区闲置空间清单，设施预测可以执行，但选址建议会提示补充候选空间。",
    ]
    warnings: list[str] = []
    if used_summary:
        message = (
            "调研表未提供逐人明细或年龄段汇总，已按常住人口总数在0—100岁间均匀生成非实名模拟人口；"
            if used_total_only else
            "人口分表未填写逐人明细，已按原始年龄段内的单岁均匀分布生成非实名模拟人口；"
        ) + "性别比按女性100、男性105.07生成，出生年份由人口基准年与年龄计算。"
        notes.append(message)
    if stated_population and stated_population != total_population:
        source_label = "年龄段汇总" if used_summary else "人口明细"
        message = f"主表常住人口为{stated_population}人，{source_label}合计{total_population}人；本次以可核验的{source_label}为准。"
        notes.append(message)
        warnings.append(message)
    if missing_age:
        warnings.append(f"人口明细中有{missing_age}条记录缺少有效年龄，未纳入预测人口。")
    if unknown_gender:
        warnings.append(f"人口明细中有{unknown_gender}条记录性别为空或无法识别，已记为未知；不影响按年龄预测。")

    facilities = {
        "助餐设施": {"社区食堂建筑面积（平方米）": _survey_number(meal, "建筑面积")},
        "养老设施": {"老年服务站容纳量（人）": _survey_number(elderly, "容纳量"), "老年服务站建筑面积（平方米）": _survey_number(elderly, "建筑面积")},
        "托育设施": {
            "现有托儿所建筑面积（平方米）": _survey_number(nursery, "建筑面积"),
            "现有托儿所托育人数（人）": _survey_number(nursery, "托育人数"),
            "现有幼儿园建筑面积（平方米）": _survey_number(kindergarten, "建筑面积"),
            "现有幼儿园用地面积（平方米）": _survey_number(kindergarten, "用地面积"),
            "现有幼儿园托育人数（人）": _survey_number(kindergarten, "托育人数"),
        },
        "停车充电设施": {"停车位数量（个）": _survey_number(parking, "机动车停车位数量"), "机动车充电桩数量（个）": _survey_number(parking, "机动车充电桩")},
        "公共活动场地": {"公共活动场地面积（平方米）": public_area, "多功能运动场地面积（平方米）": sports_area},
        "机动车充电桩列表": _survey_chargers(workbook),
        "_dataNotes": notes,
        "_surveySummary": {
            "社区所属区县及街道": main.get("社区所属区（县）及街道"), "社区建成年代": main.get("社区建成年代"),
            "社区占地面积（公顷）": main.get("社区占地面积（单位：公顷）"), "试点属性": main.get("试点属性"),
            "所辖小区数量": main.get("社区所辖小区数量（单位：个）"), "所辖小区名称": main.get("社区所辖小区名称"),
        },
    }
    return {
        "code": code, "name": name, "region": clean_text(main.get("省级行政区")) or "全国", "households": households,
        "average_household_size": round(total_population / households, 4), "migration_rates": dict(DEFAULT_MIGRATION_RATES),
        "migration_rate_unit": "‰", "age_counts": age_counts, "population_records": records, "population_base_year": population_base_year,
        "facilities": facilities, "idle_spaces": [], "_import_warnings": warnings,
    }


def validate_community_workbook(path: Path) -> list[dict[str, Any]]:
    """Return user-facing field issues without mutating project data."""
    issues: list[dict[str, Any]] = []

    def add_issue(sheet: str | None, row: int | None, field: str, value: Any, message: str) -> None:
        issues.append({"sheet": sheet, "row": row, "field": field, "value": value, "message": message})

    try:
        workbook = _load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        return [{"sheet": None, "row": None, "field": "文件", "value": None, "message": f"无法读取 Excel：{exc}"}]

    try:
        if _is_community_survey_workbook(workbook):
            try:
                _parse_community_survey_workbook(workbook)
            except (ValueError, TypeError, IndexError) as exc:
                add_issue(SURVEY_MAIN_SHEET, None, "综合调研表", None, str(exc))
            return issues

        required_sheets = ("社区基本信息", "社区人口列表")
        for sheet_name in required_sheets:
            if sheet_name not in workbook.sheetnames:
                add_issue(sheet_name, None, "工作表", None, "缺少必需工作表")

        if "社区基本信息" in workbook.sheetnames:
            try:
                _reject_percentage_cells(workbook, ("社区基本信息",))
            except ValueError as exc:
                add_issue("社区基本信息", None, "净迁入率单元格格式", None, str(exc))
            sheet = workbook["社区基本信息"]
            base_rows: dict[str, tuple[Any, int]] = {}
            for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                key = clean_text(row[0] if row else None)
                if key:
                    base_rows[key] = (row[1] if len(row) > 1 else None, row_number)

            for field in ("社区编号", "社区名称"):
                value, row_number = base_rows.get(field, (None, None))
                cleaned = clean_text(value)
                if not cleaned:
                    add_issue("社区基本信息", row_number, field, value, "必填字段不能为空")
                elif re.search(r'[<>:"/\\|?*]', cleaned):
                    add_issue("社区基本信息", row_number, field, value, "不能包含文件名保留字符")

            numeric_rules = {
                "总户数": (0, True, "应为大于或等于 0 的整数"),
                "预测户均人数（人）": (0, False, "应为大于 0 的数字"),
            }
            for field, (minimum, allow_equal, message) in numeric_rules.items():
                if field not in base_rows or base_rows[field][0] in (None, ""):
                    continue
                value, row_number = base_rows[field]
                try:
                    number = float(value)
                    valid = math.isfinite(number) and (number >= minimum if allow_equal else number > minimum)
                    if field == "总户数":
                        valid = valid and number.is_integer()
                    if not valid:
                        raise ValueError
                except (TypeError, ValueError):
                    add_issue("社区基本信息", row_number, field, value, message)

            for group in AGE_GROUPS:
                fields = _migration_rate_fields(group)
                present = [field for field in fields if field in base_rows and base_rows[field][0] not in (None, "")]
                if len(present) > 1:
                    add_issue("社区基本信息", None, group, None, "同一年龄段不能同时填写百分率和千分率，请保留一项")
                for field in present:
                    value, row_number = base_rows[field]
                    limit = 1000 if "‰" in field else 100
                    try:
                        rate = float(value)
                        if not math.isfinite(rate) or not -limit <= rate <= limit:
                            raise ValueError
                    except (TypeError, ValueError):
                        add_issue("社区基本信息", row_number, field, value, f"应为-{limit}至{limit}之间的有限数字")

        if "社区人口列表" in workbook.sheetnames:
            sheet = workbook["社区人口列表"]
            header_cells = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
            headers = [clean_text(value) for value in header_cells]
            if "年龄" not in headers:
                add_issue("社区人口列表", 1, "年龄", None, "缺少“年龄”列")
            else:
                age_index = headers.index("年龄")
                population_count = 0
                for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                    if not any(value not in (None, "") for value in row):
                        continue
                    age_value = row[age_index] if age_index < len(row) else None
                    try:
                        age = float(age_value)
                        if not age.is_integer() or not 0 <= age <= MAX_AGE:
                            raise ValueError
                        population_count += 1
                    except (TypeError, ValueError):
                        add_issue("社区人口列表", row_number, "年龄", age_value, f"应为 0 至 {MAX_AGE} 的整数")
                if population_count == 0:
                    try:
                        if not sum(_read_age_summary(workbook).values()):
                            add_issue("社区人口列表", None, "人口", None, "至少填写一条有效人口记录或有效年龄汇总")
                    except (ValueError, TypeError, IndexError) as exc:
                        add_issue("人口年龄汇总", None, "人数", None, str(exc))
    finally:
        workbook.close()

    return issues


def parse_community(path: Path) -> dict[str, Any]:
    workbook = _load_workbook(path, data_only=True, read_only=True)
    if _is_community_survey_workbook(workbook):
        try:
            return _parse_community_survey_workbook(workbook)
        finally:
            workbook.close()
    if "社区基本信息" in workbook.sheetnames:
        _reject_percentage_cells(workbook, ("社区基本信息",))
    base = _key_value_sheet(workbook, "社区基本信息")
    code = clean_text(base.get("社区编号"))
    name = clean_text(base.get("社区名称"))
    if not code or not name:
        raise ValueError("社区基本信息缺少社区编号或社区名称")

    migration_rates = dict(DEFAULT_MIGRATION_RATES)
    converted_legacy_rates = False
    from .rate_units import percent_to_permille
    migration_sources: dict[str, str] = {}
    source_by_field: dict[str, str] = {}
    base_sheet = workbook["社区基本信息"]
    for row in base_sheet.iter_rows(min_row=2, values_only=True):
        field = clean_text(row[0] if row else None)
        if field:
            source_by_field[field] = clean_text(row[2] if len(row) > 2 else None)
    for group in AGE_GROUPS:
        fields = _migration_rate_fields(group)
        present = [field for field in fields if base.get(field) not in (None, "")]
        if len(present) > 1:
            raise ValueError(f"{group}净迁入率单位冲突，请只保留千分率或百分率一项")
        if present:
            field = present[0]
            value = base[field]
            if "（%）" in field:
                migration_rates[group] = percent_to_permille(value)
                converted_legacy_rates = True
            else:
                migration_rates[group] = float(value)
            if source_by_field.get(field):
                migration_sources[group] = source_by_field[field]

    facilities: dict[str, Any] = {}
    if "填写说明" in workbook.sheetnames:
        notes = [str(row[1]) for row in workbook["填写说明"].iter_rows(min_row=2, values_only=True) if len(row) > 1 and row[0] == "案例来源" and row[1]]
        if notes:
            facilities["_dataNotes"] = notes
    if converted_legacy_rates:
        facilities.setdefault("_dataNotes", []).append("导入旧版Excel：表头标注%的净迁入率已乘10等价换算为‰；原始上传文件保留。")
    if migration_sources:
        facilities["_migrationRateSources"] = migration_sources
    for sheet_name in ("助餐设施", "养老设施", "托育设施", "停车充电设施", "公共活动场地"):
        if sheet_name in workbook.sheetnames:
            facilities[sheet_name] = _key_value_sheet(workbook, sheet_name)

    if "机动车充电桩列表" in workbook.sheetnames:
        sheet = workbook["机动车充电桩列表"]
        headers = [clean_text(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        facilities["机动车充电桩列表"] = [
            {headers[index]: value for index, value in enumerate(row)}
            for row in sheet.iter_rows(min_row=2, values_only=True)
            if any(value not in (None, "") for value in row)
        ]

    idle_spaces: list[dict[str, Any]] = []
    if "闲置空间列表" in workbook.sheetnames:
        sheet = workbook["闲置空间列表"]
        headers = [clean_text(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0] is None:
                continue
            idle_spaces.append({headers[index]: value for index, value in enumerate(row)})

    age_counts = _age_counts_from_population_sheet(workbook)
    if not sum(age_counts.values()):
        age_counts = _read_age_summary(workbook) or age_counts
    population_sheet = workbook["社区人口列表"]
    headers = [clean_text(value) for value in next(population_sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
    population_records = [{headers[i]: value for i, value in enumerate(row) if i < len(headers) and headers[i]} for row in population_sheet.iter_rows(min_row=2, values_only=True) if any(value not in (None, "") for value in row)]
    base_years = {int(row["出生年份"]) + int(row["年龄"]) for row in population_records if row.get("出生年份") not in (None, "") and row.get("年龄") not in (None, "")}
    if len(base_years) > 1:
        raise ValueError("人口列表出生年份与年龄对应的基准年不一致，请统一后导入")
    population_base_year = next(iter(base_years)) if base_years else int(base.get("人口数据基准年") or 2026)
    for index, row in enumerate(population_records, 1):
        row["序号"] = row.get("序号") or index
        gender = clean_text(row.get("性别"))
        if gender not in ("男", "女", "未知", ""):
            row["原始性别"] = row.get("性别")
        row["性别"] = gender if gender in ("男", "女") else "未知"
        age = population_base_year - int(row["出生年份"]) if row.get("出生年份") not in (None, "") else int(row.get("年龄") or 0)
        age = max(0, min(MAX_AGE, age))
        row["年龄"] = age
        row["出生年份"] = population_base_year - age
    total_population = sum(age_counts.values())
    average_household_size = float(base.get("预测户均人数（人）") or 2.5)
    households = int(base["总户数"]) if base.get("总户数") not in (None, "") else round(total_population / average_household_size)
    result = {
        "code": code,
        "name": name,
        "region": clean_text(base.get("预测参数参考地区")) or "全国",
        "households": households,
        "average_household_size": average_household_size,
        "migration_rates": migration_rates,
        "migration_rate_unit": "‰",
        "age_counts": age_counts,
        "population_records": population_records,
        "population_base_year": population_base_year,
        "facilities": facilities,
        "idle_spaces": idle_spaces,
    }
    workbook.close()
    return result


def result_sheet_title(workbook: Workbook, name: str) -> str:
    base = re.sub(r"[\\/*?:\[\]\x00-\x1f]", "_", name).strip("'") or "社区"
    title = base[:31]
    index = 2
    existing = {value.lower() for value in workbook.sheetnames}
    while title.lower() in existing:
        suffix = f"_{index}"
        title = base[:31 - len(suffix)] + suffix
        index += 1
    return title


def export_population_results(path: Path, results: dict[str, list[dict[str, Any]]]) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, yearly_results in results.items():
        sheet = workbook.create_sheet(title=result_sheet_title(workbook, sheet_name))
        years = [item["year"] for item in yearly_results]
        sheet.append(["年龄段", *years])
        for group in AGE_GROUPS:
            sheet.append([group, *[item["ageGroups"][group] for item in yearly_results]])
        sheet.append(["总人数", *[item["totalPopulation"] for item in yearly_results]])
        sheet.append(["总户数", *[item["households"] for item in yearly_results]])
        sheet.freeze_panes = "B2"
        sheet.column_dimensions["A"].width = 18
        for cell in sheet[1]:
            header_font = copy(cell.font)
            header_font.bold = True
            cell.font = header_font
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def export_facility_results(path: Path, results: dict[str, list[dict[str, Any]]]) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, yearly_results in results.items():
        sheet = workbook.create_sheet(title=result_sheet_title(workbook, sheet_name))
        years = [item["year"] for item in yearly_results]
        sheet.append(["设施类别", "参数项", *years, "参考标准", "参考来源"])
        metric_names = list(dict.fromkeys(key for item in yearly_results for key in item["metrics"]))
        for metric in metric_names:
            category, label = metric.split("/", 1)
            detail = yearly_results[-1].get("references", {}).get(metric, {})
            sheet.append([
                category,
                label,
                *[item["metrics"].get(metric) for item in yearly_results],
                detail.get("standard", ""),
                detail.get("source", ""),
            ])
        suggestions = yearly_results[-1].get("siteSuggestions", {})
        for category, suggestion in suggestions.items():
            suggestion_row = sheet.max_row + 1
            sheet.append([category, "选址建议", suggestion, *[None for _ in years[1:]], "满足预测期末需求", "社区闲置空间数据"])
            sheet.merge_cells(start_row=suggestion_row, start_column=3, end_row=suggestion_row, end_column=2 + len(years))
            sheet.row_dimensions[suggestion_row].height = 48
        sheet.freeze_panes = "C2"
        sheet.sheet_view.showGridLines = False
        sheet.auto_filter.ref = f"A1:{sheet.cell(1, sheet.max_column).column_letter}{sheet.max_row}"
        sheet.column_dimensions["A"].width = 18
        sheet.column_dimensions["B"].width = 42
        for column_index in range(3, 3 + len(years)):
            sheet.column_dimensions[sheet.cell(1, column_index).column_letter].width = 14
        sheet.column_dimensions[sheet.cell(1, 3 + len(years)).column_letter].width = 24
        sheet.column_dimensions[sheet.cell(1, 4 + len(years)).column_letter].width = 34
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="087F83")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.row_dimensions[1].height = 26
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(
                    horizontal="left" if cell.column in {2, 4 + len(years)} else "center",
                    vertical="center",
                    wrap_text=cell.column in {2, 3 + len(years), 4 + len(years)} or cell.row > len(metric_names) + 1,
                )
            if row[0].row % 2 == 0 and row[1].value != "选址建议":
                for cell in row:
                    cell.fill = PatternFill("solid", fgColor="EEF7F9")
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _style_template(workbook: Workbook) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from unicodedata import east_asian_width

    def text_width(value):
        return sum(2 if east_asian_width(c) in "WF" else 1 for c in str(value or ""))

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.sheet_view.showGridLines = False
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="087F83")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for column in sheet.columns:
            letter = column[0].column_letter
            max_length = max((text_width(cell.value) for cell in column if cell.value is not None), default=10)
            sheet.column_dimensions[letter].width = min(max(max_length + 3, 14), 70)
        for row in sheet:
            lines = 1
            for cell in row:
                width = sheet.column_dimensions[cell.column_letter].width
                lines = max(lines, math.ceil(text_width(cell.value) / max(width-2,1)))
                if isinstance(cell.value, str):
                    cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center" if cell.row==1 else "left")
                elif cell.value is not None:
                    cell.alignment = Alignment(vertical="center", horizontal="right")
            sheet.row_dimensions[row[0].row].height = max(22, lines*16+6)


def export_community_template(path, base_year: int = 2026, community=None) -> None:
    """Blank workbook or lossless export of saved community data; accepts BytesIO."""
    data = community or {}
    get = (lambda key, default=None: data.get(key, default)) if isinstance(data, dict) else (lambda key, default=None: getattr(data, key, default))
    populated = bool(community)
    base_year = get("population_base_year") or base_year
    facilities = get("facilities", {}) or {}
    workbook = Workbook()
    instructions = workbook.active
    instructions.title = "填写说明"
    instructions.append(["项目", "说明"])
    instructions.append(["数据范围", "已保存社区数据；未保存的界面修改不包含在本文件中。" if populated else "空白录入模板；请填写社区与人口数据，不能直接用空表预测。"])
    simulated_population = any("非实名模拟人口" in str(note) for note in facilities.get("_dataNotes", []))
    population_note = "出生年份+年龄=人口数据基准年。社区人口列表为按原表年龄段、最高100岁及女性100:男性105.07生成的非实名模拟记录。" if simulated_population else "出生年份+年龄=人口数据基准年。人口明细按保存值导出，未知性别不虚构。"
    instructions.append(["人口数据", population_note])
    instructions.append(["比率单位", "净迁入率使用千分率（‰），输入普通数值：10表示10‰，不要将单元格设为百分比格式；出生率和死亡率也使用‰。旧版标注%的净迁入率导入时乘10换算。"])
    instructions.append(["设施与空间", "空值表示尚未填写，0表示已确认没有；坐标保留原始值，模拟值仅供演示。"])
    instructions.append(["重导入", "相同社区编号会更新社区；请先备份。仅有年龄段汇总时，系统会按段内均匀分布生成非实名人口记录。"])
    for note in facilities.get("_dataNotes", []):
        instructions.append(["案例来源", str(note)])

    base = workbook.create_sheet("社区基本信息")
    base.append(["参数项", "参数", "参考来源"])
    for label, key, default in [("社区编号", "code", ""), ("社区名称", "name", ""), ("预测参数参考地区", "region", "全国"), ("总户数", "households", 0), ("预测户均人数（人）", "average_household_size", 2.5)]:
        base.append([label, get(key, default), ""])
    base.append(["人口数据基准年", base_year, ""])
    migration_sources = facilities.get("_migrationRateSources", {})
    for group in AGE_GROUPS:
        base.append([f"社区{group}常住人口复合年均净迁入率（‰）", get("migration_rates", {}).get(group, 0), migration_sources.get(group, "")])

    def write_rows(name, columns, records):
        sheet = workbook.create_sheet(name)
        extras = list(dict.fromkeys(key for row in records for key in row if key not in columns))
        headers = columns + extras
        sheet.append(headers)
        for row in records:
            sheet.append([row.get(key) for key in headers])
        return sheet

    records = []
    for index, raw in enumerate(get("population_records", []) or [], 1):
        row = dict(raw)
        row.setdefault("序号", index)
        if row.get("出生年份") not in (None, ""):
            row["年龄"] = base_year - int(row["出生年份"])
        elif row.get("年龄") not in (None, ""):
            row["出生年份"] = base_year - int(row["年龄"])
        row.setdefault("性别", "未知")
        records.append(row)
    write_rows("社区人口列表", ["序号", "性别", "出生年份", "年龄"], records)
    if not records and get("age_counts"):
        write_rows("人口年龄汇总", ["年龄或年龄段", "人数"], [{"年龄或年龄段": k, "人数": v} for k, v in get("age_counts").items()])
        instructions.append(["人口明细缺失", "本社区仅保存年龄汇总；导出汇总原值，不生成虚构的性别及居民记录。"])
    facility_sheets = {
        "助餐设施": ["社区食堂建筑面积（平方米）"],
        "养老设施": ["老年服务站容纳量（人）", "老年服务站建筑面积（平方米）"],
        "托育设施": ["现有托儿所建筑面积（平方米）", "现有托儿所托育人数（人）", "现有幼儿园建筑面积（平方米）", "现有幼儿园用地面积（平方米）", "现有幼儿园托育人数（人）"],
        "停车充电设施": ["停车位数量（个）", "机动车充电桩数量（个）"],
        "公共活动场地": ["公共活动场地面积（平方米）", "多功能运动场地面积（平方米）"],
    }
    for name, fields in facility_sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append(["参数项", "现状值"])
        values = facilities.get(name, {})
        for field in dict.fromkeys(fields + list(values)):
            sheet.append([field, values.get(field) if populated else 0])
    chargers = []
    for raw in facilities.get("机动车充电桩列表", []):
        row = dict(raw)
        if "机动车充电桩编号" not in row:
            row["机动车充电桩编号"] = row.pop("充电桩编号", None)
        chargers.append(row)
    write_rows("机动车充电桩列表", ["机动车充电桩编号", "建设年份", "经度", "纬度"], chargers)
    write_rows("闲置空间列表", ["闲置空间编号", "待分配建筑面积（平方米）", "待分配用地面积（平方米）", "经度", "纬度"], get("idle_spaces", []) or [])
    _style_template(workbook)
    for name in ("机动车充电桩列表", "闲置空间列表"):
        sheet = workbook[name]
        for cell in sheet[1]:
            if cell.value in ("经度", "纬度"):
                for row in sheet.iter_rows(min_row=2, min_col=cell.column, max_col=cell.column):
                    row[0].number_format = "0.00000000"
    from openpyxl.styles import Alignment
    instructions.column_dimensions["B"].width = 95
    for row in instructions.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="center")
        instructions.row_dimensions[row[0].row].height = 34
    # User text must remain literal, never become an Excel formula.
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def export_population_parameters(path: Path, data: dict[str, Any]) -> None:
    workbook = Workbook()
    base = workbook.active
    base.title = "基础参数"
    base.append(["参数项", "参数"])
    base.append(["预测开始年份", data.get("startYear")])
    base.append(["预测时长（年）", data.get("duration")])
    notes = data.get("sourceNotes", {})
    base.append(["出生率参考来源说明", notes.get("birth", "")])
    base.append(["死亡率参考来源说明", notes.get("death", "")])
    base.append(["出生率单位", "‰"])
    base.append(["死亡率单位", "‰"])
    base.append(["填写提示", "填写普通数值，如5表示5‰。不要使用Excel百分比单元格格式。"])

    birth = workbook.create_sheet("出生率")
    birth_rates = data.get("birthRates", {})
    regions = list(birth_rates)
    years = sorted({int(year) for series in birth_rates.values() for year in series})
    birth.append(["年份", *[f"{region}（‰）" for region in regions]])
    for year in years:
        birth.append([year, *[birth_rates.get(region, {}).get(str(year)) for region in regions]])

    death = workbook.create_sheet("死亡率")
    death_rates = data.get("deathRates", {})
    death_groups = next((list(values) for values in death_rates.values() if values), list(MORTALITY_GROUPS))
    death.append(["年份", *[f"{group}死亡率（‰）" for group in death_groups]])
    for year, values in sorted(death_rates.items(), key=lambda item: int(item[0])):
        death.append([int(year), *[values.get(group) for group in death_groups]])
    _style_template(workbook)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def export_facility_parameters(path: Path, data: dict[str, Any]) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet_names = {"meal": "助餐", "elderly": "养老", "childcare": "托育", "parking": "停车充电", "activity": "公共活动场地"}
    references = data.get("references", {})
    for group, definitions in FACILITY_PARAMETER_GROUPS.items():
        sheet = workbook.create_sheet(sheet_names[group])
        sheet.append(["参数项", "参考标准", "参考来源"])
        for label, dotted_path in definitions:
            reference = references.get(dotted_path, {})
            sheet.append([label, _get_nested(data, dotted_path), reference.get("source", "")])
    vehicles = workbook.create_sheet("乘用机动车保有量")
    vehicles.append(["年份", "新能源乘用机动车人均保有量（辆）", "乘用机动车人均保有量（辆）", "参考来源"])
    parking = data.get("parking", {})
    new_energy = parking.get("newEnergyVehiclesPerCapita", {})
    all_vehicles = parking.get("vehiclesPerCapita", {})
    vehicle_sources = data.get("vehicleSources", {})
    years = sorted({int(year) for year in set(new_energy) | set(all_vehicles)})
    for year in years:
        vehicles.append([year, new_energy.get(str(year)), all_vehicles.get(str(year)), vehicle_sources.get(str(year), "")])
    _style_template(workbook)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
