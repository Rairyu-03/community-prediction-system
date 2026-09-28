from app.services.prediction_service import normalize_age_counts, round_half_up, summarize_population


def test_round_half_up() -> None:
    assert round_half_up(1.5) == 2
    assert round_half_up(1.49) == 1
    assert round_half_up(-1.5) == -2


def test_normalize_group_counts() -> None:
    counts = normalize_age_counts({"0-3岁": 8, "80岁以上": 41})
    assert sum(counts[0:4]) == 8
    assert sum(counts[80:121]) == 41


def test_summary() -> None:
    counts = [0] * 121
    counts[0] = 10
    counts[65] = 5
    result = summarize_population(2027, counts, 2.5)
    assert result["totalPopulation"] == 15
    assert result["households"] == 6
    assert result["ageGroups"]["0-3岁"] == 10
    assert result["ageGroups"]["60-69岁"] == 5

