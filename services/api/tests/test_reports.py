from app.reports import weekly_recommendations


def test_weekly_report_prioritizes_pain_and_recovery_signals():
    recommendations = weekly_recommendations(
        pain_days=1,
        adherence_pct=55,
        median_rpe=9,
        weight_sample_count=2,
        weight_delta_kg=None,
    )

    assert "疼痛" in recommendations[0]
    assert any("执行率低于 70%" in item for item in recommendations)
    assert any("主观强度偏高" in item for item in recommendations)
    assert any("体重样本不足" in item for item in recommendations)


def test_weekly_report_does_not_overreact_to_insufficient_weight_samples():
    recommendations = weekly_recommendations(
        pain_days=0,
        adherence_pct=90,
        median_rpe=7,
        weight_sample_count=3,
        weight_delta_kg=None,
    )

    assert any("体重样本不足" in item for item in recommendations)
    assert not any("体重趋势未下降" in item for item in recommendations)
