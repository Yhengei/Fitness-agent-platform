def weekly_recommendations(
    *,
    pain_days: int,
    adherence_pct: int | None,
    median_rpe: float | None,
    weight_sample_count: int,
    weight_delta_kg: float | None,
) -> list[str]:
    recommendations = []
    if pain_days:
        recommendations.append("本周记录到疼痛，下一次训练先降低负荷或暂停相关动作；持续或异常疼痛应寻求专业评估。")
    if adherence_pct is not None and adherence_pct < 70:
        recommendations.append("本周执行率低于 70%，下周先减少计划总量或训练天数，优先保证可持续完成。")
    elif adherence_pct is not None and adherence_pct >= 85:
        recommendations.append("本周执行稳定，可保持当前训练频率；只有恢复良好时才小幅进阶。")
    if median_rpe is not None and median_rpe >= 9:
        recommendations.append("本周主观强度偏高，下周避免连续高强度训练，并关注睡眠与疲劳变化。")
    if weight_sample_count < 4:
        recommendations.append("体重样本不足，暂不判断减脂趋势；尽量在相近条件下记录至少 4 次。")
    elif weight_delta_kg is not None and weight_delta_kg >= 0:
        recommendations.append("当前体重趋势未下降，先检查一周饮食与日常活动执行，不根据单周数据激进降热量。")
    if not recommendations:
        recommendations.append("本周数据未发现明确调整信号，继续记录训练完成度、RPE、睡眠和体重。")
    return recommendations
