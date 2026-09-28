from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from app.defaults import AGE_GROUPS
from app.services.report_service import _population_chart, _population_chart_series


def _rows():
    return [
        SimpleNamespace(
            year=2027 + index,
            data={
                "totalPopulation": 10_000 + index * 120,
                "households": 4_000 + index * 40,
                "ageGroups": {group: 500 + group_index * 60 + index * 5 for group_index, group in enumerate(AGE_GROUPS)},
            },
        )
        for index in range(5)
    ]


def test_population_report_chart_contains_scale_and_all_age_series():
    rows = _rows()
    series = _population_chart_series(rows)

    assert [item["name"] for item in series] == ["总人口", "总户数", *AGE_GROUPS]
    assert [item["unit"] for item in series[:2]] == ["人", "户"]
    assert len(series) == 10
    assert all(len(item["values"]) == len(rows) for item in series)
    assert series[0]["values"] == [10_000, 10_120, 10_240, 10_360, 10_480]
    assert series[1]["values"] == [4_000, 4_040, 4_080, 4_120, 4_160]

    image_stream: BytesIO = _population_chart(rows, SimpleNamespace(code="T-01", name="图表测试社区"))
    with Image.open(image_stream) as image:
        assert image.format == "PNG"
        assert image.size == (1600, 900)
