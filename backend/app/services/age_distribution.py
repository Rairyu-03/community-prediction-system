from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


MAX_AGE = 100
SIMULATED_SEX_RATIO = 105.07


def parse_age_band(label: str, *, maximum_age: int = MAX_AGE) -> tuple[int, int]:
    """Parse a Chinese age-band label into an inclusive single-age range."""
    normalized = str(label or "").strip().replace(" ", "")
    bounded = re.fullmatch(r"(\d+)(?:岁)?[-—–~～至到](\d+)(?:岁)?", normalized)
    open_ended = re.fullmatch(r"(\d+)(?:岁)?(?:及以上|以上|\+)", normalized)
    younger = re.fullmatch(r"(\d+)(?:岁)?(?:及以下|以下)", normalized)
    if bounded:
        minimum, maximum = map(int, bounded.groups())
    elif open_ended:
        minimum, maximum = int(open_ended.group(1)), maximum_age
    elif younger:
        minimum, maximum = 0, int(younger.group(1))
    else:
        raise ValueError(f"无法识别年龄段：{label}")
    if minimum < 0 or maximum > maximum_age or minimum > maximum:
        raise ValueError(f"年龄段超出0—{maximum_age}岁范围：{label}")
    return minimum, maximum


def validate_age_band_partition(labels: Iterable[str], *, field: str = "年龄段") -> dict[str, tuple[int, int]]:
    """Require labels to cover every single age exactly once."""
    ranges = {str(label): parse_age_band(str(label)) for label in labels}
    if not ranges:
        raise ValueError(f"{field}不能为空")
    owner: list[str | None] = [None] * (MAX_AGE + 1)
    for label, (minimum, maximum) in ranges.items():
        for age in range(minimum, maximum + 1):
            if owner[age] is not None:
                raise ValueError(f"{field}存在重叠：{owner[age]}与{label}")
            owner[age] = label
    missing = [age for age, label in enumerate(owner) if label is None]
    if missing:
        preview = "、".join(map(str, missing[:8])) + ("等" if len(missing) > 8 else "")
        raise ValueError(f"{field}未覆盖年龄：{preview}岁")
    return ranges


def distribute_age_bands_uniformly(bands: Mapping[str, int]) -> dict[str, int]:
    """Expand non-overlapping age bands to single ages while preserving every total."""
    counts = [0] * (MAX_AGE + 1)
    occupied: set[int] = set()
    for label, raw_total in bands.items():
        minimum, maximum = parse_age_band(label)
        ages = list(range(minimum, maximum + 1))
        if occupied.intersection(ages):
            raise ValueError(f"人口年龄段存在重叠：{label}")
        occupied.update(ages)
        total = int(raw_total)
        if total < 0 or total != raw_total:
            raise ValueError(f"{label}人口必须为非负整数")
        base, remainder = divmod(total, len(ages))
        for index, age in enumerate(ages):
            # Spread indivisible remainders across the full band instead of
            # concentrating them at the youngest edge.
            extra = ((index + 1) * remainder // len(ages)) - (index * remainder // len(ages))
            counts[age] = base + extra
    return {str(age): count for age, count in enumerate(counts) if count}


def simulate_population_records(
    single_age_counts: Mapping[str, int],
    base_year: int,
) -> list[dict[str, int | str]]:
    """Create deterministic person rows using a 105.07 male-to-100 female ratio."""
    total = sum(int(value) for value in single_age_counts.values())
    male_count = int(total * SIMULATED_SEX_RATIO / (100 + SIMULATED_SEX_RATIO) + 0.5)
    records: list[dict[str, int | str]] = []
    person_index = 0
    for age in range(MAX_AGE + 1):
        for _ in range(int(single_age_counts.get(str(age), 0))):
            is_male = ((person_index + 1) * male_count // total) > (person_index * male_count // total) if total else False
            records.append({
                "序号": person_index + 1,
                "性别": "男" if is_male else "女",
                "出生年份": base_year - age,
                "年龄": age,
            })
            person_index += 1
    return records
