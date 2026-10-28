# HealthMesh Project Context

## Overview

HealthMesh is a local-first, open-source personal health data platform being developed as a Deep Learning semester project and designed with the potential to become a real product.

Its purpose is to bring fragmented health, fitness, nutrition, recovery, and body data into one user-controlled system. The unified data should remain useful through dashboards and traditional analytics even when all AI features are disabled.

## Problem

Personal health data is often split across wearables, workout trackers, calorie-tracking apps, smart scales, and sleep or recovery tools. Each application sees only part of the user's health history, making it difficult to understand relationships across data sources.

HealthMesh aims to answer:

> How can a person's fragmented health, nutrition, fitness, and body data be combined and analyzed in one private system?

## Product Principles

- **Local-first and privacy-conscious:** Sensitive health data should remain under the user's control. Local models and storage are preferred where practical.
- **Data platform first:** Ingestion, normalization, storage, and analytics are the foundation of the product.
- **Useful without AI:** Dashboards, trends, comparisons, and correlations must provide independent value.
- **AI grounded in user data:** Models should query structured data through defined tools rather than receive an unstructured data dump or invent unsupported conclusions.
- **Personalized analysis:** Forecasts and anomalies should be evaluated against the individual's history, not only population-wide thresholds.
- **Not medical advice:** HealthMesh should help users explore their data, not diagnose conditions or replace qualified medical care.

## Core Data Domains

HealthMesh should normalize supported sources into a shared schema covering:

- **Sleep:** duration, efficiency, deep sleep, and REM sleep
- **Recovery and cardiovascular:** heart rate, resting heart rate, HRV, and respiratory rate
- **Activity and training:** steps, active calories, workout duration, exercise type, training volume, and training load
- **Nutrition:** calories, protein, carbohydrates, fat, and potentially fiber and other nutrients
- **Body metrics:** weight, body-fat percentage when available, and rolling weight averages

## Major Components

### 1. Unified Health Dashboard and Analytics

The primary component imports data from multiple sources, converts it into a common format, and stores it locally. Users should be able to explore daily, weekly, and monthly views; moving averages; trends; time-period comparisons; and relationships between metrics.

Example analyses include calorie intake versus weight change, sleep versus workout performance, training volume versus HRV, and sleep duration versus resting heart rate.

### 2. Local LLM Health Coach and Data Analyst

A locally running LLM, potentially served through Ollama, acts as a natural-language interface to the unified health database. It should use narrow, testable tools such as:

- `get_sleep_summary()`
- `get_weight_trend()`
- `get_nutrition_history()`
- `get_workout_history()`
- `get_hrv_trend()`
- `compare_time_periods()`
- `get_calorie_balance()`
- `search_health_history()`
- `get_health_anomalies()`

The assistant should retrieve relevant evidence before explaining changes, trends, or unusual behavior. A later extension may add retrieval over a curated set of trusted health, nutrition, exercise, and recovery resources.

### 3. Temporal Transformer

The main deep learning component is a temporal Transformer trained on multivariate, longitudinal health data. Given a recent window, such as the previous 14 or 30 days, it should learn a representation of the user's current health state and predict future measurements or near-term trends.

Possible prediction targets include next-day HRV, resting heart rate, sleep, body weight, and smoothed weight trend.

The proposed training strategy is:

1. Use self-supervised masked reconstruction to learn relationships among metrics and handle partially observed data.
2. Fine-tune the learned representation for next-step or near-term forecasting.
3. Derive personalized anomaly scores from the difference between predicted and observed measurements.

The learned representation may later support similar-period retrieval, clustering, and health-state embeddings.

## Conceptual Architecture

```text
Health data sources
        |
        v
Ingestion and normalization
        |
        v
Local unified health database
        |
        +--> Dashboard and analytics
        |
        +--> Local LLM agent and query tools
        |
        +--> Temporal Transformer
                 |
                 +--> Forecasts
                 +--> Personalized anomalies
                 +--> Health-state embeddings
```

The LLM should eventually be able to call the forecasting and anomaly systems through tools such as `get_forecast()`, `get_expected_metrics()`, and `find_similar_health_states()`.

## Priority Order

1. Build a reliable unified health data platform.
2. Add a grounded local LLM interface for exploring that data.
3. Develop and evaluate the temporal Transformer as the deep learning research contribution.

## Initial Success Criteria

A successful first version should:

- ingest at least one realistic health-data source and normalize it into an extensible schema;
- store and query the normalized data locally;
- visualize meaningful trends across multiple health domains;
- answer natural-language questions using retrieved data and transparent tool calls;
- train and evaluate a temporal model on clearly defined forecasting tasks;
- produce personalized anomaly scores with an explainable connection to forecast error; and
- clearly document data limitations, privacy assumptions, and the non-medical nature of its output.

## Current Status

The local React/FastAPI dashboard and CSV platform are implemented. Focused Google
Health Takeout and Cronometer Daily Nutrition importers load the user's real
history into a separate personal database. The current priority is a class-demo
study of HRV forecasting using that daily history.

The separate `ml/` workspace provides dataset preparation, chronological
statistical/regression baselines, pretrained Chronos-2, training-only personal
bias correction, and a fixed LoRA fine-tuning experiment. It compares HRV-only,
Fitbit, and Fitbit-plus-nutrition inputs. Anomaly calibration, live forecasting,
and a functional LLM Coach remain future work. See [`ml/README.md`](./ml/README.md) and
[`design_and_implementation_plan.md`](./design_and_implementation_plan.md).

A fixed exploratory diagnostic now compares next-day HRV with the average over
the next three days across three chronological development folds. It includes
stronger mean/median baselines, original-export checks, and forecast plots. The
three-day combined ridge model led development, but calibration and LoRA did not
make Chronos outperform the simple baseline. Ridge was frozen before evaluating
October 8–21 once. It did not beat the baseline on that final test. The holdout
is now consumed; new model tuning needs new independent evaluation data.
The `/modeling` page displays the saved development comparison and final-test
forecasts with limitations. Use `make run-personal` to load the private results.
