from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path


HEADERS = [
    "date", "sleep_duration_min", "sleep_efficiency_pct", "deep_sleep_min", "rem_sleep_min",
    "light_sleep_min", "hrv_ms", "resting_heart_rate_bpm", "respiratory_rate_bpm", "steps",
    "active_calories_kcal", "total_calories_burned_kcal", "workout_duration_min", "training_load",
    "calories_consumed_kcal", "protein_g", "carbohydrates_g", "fat_g", "fiber_g",
    "nutrition_complete", "weight_lb", "body_fat_pct",
]


def rounded(value: float, digits: int = 1) -> str:
    return str(round(value, digits))


def main() -> None:
    output = Path(__file__).resolve().parents[2] / "fixtures" / "healthmesh_daily_sample.csv"
    start = date(2026, 1, 1)
    rows: list[dict[str, str]] = []
    for index in range(90):
        day = start + timedelta(days=index)
        weekly = math.sin(index * math.pi / 3.5)
        slower = math.sin(index * math.pi / 15)
        sleep = round(438 + 31 * weekly + 13 * slower)
        deep = round(78 + 8 * slower)
        rem = round(96 + 10 * weekly)
        light = sleep - deep - rem
        workout = 52 if index % 3 == 0 else (32 if index % 5 == 0 else 0)
        steps = round(7600 + 1700 * weekly + workout * 24)
        burned = round(2240 + steps * 0.035 + workout * 4.1)
        intake = round(2310 + 190 * math.sin(index * math.pi / 5) + (120 if index % 7 == 5 else 0))
        protein = round(151 + 15 * math.sin(index * math.pi / 6))
        carbs = round(245 + 26 * math.sin(index * math.pi / 5))
        fat = round(74 + 9 * math.cos(index * math.pi / 7))
        row = {
            "date": day.isoformat(),
            "sleep_duration_min": str(sleep),
            "sleep_efficiency_pct": rounded(87 + 4 * slower),
            "deep_sleep_min": str(deep),
            "rem_sleep_min": str(rem),
            "light_sleep_min": str(light),
            "hrv_ms": rounded(59 + 8 * slower - (6 if sleep < 410 else 0)),
            "resting_heart_rate_bpm": rounded(56 - 3 * slower + (3 if sleep < 410 else 0)),
            "respiratory_rate_bpm": rounded(14.2 + 0.5 * math.cos(index * math.pi / 9)),
            "steps": str(max(1200, steps)),
            "active_calories_kcal": str(round(310 + steps * 0.035 + workout * 2.4)),
            "total_calories_burned_kcal": str(burned),
            "workout_duration_min": str(workout),
            "training_load": str(round(workout * (1.35 + 0.1 * weekly))),
            "calories_consumed_kcal": str(intake),
            "protein_g": str(protein),
            "carbohydrates_g": str(carbs),
            "fat_g": str(fat),
            "fiber_g": str(round(27 + 4 * math.sin(index * math.pi / 8))),
            "nutrition_complete": "false" if index % 9 == 0 else "true",
            "weight_lb": rounded(180.1 - index * 0.043 + 0.7 * slower) if index % 2 == 0 else "",
            "body_fat_pct": rounded(19.2 - index * 0.009 + 0.2 * slower) if index % 7 == 0 else "",
        }
        if index % 17 == 0:
            for key in ["sleep_duration_min", "sleep_efficiency_pct", "deep_sleep_min", "rem_sleep_min", "light_sleep_min"]:
                row[key] = ""
        if index % 13 == 0:
            for key in ["hrv_ms", "resting_heart_rate_bpm", "respiratory_rate_bpm"]:
                row[key] = ""
        if index % 11 == 0:
            for key in ["calories_consumed_kcal", "protein_g", "carbohydrates_g", "fat_g", "fiber_g"]:
                row[key] = ""
            row["nutrition_complete"] = ""
        rows.append(row)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(output)


if __name__ == "__main__":
    main()

