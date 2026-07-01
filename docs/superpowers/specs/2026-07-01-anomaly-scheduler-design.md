# Anomaly Scheduler — Design

## Context

SugarBuddy's pipeline (from `Parent-Teen-Diabetes-Investigation-Agent.pptx`):

```
CGM Event -> Structured Questionnaire (8 yes/no + notes) -> ReAct Agent -> Parent Summary
```

The `CGM Event` / anomaly-detection stage is already built (`sugarbuddy_anomaly_detector.py`):
`NightscoutClient`, `AnomalyDetector`, and a `CaseTracker` that suppresses re-triggering
for anomalies that are still ongoing.

This spec covers the next stage only: the **scheduler** that runs the anomaly check on
an interval and hands off newly-opened cases toward the (not-yet-built) questionnaire
step. It does **not** cover the questionnaire UI or the ReAct agent — those are separate,
future specs.

### Why a scheduler is needed at all

`sugarbuddy_anomaly_detector.py` already has `run_synced_polling()` — a blocking
`while True` loop with `time.sleep()`. That works on an always-on machine, but the
course requires deployment on **Vercel**, which is serverless: code only runs in
response to an HTTP request, for at most 300 seconds, with no persistent background
process and no durable local filesystem between invocations. `CaseTracker`'s
JSON-file-based state also can't survive that (each invocation may land on a different
machine with an empty disk).

So "the scheduler" = whatever makes the anomaly check run automatically every few
minutes against a Vercel deployment, plus moving the open/closed case state somewhere
that persists across invocations.

## Decisions made during brainstorming

- **Stack:** Python (FastAPI) on Vercel. The anomaly detector is already Python;
  porting it to Node/Next.js would be pure busywork. Vercel supports Python
  serverless functions natively.
- **Trigger mechanism:** GitHub Actions scheduled workflow, not Vercel Cron. Vercel's
  free/Hobby tier only allows once-per-day cron; sub-daily requires the paid Pro plan.
  A GitHub Actions workflow on a `schedule:` cron pings the endpoint every 5 minutes
  for free, with visible run history in the repo.
- **Case-state persistence:** Supabase (the project's required primary DB) replaces
  the local JSON file `CaseTracker` currently uses.
- **Hand-off to the questionnaire stage:** in-app pull. The scheduler does not push a
  notification anywhere; it only marks a case row as `questionnaire_status = 'pending'`.
  The (future) questionnaire step is responsible for polling/reading that state itself.
- **Scope:** scheduler + persistence + hand-off record only. No questionnaire UI, no
  ReAct agent changes in this spec.

## Architecture

```
GitHub Actions (cron, every 5 min)
        |  POST + secret header
        v
POST /api/cron/check-anomalies   (FastAPI route, deployed on Vercel)
        |
        |-- calls AnomalyDetector.check_for_anomalies() (unchanged, talks to Nightscout)
        |
        |-- diffs the result against open cases in Supabase (anomaly_cases table)
        |     - new case (type+direction not currently open) -> INSERT row,
        |       questionnaire_status = 'pending'  <-- this is what the questionnaire
        |                                              stage will later pick up
        |     - already-open case still present   -> UPDATE last_seen_at, reset
        |                                              resolved_streak to 0
        |     - open case NOT present this cycle   -> resolved_streak += 1;
        |                                              closes (status='closed') once
        |                                              resolved_streak >= 2
        |
        v
returns {"new_cases": N, "still_open": N, "closed": N}
```

## Data model

New Supabase table `anomaly_cases`:

| column | type | notes |
|---|---|---|
| `id` | uuid, pk | `default gen_random_uuid()` |
| `anomaly_type` | text | one of `AnomalyType` values (`rate_of_change`, `big_gap`, `iob_contextual`, `glucose_extreme`) |
| `direction` | text, nullable | `low` / `high` / null — distinguishes concurrent low vs. high cases, mirrors `CaseTracker._case_key` |
| `severity` | text | from `Anomaly.severity` |
| `message` | text | from `Anomaly.message` |
| `details` | jsonb | from `Anomaly.details` |
| `status` | text | `open` \| `closed` |
| `questionnaire_status` | text | `pending` \| `answered` (only `pending` is written by this spec; `answered` is set later by the questionnaire step) |
| `opened_at` | timestamptz | when the case first appeared |
| `last_seen_at` | timestamptz | updated every cycle the case is still active |
| `resolved_streak` | int | consecutive cycles absent; case closes at 2 (same constant as today's `case_resolution_readings`) |
| `created_at` | timestamptz | `default now()` |

Constraint: a **partial unique index** on `(anomaly_type, direction) WHERE status = 'open'`
ensures at most one open case per type+direction, so an accidental double-trigger of the
cron endpoint (GitHub Actions timing isn't perfectly precise) can't create duplicate
"new" cases for the same ongoing event.

## Endpoint behavior

- **Route:** `POST /api/cron/check-anomalies`
- **Auth:** GitHub Actions sends a shared secret in a header (e.g. `x-cron-secret`),
  stored as a GitHub Actions secret and a Vercel environment variable. Request is
  rejected with 401 if the header doesn't match.
- **Body:** none required; it's a trigger, not a data submission.
- **Response:** `{"new_cases": <int>, "still_open": <int>, "closed": <int>}` — visible
  in the GitHub Actions run log for quick sanity-checking without needing to open Supabase.

## Error handling

- **Nightscout unreachable:** already surfaces naturally — the detector's `BIG_GAP`
  check fires once readings stop arriving beyond the threshold. The cron endpoint logs
  the fetch error for that run and exits cleanly without writing partial state.
- **Double-triggering:** handled by the unique partial index described above, not by
  application-level locking.
- **Vercel timeout:** the full cycle (one Nightscout fetch + a handful of Supabase
  reads/writes) takes low single-digit seconds — far under the 300s Vercel limit.

## Testing

- Unit tests for the open/refresh/close transition logic: feed a sequence of fake
  anomaly lists across simulated consecutive runs, assert the right rows get
  inserted/updated/closed (same scenarios `CaseTracker`'s current logic implies, now
  targeting Supabase instead of a JSON file).
- A test that calls the endpoint without the secret header and asserts a 401.
- Manual end-to-end check against the live test Nightscout instance
  (`https://ggns2.fly.dev/`, from `Data Sources.docx`): trigger the endpoint, confirm a
  row appears in `anomaly_cases`.
