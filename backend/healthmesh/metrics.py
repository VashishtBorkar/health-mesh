from __future__ import annotations


def metric(
    key: str,
    domain: str,
    label: str,
    unit: str,
    aggregation: str = "mean",
    chart_type: str = "line",
    precision: int = 1,
) -> dict[str, object]:
    return {
        "key": key,
        "domain": domain,
        "label": label,
        "unit": unit,
        "value_type": "number",
        "aggregation": aggregation,
        "display_config": {"chartType": chart_type, "precision": precision},
    }


METRIC_DEFINITIONS = {
    "sleep_duration_min": metric("sleep_duration_min", "sleep", "Sleep duration", "min"),
    "sleep_efficiency_pct": metric("sleep_efficiency_pct", "sleep", "Sleep efficiency", "%"),
    "deep_sleep_min": metric("deep_sleep_min", "sleep", "Deep sleep", "min"),
    "rem_sleep_min": metric("rem_sleep_min", "sleep", "REM sleep", "min"),
    "light_sleep_min": metric("light_sleep_min", "sleep", "Light sleep", "min"),
    "hrv_ms": metric("hrv_ms", "recovery", "Heart-rate variability", "ms"),
    "resting_heart_rate_bpm": metric("resting_heart_rate_bpm", "recovery", "Resting heart rate", "bpm"),
    "respiratory_rate_bpm": metric("respiratory_rate_bpm", "recovery", "Respiratory rate", "breaths/min"),
    "steps": metric("steps", "activity", "Steps", "steps", "sum", "bar", 0),
    "active_calories_kcal": metric("active_calories_kcal", "activity", "Active calories", "kcal", "sum", "bar", 0),
    "total_calories_burned_kcal": metric("total_calories_burned_kcal", "activity", "Total calories burned", "kcal", "sum", "line", 0),
    "workout_duration_min": metric("workout_duration_min", "activity", "Workout duration", "min", "sum", "bar", 0),
    "training_load": metric("training_load", "activity", "Training load", "score", "sum", "bar", 0),
    "calories_consumed_kcal": metric("calories_consumed_kcal", "nutrition", "Recorded calorie intake", "kcal", "sum", "line", 0),
    "protein_g": metric("protein_g", "nutrition", "Protein", "g", "sum", "line", 0),
    "carbohydrates_g": metric("carbohydrates_g", "nutrition", "Carbohydrates", "g", "sum", "line", 0),
    "fat_g": metric("fat_g", "nutrition", "Fat", "g", "sum", "line", 0),
    "fiber_g": metric("fiber_g", "nutrition", "Fiber", "g", "sum", "line", 0),
    "weight_lb": metric("weight_lb", "body", "Weight", "lb"),
    "body_fat_pct": metric("body_fat_pct", "body", "Body fat", "%"),
}

PERCENTAGE_KEYS = {"sleep_efficiency_pct", "body_fat_pct"}
INTEGER_KEYS = {"steps"}
SLEEP_STAGE_KEYS = {"deep_sleep_min", "rem_sleep_min", "light_sleep_min"}

