from app.services.age_distribution import distribute_age_bands_uniformly, parse_age_band, simulate_population_records, validate_age_band_partition
from app.services.prediction_service import advance_population, normalize_age_counts, round_half_up, summarize_population


def test_round_half_up() -> None:
    assert round_half_up(1.5) == 2
    assert round_half_up(1.49) == 1
    assert round_half_up(-1.5) == -2


def test_normalize_group_counts() -> None:
    counts = normalize_age_counts({"0-3岁": 8, "80岁以上": 41})
    assert sum(counts[0:4]) == 8
    assert sum(counts[80:101]) == 41


def test_uniform_age_band_expansion_preserves_each_source_band() -> None:
    result = distribute_age_bands_uniformly({"0-6岁": 10, "7-12岁": 14, "80岁以上": 83})
    assert sum(result.get(str(age), 0) for age in range(0, 7)) == 10
    assert sum(result.get(str(age), 0) for age in range(7, 13)) == 14
    assert sum(result.get(str(age), 0) for age in range(80, 101)) == 83
    assert max(result.get(str(age), 0) for age in range(80, 101)) - min(result.get(str(age), 0) for age in range(80, 101)) <= 1


def test_custom_mortality_age_bands_can_cover_single_age_population() -> None:
    assert parse_age_band("65—79岁") == (65, 79)
    groups = ["0-17岁", "18-64岁", "65—79岁", "80岁及以上"]
    assert list(validate_age_band_partition(groups)) == groups


def test_prediction_accepts_custom_mortality_partition() -> None:
    import random

    counts = [1] * 101
    rates = {"0-17岁": 0, "18-64岁": 0, "65—79岁": 0, "80岁及以上": 0}
    advanced = advance_population(counts, births=0, death_rates=rates, rng=random.Random(1))
    assert sum(advanced) == sum(counts)


def test_simulated_population_records_preserve_age_and_gender_totals() -> None:
    age_counts = {"0": 2, "1": 3, "80": 2}
    records = simulate_population_records(age_counts, 2026)
    assert len(records) == 7
    assert sum(row["性别"] == "男" for row in records) == 4
    assert sum(row["性别"] == "女" for row in records) == 3
    assert all(row["出生年份"] + row["年龄"] == 2026 for row in records)
    assert [row["年龄"] for row in records].count(1) == 3


def test_summary() -> None:
    counts = [0] * 101
    counts[0] = 10
    counts[65] = 5
    result = summarize_population(2027, counts, 2.5)
    assert result["totalPopulation"] == 15
    assert result["households"] == 6
    assert result["ageGroups"]["0-3岁"] == 10
    assert result["ageGroups"]["60-69岁"] == 5
