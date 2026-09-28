from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer, model_validator
from .defaults import AGE_GROUPS
from .services.validation_service import finite_number


class ApiModel(BaseModel):
    @field_serializer("*", check_fields=False, when_used="json")
    def serialize_utc(self, value):
        if isinstance(value, datetime):
            return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
        return value


class ProjectCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("工程名称不能为空")
        if any(char in normalized for char in '<>:"/\\|?*'):
            raise ValueError("工程名称不能包含文件系统保留字符")
        return normalized


class ProjectImport(BaseModel):
    source_path: str
    name: str | None = None


class ProjectUpdate(ProjectCreate):
    pass


class ProjectRead(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    path: str
    created_at: datetime
    updated_at: datetime
    is_demo: bool = False


class ParameterUpdate(BaseModel):
    data: dict[str, Any]


class ParameterRead(ApiModel):
    kind: str
    data: dict[str, Any]
    source_file: str | None = None
    updated_at: datetime


class CommunityCreate(ApiModel):
    model_config = ConfigDict(allow_inf_nan=False)
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    region: str = "全国"
    households: int = Field(default=0, ge=0)
    average_household_size: float = Field(default=2.5, gt=0)
    migration_rates: dict[str, float] = Field(default_factory=dict)
    migration_rate_unit: Literal["‰"] = "‰"
    age_counts: dict[str, int] = Field(default_factory=dict)
    population_records: list[dict[str, Any]] = Field(default_factory=list)
    population_base_year: int | None = Field(default=None, ge=1900, le=9900)
    facilities: dict[str, Any] = Field(default_factory=dict)
    idle_spaces: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_population_records(self):
        if not self.population_records:
            return self
        if self.population_base_year is None:
            raise ValueError("填写人口列表时必须设置人口数据基准年")
        counts = {}
        identifiers = set()
        for index, row in enumerate(self.population_records, 1):
            identifier = str(row.get("序号", index)).strip()
            if not identifier or identifier in identifiers:
                raise ValueError(f"人口列表第{index}行序号为空或重复")
            identifiers.add(identifier)
            if row.get("性别", "未知") not in ("男", "女", "未知", "", None):
                raise ValueError(f"人口列表第{index}行性别无效")
            birth = row.get("出生年份")
            if birth not in (None, ""):
                year = finite_number(birth, f"第{index}行出生年份", self.population_base_year - 120, self.population_base_year)
                if not year.is_integer():
                    raise ValueError("出生年份必须为整数")
                age = self.population_base_year - int(year)
            else:
                age = finite_number(row.get("年龄"), f"第{index}行年龄", 0, 120)
                if not float(age).is_integer():
                    raise ValueError("年龄必须为整数")
                age = int(age)
            row["年龄"] = age
            counts[str(age)] = counts.get(str(age), 0) + 1
        self.age_counts = counts
        return self

    @field_validator("code", "name", "region")
    @classmethod
    def trim_text(cls, value: str) -> str:
        cleaned = value.replace("\u200b", "").replace("\u200c", "").strip()
        if not cleaned:
            raise ValueError("不能为空")
        return cleaned

    @field_validator("age_counts")
    @classmethod
    def validate_age_counts(cls, values: dict[str, int]) -> dict[str, int]:
        numeric = [key.isdigit() for key in values]
        if numeric and any(numeric) and not all(numeric):
            raise ValueError("不能混合单岁年龄和年龄段人口")
        for key, count in values.items():
            if key not in AGE_GROUPS and not (key.isdigit() and 0 <= int(key) <= 120):
                raise ValueError(f"未知年龄或年龄段：{key}")
            if count < 0:
                raise ValueError(f"{key}人口不能为负数")
        return values

    @field_validator("migration_rates")
    @classmethod
    def validate_migration(cls, values: dict[str, float]) -> dict[str, float]:
        for group, rate in values.items():
            if group not in AGE_GROUPS:
                raise ValueError(f"未知迁入率年龄段：{group}")
            finite_number(rate, f"{group}净迁入率（‰）", -1000, 1000)
        return values

    @field_validator("idle_spaces")
    @classmethod
    def validate_spaces(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        identifiers = set()
        for space in values:
            identifier = str(space.get("闲置空间编号") or "").strip()
            if not identifier or identifier in identifiers:
                raise ValueError("闲置空间编号不能为空或重复")
            identifiers.add(identifier)
            for field in ("待分配建筑面积（平方米）", "待分配用地面积（平方米）"):
                finite_number(space.get(field) or 0, field)
            for field, limit in (("经度", 180), ("纬度", 90)):
                if space.get(field) not in (None, ""):
                    finite_number(space[field], field, -limit, limit)
        return values

    @field_validator("facilities")
    @classmethod
    def validate_facilities(cls, values: dict[str, Any]) -> dict[str, Any]:
        for category, fields in values.items():
            if category == "机动车充电桩列表":
                if not isinstance(fields, list) or any(not isinstance(row, dict) for row in fields):
                    raise ValueError("机动车充电桩列表格式错误")
                identifiers = set()
                for row in fields:
                    identifier = str(row.get("机动车充电桩编号") or row.get("充电桩编号") or "").strip()
                    if not identifier or identifier in identifiers:
                        raise ValueError("机动车充电桩编号不能为空或重复")
                    identifiers.add(identifier)
                    row["机动车充电桩编号"] = identifier
                    for coord, limit in (("经度", 180), ("纬度", 90)):
                        if row.get(coord) not in (None, ""):
                            finite_number(row[coord], coord, -limit, limit)
                    if row.get("建设年份") not in (None, ""):
                        year = finite_number(row["建设年份"], "充电桩建设年份", 1800, 9999)
                        if not year.is_integer():
                            raise ValueError("充电桩建设年份必须为整数")
            elif category in ("助餐设施", "养老设施", "托育设施", "停车充电设施", "公共活动场地", "公共活动设施"):
                if not isinstance(fields, dict):
                    raise ValueError(f"{category}格式错误")
                for field, value in fields.items():
                    if any(unit in field for unit in ("面积", "数量", "人数", "容纳量")) and value not in (None, ""):
                        finite_number(value, f"{category}/{field}")
        return values


class CommunityRead(CommunityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source_file: str | None = None
    created_at: datetime
    updated_at: datetime


class CommunityImportIssue(BaseModel):
    sheet: str | None = None
    row: int | None = None
    field: str
    value: Any | None = None
    message: str


class CommunityImportReport(BaseModel):
    filename: str
    total_count: int = 1
    success_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    issues: list[CommunityImportIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    community: CommunityRead | None = None


class PredictionRequest(BaseModel):
    seed: int = 20260825


class FacilityPredictionRequest(PredictionRequest):
    population_run_id: int | None = None
    generate_report: bool = False
    report_mode: str = Field(default="community", pattern="^(community|overall)$")
    community_id: int | None = None


class ReportGenerationRequest(BaseModel):
    report_mode: str = Field(default="overall", pattern="^(community|overall)$")
    community_id: int | None = None


class PredictionRunRead(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    kind: str
    status: str
    seed: int
    output_file: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    report_available: bool = False
    project_name: str = ""
    community_names: list[str] = Field(default_factory=list)
    community_ids: list[int] = Field(default_factory=list)
    forecast_years: list[int] = Field(default_factory=list)


class DashboardRead(BaseModel):
    community_count: int
    total_households: int
    total_population: int
    regions: dict[str, int]
