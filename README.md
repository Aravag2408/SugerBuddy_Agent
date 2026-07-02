# SugarBuddy

SugarBuddy is a Parent-Teen Diabetes Investigation Agent. It watches a teen's
live CGM (continuous glucose monitor) data via Nightscout, detects
glucose anomalies, and hands them off to a check-in flow so a parent gets a
clear summary instead of raw sensor noise.

## Pipeline

```
CGM Event -> Structured Questionnaire (8 yes/no + notes) -> ReAct Agent -> Parent Summary
```

## Status

- **Anomaly detection** — built (`sugarbuddy_anomaly_detector.py`). Pulls
  entries/treatments from Nightscout and flags three anomaly classes:
  rate-of-change, sensor gaps, and IOB-contextual risk.
- **Scheduler** — designed, not yet implemented. See
  [docs/superpowers/specs/2026-07-01-anomaly-scheduler-design.md](docs/superpowers/specs/2026-07-01-anomaly-scheduler-design.md)
  for the plan to run detection on a schedule (GitHub Actions -> FastAPI on
  Vercel) with case state persisted in Supabase.
- **Questionnaire UI / ReAct agent** — not yet started.

## Repo layout

- `sugarbuddy_anomaly_detector.py` — `NightscoutClient`, `AnomalyDetector`,
  and `CaseTracker` for the anomaly-detection stage.
- `docs/superpowers/specs/` — design specs for upcoming pipeline stages.
