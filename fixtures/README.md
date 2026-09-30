# HealthMesh Daily CSV

HealthMesh phase one accepts UTF-8 CSV files with one row per local calendar day. `date` is required and must use `YYYY-MM-DD`. Every other column is optional; blank cells mean that no observation was recorded.

| Column | Meaning | Unit / values |
| --- | --- | --- |
| `sleep_duration_min` | Total sleep duration | minutes |
| `sleep_efficiency_pct` | Time asleep divided by time in bed | 0–100 percent |
| `deep_sleep_min` | Deep sleep | minutes |
| `rem_sleep_min` | REM sleep | minutes |
| `light_sleep_min` | Light sleep | minutes |
| `hrv_ms` | Heart-rate variability | milliseconds |
| `resting_heart_rate_bpm` | Resting heart rate | beats per minute |
| `respiratory_rate_bpm` | Respiratory rate | breaths per minute |
| `steps` | Daily step count | whole-number steps |
| `active_calories_kcal` | Activity energy | kilocalories |
| `total_calories_burned_kcal` | Total daily expenditure | kilocalories |
| `workout_duration_min` | Recorded workout duration | minutes |
| `training_load` | Source-defined training load | unitless score |
| `calories_consumed_kcal` | Recorded energy intake | kilocalories |
| `protein_g` | Recorded protein | grams |
| `carbohydrates_g` | Recorded carbohydrates | grams |
| `fat_g` | Recorded fat | grams |
| `fiber_g` | Recorded fiber | grams |
| `nutrition_complete` | Whether the full day was logged | `true`, `false`, or blank |
| `weight_lb` | Body weight | pounds |
| `body_fat_pct` | Body-fat percentage | 0–100 percent |

Explicit zeroes are retained. Blank values never delete observations from earlier imports. Re-importing a changed value for the same date updates it without creating a duplicate.

