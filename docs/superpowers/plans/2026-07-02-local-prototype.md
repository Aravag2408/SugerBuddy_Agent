# Local Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
##
**Goal:** Build `local_prototype.py`, a zero-cost, no-cloud script that runs the CGM-event -> questionnaire -> (stubbed) agent-call flow end to end on a laptop, using real RAG text and the real structured investigation table.

**Architecture:** One standalone script plus three small data files. The script calls the existing `AnomalyDetector` against a live test Nightscout site (falling back to a hardcoded anomaly), asks the 9-question Hebrew questionnaire via `input()`, does local keyword-based retrieval against the checked-in RAG text and investigation table (no LLM/embedding calls), prints the exact LLM call it *would* make in the course's required `steps` shape, and saves the full record to a local JSON file.

**Tech Stack:** Python 3, `requests` (already a dependency via `sugarbuddy_anomaly_detector.py`), `openpyxl` (one-off, for the data-generation task only — not a runtime dependency of `local_prototype.py`), stdlib `json`/`pathlib`/`datetime`.

## Global Constraints

- Zero cost: no LLM calls, no embedding calls, no Pinecone/Supabase/network calls other than the Nightscout test site. (Source: `docs/superpowers/specs/2026-07-02-local-prototype-design.md`, and the team's explicit decision to defer LLMod.ai spend.)
- No fabricated medical or investigation content — RAG text and table rows must come from the team's real source files (`American Diabetes Association.docx`, the NIDDK page, `טבלת דאטה.xlsx`), not invented.
- Reuse `Anomaly`, `AnomalyDetector`, `AnomalySeverity`, `AnomalyType`, `SugarBuddyConfig` from `sugarbuddy_anomaly_detector.py` as-is — do not reimplement or modify them.
- The 9 questionnaire questions must match the spec's table verbatim (Hebrew text, exact key names).
- No automated test suite for this script (per spec: it's manual developer scaffolding, not production code). Each task instead has a manual verification step with an exact command and expected output.
- Keep prompt/context content small (course requirement: "minimize prompt/context size") — table matches capped at 3.

---

### Task 1: RAG reference text files

**Files:**
- Create: `data/rag/ada_diabetes_association.txt`
- Create: `data/rag/niddk_hypoglycemia.txt`

**Interfaces:**
- Produces: two UTF-8 text files, each containing a `## HYPERGLYCEMIA` and/or `## HYPOGLYCEMIA` section marker (exact strings, all-caps, two leading `#`) that Task 5 will split on.

- [ ] **Step 1: Write `data/rag/ada_diabetes_association.txt`**

Create the file with exactly this content (real text from the team's "American Diabetes Association.docx", reorganized under two section headers — no facts added or removed):

```
## HYPERGLYCEMIA

American Diabetes Association -- Hyperglycemia (High Blood Glucose)

Hyperglycemia is the technical term for high blood glucose (blood sugar). High blood glucose happens when the body has too little insulin or when the body can't use insulin properly.

What causes hyperglycemia?
A number of things can cause hyperglycemia:
- If you have type 1, you may not have given yourself enough insulin.
- If you have type 2, your body may have enough insulin, but it is not as effective as it should be.
- You ate more than planned or exercised less than planned.
- You have stress from an illness, such as a cold or flu.
- You have other stress, such as family conflicts or school or dating problems.
- You may have experienced the dawn phenomenon (a surge of hormones that the body produces daily around 4:00 a.m. to 5:00 a.m.).

What are the symptoms of hyperglycemia?
The signs and hyperglycemia symptoms include the following: high blood glucose, high levels of glucose in the urine, frequent urination, increased thirst.

How do I treat hyperglycemia?
You can often lower your blood glucose level by exercising. However, if your blood glucose is above 240 mg/dl, check your urine for ketones. If you have ketones, do not exercise -- exercising when ketones are present may make your blood glucose level go even higher. Cutting down on the amount of food you eat might also help. If exercise and changes in diet don't work, your doctor may change the amount of your medication or insulin, or the timing of when you take it.

What if high glucose levels go untreated?
Hyperglycemia can be a serious problem if you don't treat it. If you fail to treat hyperglycemia, a condition called ketoacidosis (diabetic coma) could occur. Ketoacidosis develops when your body doesn't have enough insulin, so it breaks down fats for energy, producing waste products called ketones that build up in the blood. Ketoacidosis is life-threatening and needs immediate treatment. Symptoms include: shortness of breath, breath that smells fruity, nausea and vomiting, very dry mouth.

How can I prevent hyperglycemia?
Your best bet is to practice good diabetes management and learn to detect hyperglycemia so you can treat it early -- before it gets worse.

## HYPOGLYCEMIA

American Diabetes Association -- Hypoglycemia (Low Blood Glucose): Causes and Prevention

What causes low blood glucose?
Hypoglycemia (or low blood glucose) is common for people with type 1 diabetes. It also can occur in people with type 2 diabetes taking insulin or certain diabetes medications.

Common causes of low blood glucose:
- Insulin and similar medications: too much insulin or certain diabetes medications, miscalculating carbs eaten, accidentally injecting the wrong insulin type, injecting directly into the muscle instead of just under the skin.
- What you eat or drink: not eating enough food, eating fewer carbs than planned, skipping a meal or snack, delayed meals, alcohol (especially on an empty stomach) -- alcohol use can cause dangerously low blood glucose, including many hours after use.
- Physical activity: exercise can lower blood glucose and increase insulin sensitivity for hours afterward, including overnight while sleeping.

Can low blood glucose be prevented?
Keep blood glucose in your target range, track personal low-blood-glucose symptoms so you can act faster, and monitor with a glucose meter or CGM. Check more frequently around meals, physical activity, bedtime, and when routines change (new insulin routine, schedule change, travel).

American Diabetes Association -- Signs, Symptoms, and Treatment for Hypoglycemia

What are the signs of low blood glucose (hypoglycemia)?
Signs and symptoms are caused by release of the "fight-or-flight" hormone epinephrine (adrenaline), and can develop quickly: feeling shaky, nervous or anxious, sweating/chills/clamminess, irritability, confusion, fast heartbeat, lightheadedness or dizziness, hunger, nausea, pallor, sleepiness, weakness, blurred vision, tingling or numbness in lips/tongue/cheeks, headaches, coordination problems, and in some cases seizures.

Hypoglycemia unawareness: for most people, symptoms start below 70 mg/dL, but some people can have a low with no symptoms at all ("hypoglycemia unawareness"), which increases risk of severe hypoglycemia, including at night.

How do you treat low blood glucose? The "15-15 Rule":
If blood glucose is 70 mg/dL or below: consume 15 grams of fast-acting carbohydrates, wait 15 minutes, then recheck. If still below 70 mg/dL (or not trending up), have another 15 grams. Once above 70 mg/dL (or trending up) and not eating a meal soon, have a protein+carbohydrate snack to prevent it dropping again. Fast-acting carb examples: glucose tablets, glucose gel, 1/2 cup of juice or regular soda, a tablespoon of sugar/corn syrup/honey, or hard candies/jellybeans (check label for 15g equivalent).
```

- [ ] **Step 2: Write `data/rag/niddk_hypoglycemia.txt`**

Create the file with exactly this content (real text from the NIDDK hypoglycemia page):

```
## HYPOGLYCEMIA (NIDDK)

Low blood glucose, also called low blood sugar or hypoglycemia, occurs when the level of glucose in your blood drops below what is healthy for you. Symptoms develop rapidly and range from mild (shakiness, hunger, dizziness) to severe (loss of consciousness, seizures). Severely low blood glucose can cause serious complications, including passing out, coma, or death.

Causes of low blood glucose:
- Insulin and diabetes medicines (sulfonylureas, meglitinides) that lower glucose levels.
- Insufficient carbohydrate intake or skipped/delayed meals.
- Fasting while taking glucose-lowering medications.
- Increased physical activity (can lower blood glucose for up to 24 hours after).
- Alcohol consumption without adequate food.
- Illness that prevents normal eating.
```

- [ ] **Step 3: Verify both files**

Run: `python -c "from pathlib import Path; a=Path('data/rag/ada_diabetes_association.txt').read_text(encoding='utf-8'); n=Path('data/rag/niddk_hypoglycemia.txt').read_text(encoding='utf-8'); print('## HYPERGLYCEMIA' in a, '## HYPOGLYCEMIA' in a, '## HYPOGLYCEMIA' in n)"`

Expected output: `True True True`

- [ ] **Step 4: Commit**

```bash
git add data/rag/ada_diabetes_association.txt data/rag/niddk_hypoglycemia.txt
git commit -m "Add real RAG reference text (ADA + NIDDK) for the local prototype"
```

---

### Task 2: Structured investigation table JSON

**Files:**
- Create: `data/investigation_table.json`
- Requires: `טבלת דאטה.xlsx` present in the repo root (source file, not committed — team's local working file) and the `openpyxl` package (`pip install openpyxl` if not already available).

**Interfaces:**
- Produces: `data/investigation_table.json` — a JSON array of objects, each `{"state": "היפו"|"היפר", "category": str, "cause": str, "time_to_effect": str, "explanation": str}`. Task 5 reads this file.

- [ ] **Step 1: Run the extraction script**

Run this exact command (adjust the xlsx filename if it differs) from the repo root:

```bash
python -c "
import json
import openpyxl

wb = openpyxl.load_workbook('טבלת דאטה.xlsx', data_only=True)
ws = wb.worksheets[0]

records = []
for row in ws.iter_rows(values_only=True):
    state = row[1]
    if state not in ('היפו', 'היפר'):
        continue
    records.append({
        'state': state,
        'category': (row[2] or '').strip(),
        'cause': (row[3] or '').strip(),
        'time_to_effect': (row[4] or '').strip(),
        'explanation': (row[5] or '').strip(),
    })

with open('data/investigation_table.json', 'w', encoding='utf-8') as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

print(f'wrote {len(records)} records')
"
```

Expected output: `wrote 68 records` (48 היפו rows + 20 היפר rows, per the real table's structure: `מצב`/`קטגוריה`/`גורם`/`כמה זמן אחרי האירוע רואים השפעה?`/`איך להסביר לאנשים שלא מבינים?` in columns B-F).

If the count differs, the xlsx has been edited since this plan was written — open `data/investigation_table.json` and sanity-check a few rows against the spreadsheet before continuing; do not silently proceed with an unexpected count.

- [ ] **Step 2: Verify the output**

Run: `python -c "import json; rows = json.load(open('data/investigation_table.json', encoding='utf-8')); print(len(rows)); print(rows[0]); print(rows[-1])"`

Expected: 68, followed by the first record (a `היפו` / `פעילות גופנית` row) and the last record (a `היפר` row).

- [ ] **Step 3: Commit**

```bash
git add data/investigation_table.json
git commit -m "Add structured investigation table data (parsed from טבלת דאטה.xlsx)"
```
.
---

### Task 3: Anomaly retrieval with fallback

**Files:**
- Create: `local_prototype.py`
- Test: manual, via `python -c`

**Interfaces:**
- Consumes: `Anomaly`, `AnomalyDetector`, `AnomalySeverity`, `AnomalyType`, `SugarBuddyConfig` from `sugarbuddy_anomaly_detector.py` (already in the repo root).
- Produces: `FALLBACK_ANOMALY: Anomaly`, `get_anomaly(config: SugarBuddyConfig) -> tuple[Anomaly, str]` (second element is `"live"` or `"fallback"`), `derive_direction(anomaly: Anomaly) -> str | None` (returns `"high"`, `"low"`, or `None`). Tasks 4-6 build on this file.

- [ ] **Step 1: Create `local_prototype.py` with the anomaly-retrieval piece**

```python
"""Local, zero-cost prototype: CGM anomaly -> questionnaire -> agent-call stub."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sugarbuddy_anomaly_detector import (
    Anomaly,
    AnomalyDetector,
    AnomalySeverity,
    AnomalyType,
    SugarBuddyConfig,
)

DATA_DIR = Path(__file__).parent / "data"
NIGHTSCOUT_TEST_URL = "https://ggns2.fly.dev/"

FALLBACK_ANOMALY = Anomaly(
    type=AnomalyType.GLUCOSE_EXTREME,
    severity=AnomalySeverity.WARNING,
    message=(
        "Glucose rose to 260 mg/dL (threshold: 180 mg/dL). "
        "New high — not present in the last two readings."
    ),
    timestamp=datetime.now(timezone.utc),
    details={"sgv": 260, "threshold": 180, "direction": "high"},
)


def get_anomaly(config: SugarBuddyConfig) -> tuple[Anomaly, str]:
    try:
        detector = AnomalyDetector(config)
        anomalies = detector.check_for_anomalies()
    except Exception:
        anomalies = []
    if anomalies:
        return anomalies[0], "live"
    return FALLBACK_ANOMALY, "fallback"


def derive_direction(anomaly: Anomaly) -> str | None:
    if anomaly.type == AnomalyType.GLUCOSE_EXTREME:
        return anomaly.details.get("direction")
    if anomaly.type == AnomalyType.RATE_OF_CHANGE:
        roc = anomaly.details.get("roc_mgdl_per_min", 0)
        return "high" if roc > 0 else "low"
    if anomaly.type == AnomalyType.IOB_CONTEXTUAL:
        return "low"
    return None  # BIG_GAP carries no glucose-direction information
```

- [ ] **Step 2: Manual smoke test — fallback path**

Run: `python -c "
from local_prototype import get_anomaly, derive_direction
from sugarbuddy_anomaly_detector import SugarBuddyConfig
config = SugarBuddyConfig(nightscout_base_url='https://invalid.example.invalid')
anomaly, source = get_anomaly(config)
print(source, anomaly.type.value, derive_direction(anomaly))
"`

Expected output: `fallback glucose_extreme high` (the invalid URL forces the exception path, confirming the fallback and `derive_direction` both work).

- [ ] **Step 3: Manual smoke test — live path**

Run: `python -c "
from local_prototype import get_anomaly, derive_direction, NIGHTSCOUT_TEST_URL
from sugarbuddy_anomaly_detector import SugarBuddyConfig
config = SugarBuddyConfig(nightscout_base_url=NIGHTSCOUT_TEST_URL)
anomaly, source = get_anomaly(config)
print(source, anomaly.type.value, anomaly.severity.value, derive_direction(anomaly))
"`

Expected: prints `live ...` with real values if the test site currently has an anomaly, or `fallback glucose_extreme high` if it doesn't (both are correct — the site's real state at test time isn't controlled by this plan).

- [ ] **Step 4: Commit**

```bash
git add local_prototype.py
git commit -m "Add anomaly retrieval with fallback to local_prototype.py"
```

---

### Task 4: Questionnaire

**Files:**
- Modify: `local_prototype.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `QUESTIONS: list[tuple[str, str]]`, `ask_questionnaire() -> dict` (keys are the 9 question keys plus `"notes"`; question values are `bool`, `notes` is `str`). Task 5 and 6 consume the dict this returns.

- [ ] **Step 1: Append the questionnaire piece to `local_prototype.py`**

```python
QUESTIONS: list[tuple[str, str]] = [
    ("ate_recently", "אכלת משהו בתוך השעתיים האחרונות?"),
    ("carb_count_accurate", "האם הזנת כמות מדוייקת של פחמימות או בערך?"),
    ("exercised_last_4h", "רצת, קפצת, או עשית שיעור ספורט ואימון ב-4 השעות האחרונות?"),
    ("stressed_last_30min", "מישהו הרגיז אותך או שהיית בלחץ גדול בחצי השעה האחרונה?"),
    ("drank_water_today", "שתית לפחות 4 כוסות מים במהלך היום?"),
    ("hot_weather_last_30min", "האם היית בחוץ במזג אוויר חם מאוד בחצי השעה האחרונה?"),
    ("correction_dose_last_3h", "החלפת משאבה או לקחת מנת תיקון (או פחמימות מהירות להיפו) ב-3 השעות האחרונות?"),
    ("phone_sensor_check_last_hour", "האם היית צמודה לטלפון הנייד בשעה האחרונה, והאם בדקת שהחיישן והמשאבה מחוברים חזק לעור?"),
    ("accurate_meals_today", "האם אכלת ארוחות מדוייקות היום?"),
]


def _ask_yes_no(question_text: str) -> bool:
    while True:
        raw = input(f"{question_text} (y/n): ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("Please answer y or n.")


def ask_questionnaire() -> dict:
    answers: dict = {}
    for key, text in QUESTIONS:
        answers[key] = _ask_yes_no(text)
    answers["notes"] = input("Notes (optional, press Enter to skip): ").strip()
    return answers
```

- [ ] **Step 2: Manual smoke test**

Run: `python -c "
from unittest.mock import patch
from local_prototype import ask_questionnaire
with patch('builtins.input', side_effect=['y'] * 9 + ['felt dizzy']):
    print(ask_questionnaire())
"`

Expected output: a dict with all 9 question keys set to `True` and `'notes': 'felt dizzy'`.

- [ ] **Step 3: Manual smoke test — invalid input re-prompts**

Run: `python -c "
from unittest.mock import patch
from local_prototype import ask_questionnaire
with patch('builtins.input', side_effect=['maybe', 'n'] * 9 + ['']):
    result = ask_questionnaire()
    print(all(v is False for k, v in result.items() if k != 'notes'))
"`

Expected output: `True` (confirms an invalid first answer ('maybe') doesn't crash and the re-prompted 'n' is what's recorded).

- [ ] **Step 4: Commit**

```bash
git add local_prototype.py
git commit -m "Add questionnaire step to local_prototype.py"
```

---

### Task 5: Context retrieval (structured table + RAG text)

**Files:**
- Modify: `local_prototype.py`
- Requires: `data/investigation_table.json` (Task 2), `data/rag/ada_diabetes_association.txt` and `data/rag/niddk_hypoglycemia.txt` (Task 1).

**Interfaces:**
- Consumes: `derive_direction(anomaly) -> str | None` (Task 3), `DATA_DIR: Path` (Task 3), the `answers` dict shape from `ask_questionnaire()` (Task 4).
- Produces: `retrieve_context(anomaly: Anomaly, answers: dict) -> dict` returning `{"table_matches": list[dict], "rag_snippet": str}`. Task 6 consumes this return value.

- [ ] **Step 1: Append the retrieval piece to `local_prototype.py`**

```python
KEYWORD_MAP: list[tuple[str, bool, list[str]]] = [
    ("ate_recently", False, ["ארוחות"]),
    ("carb_count_accurate", False, ["פחמימות"]),
    ("exercised_last_4h", True, ["פעילות גופנית"]),
    ("stressed_last_30min", True, ["סטרס", "לחץ"]),
    ("hot_weather_last_30min", True, ["חום", "מזג אוויר"]),
    ("correction_dose_last_3h", True, ["תיקון"]),
    ("phone_sensor_check_last_hour", False, ["טלפון"]),
    ("accurate_meals_today", False, ["ארוחות"]),
]

STATE_BY_DIRECTION = {"high": "היפר", "low": "היפו"}

RAG_FILES: dict[str, list[Path]] = {
    "high": [DATA_DIR / "rag" / "ada_diabetes_association.txt"],
    "low": [
        DATA_DIR / "rag" / "ada_diabetes_association.txt",
        DATA_DIR / "rag" / "niddk_hypoglycemia.txt",
    ],
}


def _load_table() -> list[dict]:
    with open(DATA_DIR / "investigation_table.json", encoding="utf-8") as f:
        return json.load(f)


def _extract_rag_section(text: str, direction: str) -> str:
    marker = "## HYPERGLYCEMIA" if direction == "high" else "## HYPOGLYCEMIA"
    other_marker = "## HYPOGLYCEMIA" if direction == "high" else "## HYPERGLYCEMIA"
    if marker not in text:
        return ""
    section = text.split(marker, 1)[1]
    if other_marker in section:
        section = section.split(other_marker, 1)[0]
    return section.strip()


def retrieve_context(anomaly: Anomaly, answers: dict) -> dict:
    direction = derive_direction(anomaly)
    if direction is None:
        return {"table_matches": [], "rag_snippet": ""}

    state = STATE_BY_DIRECTION[direction]
    table = [row for row in _load_table() if row["state"] == state]

    matches: list[dict] = []
    for key, trigger, keywords in KEYWORD_MAP:
        if answers.get(key) != trigger:
            continue
        for row in table:
            haystack = row["category"] + " " + row["cause"]
            if any(kw in haystack for kw in keywords) and row not in matches:
                matches.append(row)

    matches = matches[:3]

    rag_snippet = ""
    for path in RAG_FILES.get(direction, []):
        text = path.read_text(encoding="utf-8")
        rag_snippet += _extract_rag_section(text, direction) + "\n\n"

    return {"table_matches": matches, "rag_snippet": rag_snippet.strip()}
```

- [ ] **Step 2: Manual smoke test — high/exercise match**

Run: `python -c "
from local_prototype import retrieve_context, FALLBACK_ANOMALY
answers = {'exercised_last_4h': True, 'ate_recently': True, 'carb_count_accurate': True,
           'stressed_last_30min': False, 'drank_water_today': True,
           'hot_weather_last_30min': False, 'correction_dose_last_3h': False,
           'phone_sensor_check_last_hour': True, 'accurate_meals_today': True, 'notes': ''}
ctx = retrieve_context(FALLBACK_ANOMALY, answers)
print(len(ctx['table_matches']))
print(all(m['state'] == 'היפר' for m in ctx['table_matches']))
print('## HYPERGLYCEMIA' not in ctx['rag_snippet'])
print(len(ctx['rag_snippet']) > 0)
"`

Expected output: four lines — a count between 1 and 3, `True`, `True` (the marker itself is stripped out, only the section body remains), `True`.

- [ ] **Step 3: Manual smoke test — BIG_GAP has no direction**

Run: `python -c "
from datetime import datetime, timezone
from local_prototype import retrieve_context
from sugarbuddy_anomaly_detector import Anomaly, AnomalyType, AnomalySeverity
gap = Anomaly(type=AnomalyType.BIG_GAP, severity=AnomalySeverity.URGENT, message='gap',
              timestamp=datetime.now(timezone.utc), details={'gap_minutes': 45})
print(retrieve_context(gap, {'notes': ''}))
"`

Expected output: `{'table_matches': [], 'rag_snippet': ''}`

- [ ] **Step 4: Commit**

```bash
git add local_prototype.py
git commit -m "Add context retrieval (structured table + RAG) to local_prototype.py"
```

---

### Task 6: Agent-call stub, save, and main

**Files:**
- Modify: `local_prototype.py`

**Interfaces:**
- Consumes: `get_anomaly`, `derive_direction` (Task 3), `ask_questionnaire` (Task 4), `retrieve_context` (Task 5).
- Produces: `build_agent_step(anomaly, answers, context) -> dict`, `print_agent_stub(step: dict) -> None`, `save_record(anomaly, source, answers, context, step) -> None`, `main() -> None`. This is the last task — nothing downstream consumes these.

- [ ] **Step 1: Append the stub/save/main piece to `local_prototype.py`**

```python
SYSTEM_PROMPT = (
    "You are a diabetes event investigation assistant for a parent-teen pair. "
    "Given a CGM anomaly, structured yes/no answers, relevant cause table rows, "
    "and medical reference text, return ONLY a JSON object with two keys: "
    "parent_summary (evidence-based possible contributing factors with confidence "
    "levels, for the parent) and teen_guidance (short, concrete, actionable next "
    "steps for the teen). Do not diagnose."
)


def _build_user_prompt(anomaly: Anomaly, answers: dict, context: dict) -> str:
    payload = {
        "anomaly": {
            "type": anomaly.type.value,
            "severity": anomaly.severity.value,
            "message": anomaly.message,
            "timestamp": anomaly.timestamp.isoformat(),
            "details": anomaly.details,
        },
        "questionnaire_answers": answers,
        "candidate_causes": context["table_matches"],
        "reference_text": context["rag_snippet"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_agent_step(anomaly: Anomaly, answers: dict, context: dict) -> dict:
    return {
        "module": "InvestigationAgent",
        "prompt": {
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": _build_user_prompt(anomaly, answers, context),
        },
        "response": None,
    }


def print_agent_stub(step: dict) -> None:
    print("\n=== Agent step (TODO — not calling the LLM yet) ===")
    print(json.dumps(step, ensure_ascii=False, indent=2))


def save_record(anomaly: Anomaly, source: str, answers: dict, context: dict, step: dict) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "anomaly": {
            "type": anomaly.type.value,
            "severity": anomaly.severity.value,
            "message": anomaly.message,
            "details": anomaly.details,
            "source": source,
        },
        "questionnaire": answers,
        "context": context,
        "step": step,
    }
    out_path = Path(__file__).parent / "local_run_output.json"
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved record to {out_path}")


def main() -> None:
    config = SugarBuddyConfig(nightscout_base_url=NIGHTSCOUT_TEST_URL)
    anomaly, source = get_anomaly(config)
    print(f"\nAnomaly ({source}): [{anomaly.severity.value}] {anomaly.message}")

    answers = ask_questionnaire()
    context = retrieve_context(anomaly, answers)
    step = build_agent_step(anomaly, answers, context)

    print_agent_stub(step)
    save_record(anomaly, source, answers, context, step)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual smoke test — non-interactive full pipeline**

Run: `python -c "
from unittest.mock import patch
from local_prototype import get_anomaly, ask_questionnaire, retrieve_context, build_agent_step, save_record, NIGHTSCOUT_TEST_URL
from sugarbuddy_anomaly_detector import SugarBuddyConfig
config = SugarBuddyConfig(nightscout_base_url=NIGHTSCOUT_TEST_URL)
anomaly, source = get_anomaly(config)
with patch('builtins.input', side_effect=['n'] * 9 + ['']):
    answers = ask_questionnaire()
context = retrieve_context(anomaly, answers)
step = build_agent_step(anomaly, answers, context)
save_record(anomaly, source, answers, context, step)
import json
record = json.load(open('local_run_output.json', encoding='utf-8'))
print(record['step']['module'], record['step']['response'], record['anomaly']['source'])
"`

Expected output: `Saved record to <path>\InvestigationAgent None <live or fallback>`.

- [ ] **Step 3: Run the full interactive script once**

Run: `python local_prototype.py` and answer each prompt (any y/n + optional notes). Confirm:
- An anomaly line prints first (`Anomaly (live): ...` or `Anomaly (fallback): ...`).
- All 9 questions are asked in order, in Hebrew, matching the table in Task 4.
- The `=== Agent step ===` block prints valid-looking JSON with a non-null `system_prompt` and `user_prompt`, and `"response": null`.
- `local_run_output.json` is created in the repo root and is valid JSON (`python -c "import json; json.load(open('local_run_output.json', encoding='utf-8'))"` should not raise).

- [ ] **Step 4: Add `local_run_output.json` to `.gitignore`**

This file is a per-run artifact, not source — it shouldn't be committed. Check whether `.gitignore` exists; if not, create it.

```bash
echo "local_run_output.json" >> .gitignore
```

- [ ] **Step 5: Commit**

```bash
git add local_prototype.py .gitignore
git commit -m "Add agent-call stub, record saving, and main() to local_prototype.py"
```
