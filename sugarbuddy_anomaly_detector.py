"""
SugarBuddy — Glucose Anomaly Detection Module
================================================

Pulls live CGM + treatment data from a Nightscout instance and flags
three classes of anomaly for the Check-In Agent to reason over:

  1. RATE_OF_CHANGE  — glucose rising/falling too fast (sustained, not a blip)
  2. BIG_GAP         — sensor dropout / missing data beyond a real "gap"
                        threshold (normal 5-min jitter is ignored)
  3. IOB_CONTEXTUAL  — glucose level considered alongside Insulin-on-Board,
                        e.g. a "fine" glucose value that is actually risky
                        because there's a lot of active insulin still working

Design notes
------------
- Nightscout's own `entries.json` gives raw SGV values; it does NOT give
  IOB unless the site is fed by a looping system's devicestatus (rare for
  a plain Nightscout+Dexcom/Libre setup). So IOB is computed locally from
  `treatments.json` bolus history using a standard exponential insulin
  activity curve (same family of model used by OpenAPS/Loop).
- This module is transport-agnostic: `NightscoutClient` does the HTTP
  calls, `AnomalyDetector` is pure logic and easily unit-testable.
- Intended to be wrapped as a tool the ReAct Check-In Agent calls, e.g.
  `check_for_anomalies() -> list[Anomaly]`.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class SugarBuddyConfig:
    nightscout_base_url: str  # e.g. "https://your-site.herokuapp.com"
    api_token: Optional[str] = None       # Nightscout access token, if required
    api_secret_hash: Optional[str] = None  # SHA1 of admin password, if using legacy auth

    # --- Rate of change thresholds ---
    roc_mgdl_per_min_warn: float = 2.0     # mg/dL per minute sustained -> WARNING
    roc_mgdl_per_min_urgent: float = 3.0   # mg/dL per minute sustained -> URGENT
    roc_window_minutes: int = 15           # look-back window for trend calc

    # --- Gap detection (deliberately generous, per your call: only BIG gaps) ---
    expected_reading_interval_min: int = 5
    big_gap_threshold_min: int = 30        # >30 min with no new reading = anomaly

    # --- IOB model (exponential activity curve) ---
    dia_minutes: int = 300                 # Duration of Insulin Action, default 5h
    peak_minutes: int = 75                 # time-to-peak activity, typical rapid-acting

    # --- IOB-contextual risk thresholds ---
    iob_high_units: float = 3.0            # "a lot" of active insulin
    low_glucose_with_iob_threshold: float = 100.0  # below this + high IOB = risky
    falling_with_iob_roc: float = 1.0      # mg/dL/min falling + high IOB = risky
    devicestatus_max_staleness_min: int = 15  # if loop's own IOB is older than this, fall back to manual calc
    predicted_low_threshold: float = 80.0     # flag if loop's own eventualBG prediction dips this low

    # --- Raw glucose extremes (edge-triggered: only fires on NEW onset, not while sustained) ---
    glucose_low_threshold: float = 70.0
    glucose_high_threshold: float = 200.0

    # --- Open-case suppression: don't re-trigger the pipeline for an anomaly
    # that's still ongoing. A case closes once it stops appearing for this
    # many consecutive cycles (~5 min apart), i.e. 2 = ~10 min back in range.
    case_resolution_readings: int = 2


class AnomalySeverity(str, Enum):
    WARNING = "warning"
    URGENT = "urgent"


class AnomalyType(str, Enum):
    RATE_OF_CHANGE = "rate_of_change"
    BIG_GAP = "big_gap"
    IOB_CONTEXTUAL = "iob_contextual"
    GLUCOSE_EXTREME = "glucose_extreme"


@dataclass
class Anomaly:
    type: AnomalyType
    severity: AnomalySeverity
    message: str
    timestamp: datetime
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Nightscout client
# ---------------------------------------------------------------------------

class NightscoutClient:
    def __init__(self, config: SugarBuddyConfig):
        self.config = config
        self.session = requests.Session()
        headers = {}
        if config.api_secret_hash:
            headers["api-secret"] = config.api_secret_hash
        self.session.headers.update(headers)

    def _params(self, extra: Optional[dict] = None) -> dict:
        params = dict(extra or {})
        if self.config.api_token:
            params["token"] = self.config.api_token
        return params

    def get_recent_entries(self, count: int = 100) -> list[dict]:
        """Fetch the most recent SGV (glucose) entries, newest first."""
        url = f"{self.config.nightscout_base_url.rstrip('/')}/api/v1/entries.json"
        resp = self.session.get(url, params=self._params({"count": count}), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_recent_treatments(self, hours: int = 8) -> list[dict]:
        """Fetch recent treatments (boluses, carbs) for IOB calculation."""
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        url = f"{self.config.nightscout_base_url.rstrip('/')}/api/v1/treatments.json"
        params = self._params({
            "find[created_at][$gte]": since,
            "count": 200,
        })
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_latest_devicestatus(self, count: int = 1) -> list[dict]:
        """
        Fetch recent devicestatus entries. For closed-loop systems (AndroidAPS/
        oref0, Loop) this carries the algorithm's own IOB, COB, and short-term
        BG prediction — computed with far more nuance (temp basals, autosens,
        carb absorption) than a standalone bolus-decay estimate can achieve.
        """
        url = f"{self.config.nightscout_base_url.rstrip('/')}/api/v1/devicestatus.json"
        resp = self.session.get(url, params=self._params({"count": count}), timeout=10)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Loop snapshot extraction (AndroidAPS/oref0 and iOS Loop schemas)
# ---------------------------------------------------------------------------

@dataclass
class LoopSnapshot:
    iob: float
    cob: float
    eventual_bg: Optional[float]
    timestamp: datetime
    source: str  # "devicestatus" or "computed"


def extract_loop_snapshot(devicestatus_entries: list[dict]) -> Optional[LoopSnapshot]:
    """
    Pull IOB/COB/eventualBG out of the most recent devicestatus entry.
    Tries the AndroidAPS/oref0 schema first (openaps.suggested / .enacted),
    then falls back to the iOS Loop schema (loop.iob / loop.cob), since either
    might show up depending on the uploader. Returns None if nothing usable.
    """
    if not devicestatus_entries:
        return None

    entry = devicestatus_entries[0]

    # --- AndroidAPS / oref0 schema ---
    openaps = entry.get("openaps")
    if openaps:
        snapshot = openaps.get("suggested") or openaps.get("enacted")
        if snapshot and "IOB" in snapshot:
            ts_str = snapshot.get("timestamp") or entry.get("created_at")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)
            return LoopSnapshot(
                iob=float(snapshot.get("IOB", 0.0)),
                cob=float(snapshot.get("COB", 0.0)),
                eventual_bg=snapshot.get("eventualBG"),
                timestamp=ts,
                source="devicestatus",
            )

    # --- iOS Loop schema ---
    loop = entry.get("loop")
    if loop:
        iob_obj = loop.get("iob", {})
        cob_obj = loop.get("cob", {})
        ts_str = loop.get("timestamp") or entry.get("created_at")
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)
        if "iob" in iob_obj:
            return LoopSnapshot(
                iob=float(iob_obj.get("iob", 0.0)),
                cob=float(cob_obj.get("cob", 0.0)),
                eventual_bg=None,
                timestamp=ts,
                source="devicestatus",
            )

    return None


# ---------------------------------------------------------------------------
# IOB calculation (exponential model) — fallback only, used when devicestatus
# is missing or stale
# ---------------------------------------------------------------------------

def _insulin_activity_fraction_remaining(minutes_since_bolus: float, dia: int, peak: int) -> float:
    """
    Fraction of a bolus still active at `minutes_since_bolus`, using the
    exponential insulin activity model (Dragan Maksimovic / oref0 formula).
    Returns 0.0 once past DIA.
    """
    if minutes_since_bolus <= 0:
        return 1.0
    if minutes_since_bolus >= dia:
        return 0.0

    tau = peak * (1 - peak / dia) / (1 - 2 * peak / dia)
    a = 2 * tau / dia
    S = 1 / (1 - a + (1 + a) * math.exp(-dia / tau))

    t = minutes_since_bolus
    iob_fraction = 1 - S * (1 - a) * (
        (t ** 2 / (tau * dia * (1 - a)) - t / tau - 1) * math.exp(-t / tau) + 1
    )
    return max(0.0, min(1.0, iob_fraction))


def compute_iob(treatments: list[dict], dia: int, peak: int, now: Optional[datetime] = None) -> float:
    """Sum remaining IOB across all boluses within the DIA window."""
    now = now or datetime.now(timezone.utc)
    total_iob = 0.0

    for t in treatments:
        insulin = t.get("insulin")
        if not insulin:
            continue  # skip carb-only entries, notes, etc.

        ts_str = t.get("created_at") or t.get("timestamp")
        if not ts_str:
            continue
        try:
            bolus_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        minutes_since = (now - bolus_time).total_seconds() / 60.0
        if minutes_since < 0 or minutes_since >= dia:
            continue

        remaining_fraction = _insulin_activity_fraction_remaining(minutes_since, dia, peak)
        total_iob += insulin * remaining_fraction

    return round(total_iob, 2)


# ---------------------------------------------------------------------------
# Open-case suppression
# ---------------------------------------------------------------------------
#
# Prevents the pipeline (Structured Questionnaire -> ReAct Agent -> ...) from
# re-triggering every ~5 min for what is clearly the *same ongoing* anomaly
# (e.g. a hypo that hasn't resolved yet). A case is keyed by (anomaly type,
# direction) so a low and a high are tracked as distinct cases, and closes
# once the anomaly stops appearing for `case_resolution_readings` consecutive
# cycles — i.e. it isn't just one bounce, glucose has genuinely settled.
#
# This does NOT suppress genuinely new/separate events: once a case closes,
# the next occurrence of that anomaly type opens a fresh case and triggers
# the pipeline again as normal.

@dataclass
class _CaseState:
    opened_at: datetime
    resolved_streak: int = 0


class CaseTracker:
    def __init__(self, resolution_readings_required: int = 2, state_file: Optional[str] = None):
        """
        state_file: path to a JSON file used to persist open-case state across
        restarts. IMPORTANT: this path must point at storage that survives a
        container restart (a mounted persistent volume) — the container's own
        writable layer is typically wiped on redeploy. If None, state is
        in-memory only and will be lost on restart (fine for local testing,
        not for production).
        """
        self.resolution_readings_required = resolution_readings_required
        self.state_file = state_file
        self._open_cases: dict[tuple, _CaseState] = {}
        if state_file:
            self._load()

    @staticmethod
    def _case_key(anomaly: Anomaly) -> tuple:
        # direction (low/high) distinguishes cases where relevant, e.g. GLUCOSE_EXTREME
        direction = anomaly.details.get("direction")
        return (anomaly.type, direction)

    @staticmethod
    def _key_to_str(key: tuple) -> str:
        anomaly_type, direction = key
        return f"{anomaly_type.value}|{direction or ''}"

    @staticmethod
    def _key_from_str(key_str: str) -> tuple:
        type_str, _, direction = key_str.partition("|")
        return (AnomalyType(type_str), direction or None)

    def _load(self) -> None:
        if not os.path.exists(self.state_file):
            return  # first run, nothing to load yet
        try:
            with open(self.state_file, "r") as f:
                raw = json.load(f)
            for key_str, state in raw.items():
                key = self._key_from_str(key_str)
                self._open_cases[key] = _CaseState(
                    opened_at=datetime.fromisoformat(state["opened_at"]),
                    resolved_streak=state["resolved_streak"],
                )
            if self._open_cases:
                print(f"[CaseTracker] restored {len(self._open_cases)} open case(s) from {self.state_file}")
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            print(f"[CaseTracker] could not load state file ({e}); starting with no open cases")

    def _save(self) -> None:
        if not self.state_file:
            return
        raw = {
            self._key_to_str(key): {
                "opened_at": state.opened_at.isoformat(),
                "resolved_streak": state.resolved_streak,
            }
            for key, state in self._open_cases.items()
        }
        # Write to a temp file then rename — rename is atomic on POSIX, so a
        # crash mid-write can never leave a corrupted/partial state file.
        tmp_path = f"{self.state_file}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(raw, f)
        os.replace(tmp_path, self.state_file)

    def filter_new_events(self, anomalies: list[Anomaly]) -> list[Anomaly]:
        """
        Call once per cycle with everything the detector found. Returns only
        the subset that represents a genuinely NEW case opening — i.e. what
        should actually trigger the pipeline. Anomalies belonging to an
        already-open case are suppressed (but still tracked internally).
        """
        active_keys = set()
        new_events: list[Anomaly] = []

        for anomaly in anomalies:
            key = self._case_key(anomaly)
            active_keys.add(key)

            if key not in self._open_cases:
                # First time we've seen this case -> open it, let it through.
                self._open_cases[key] = _CaseState(opened_at=anomaly.timestamp)
                new_events.append(anomaly)
            else:
                # Case already open and still active this cycle -> suppress,
                # and reset the resolution streak since it hasn't resolved.
                self._open_cases[key].resolved_streak = 0

        # Any open case that did NOT show up in this cycle's anomalies is
        # one step closer to being resolved.
        for key in list(self._open_cases.keys()):
            if key not in active_keys:
                self._open_cases[key].resolved_streak += 1
                if self._open_cases[key].resolved_streak >= self.resolution_readings_required:
                    del self._open_cases[key]  # case closed; next occurrence will be treated as new

        self._save()
        return new_events

    def open_case_count(self) -> int:
        return len(self._open_cases)


# ---------------------------------------------------------------------------
# Anomaly detector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    def __init__(self, config: SugarBuddyConfig):
        self.config = config
        self.client = NightscoutClient(config)

    def check_for_anomalies(self) -> list[Anomaly]:
        entries = self.client.get_recent_entries(count=60)
        if not entries:
            return []

        entries = self._normalize_entries(entries)
        anomalies: list[Anomaly] = []

        anomalies += self._check_big_gap(entries)
        anomalies += self._check_rate_of_change(entries)
        anomalies += self._check_iob_contextual(entries)
        anomalies += self._check_glucose_extreme(entries)

        return anomalies

    def get_last_reading(self) -> Optional[dict]:
        """
        Convenience for the pipeline's 'CGM Event' step: returns
        {"sgv": <glucose value>, "time": <datetime>} for the most recent
        reading, or None if no data is available.
        """
        entries = self.client.get_recent_entries(count=1)
        if not entries:
            return None
        normalized = self._normalize_entries(entries)
        return normalized[-1] if normalized else None

    # -- normalization -------------------------------------------------

    @staticmethod
    def _normalize_entries(raw: list[dict]) -> list[dict]:
        """Nightscout entries carry `date` (epoch ms) and `sgv`. Sort ascending by time."""
        cleaned = []
        for e in raw:
            if "sgv" not in e or "date" not in e:
                continue
            cleaned.append({
                "sgv": e["sgv"],
                "time": datetime.fromtimestamp(e["date"] / 1000, tz=timezone.utc),
            })
        cleaned.sort(key=lambda x: x["time"])
        return cleaned

    # -- 1. big gap ------------------------------------------------------

    def _check_big_gap(self, entries: list[dict]) -> list[Anomaly]:
        if not entries:
            return []
        last_reading_time = entries[-1]["time"]
        now = datetime.now(timezone.utc)
        gap_min = (now - last_reading_time).total_seconds() / 60.0

        if gap_min >= self.config.big_gap_threshold_min:
            return [Anomaly(
                type=AnomalyType.BIG_GAP,
                severity=AnomalySeverity.URGENT,
                message=(
                    f"No new CGM reading for {gap_min:.0f} minutes "
                    f"(expected every ~{self.config.expected_reading_interval_min} min). "
                    f"Possible sensor dropout or connectivity issue."
                ),
                timestamp=now,
                details={"gap_minutes": round(gap_min, 1), "last_reading_time": last_reading_time.isoformat()},
            )]
        return []

    # -- 4. raw glucose extreme (edge-triggered) -----------------------

    def _check_glucose_extreme(self, entries: list[dict]) -> list[Anomaly]:
        """
        Simple, insulin-agnostic check: is the current reading dangerously
        low or high, AND is this new (not already true for the last two
        readings)? Edge-triggered on purpose — once a low/high is already
        known, we don't want to re-flag it every 5 minutes while it persists;
        other checks (rate-of-change, IOB-contextual) keep tracking the
        situation as it evolves.
        """
        if not entries:
            return []

        current = entries[-1]
        previous_readings = entries[-3:-1]  # up to 2 readings before current

        def already_flagged(is_extreme) -> bool:
            # If we don't have 2 prior readings yet, treat as new (can't
            # confirm it was already happening) rather than suppress it.
            if len(previous_readings) < 2:
                return False
            return all(is_extreme(e["sgv"]) for e in previous_readings)

        sgv = current["sgv"]

        if sgv <= self.config.glucose_low_threshold:
            is_low = lambda v: v <= self.config.glucose_low_threshold
            if not already_flagged(is_low):
                return [Anomaly(
                    type=AnomalyType.GLUCOSE_EXTREME,
                    severity=AnomalySeverity.URGENT,
                    message=(
                        f"Glucose dropped to {sgv} mg/dL (threshold: {self.config.glucose_low_threshold} mg/dL). "
                        f"New low — not present in the last two readings."
                    ),
                    timestamp=current["time"],
                    details={"sgv": sgv, "threshold": self.config.glucose_low_threshold, "direction": "low"},
                )]

        elif sgv >= self.config.glucose_high_threshold:
            is_high = lambda v: v >= self.config.glucose_high_threshold
            if not already_flagged(is_high):
                return [Anomaly(
                    type=AnomalyType.GLUCOSE_EXTREME,
                    severity=AnomalySeverity.WARNING,
                    message=(
                        f"Glucose rose to {sgv} mg/dL (threshold: {self.config.glucose_high_threshold} mg/dL). "
                        f"New high — not present in the last two readings."
                    ),
                    timestamp=current["time"],
                    details={"sgv": sgv, "threshold": self.config.glucose_high_threshold, "direction": "high"},
                )]

        return []

    # -- 2. rate of change ------------------------------------------------

    def _check_rate_of_change(self, entries: list[dict]) -> list[Anomaly]:
        window = timedelta(minutes=self.config.roc_window_minutes)
        now = entries[-1]["time"]
        window_entries = [e for e in entries if now - e["time"] <= window]

        if len(window_entries) < 2:
            return []

        first, last = window_entries[0], window_entries[-1]
        minutes_elapsed = (last["time"] - first["time"]).total_seconds() / 60.0
        if minutes_elapsed <= 0:
            return []

        roc = (last["sgv"] - first["sgv"]) / minutes_elapsed  # mg/dL per min, signed

        abs_roc = abs(roc)
        if abs_roc < self.config.roc_mgdl_per_min_warn:
            return []

        direction = "rising" if roc > 0 else "falling"
        severity = (
            AnomalySeverity.URGENT
            if abs_roc >= self.config.roc_mgdl_per_min_urgent
            else AnomalySeverity.WARNING
        )

        return [Anomaly(
            type=AnomalyType.RATE_OF_CHANGE,
            severity=severity,
            message=(
                f"Glucose {direction} rapidly: {abs_roc:.1f} mg/dL/min over the last "
                f"{minutes_elapsed:.0f} minutes ({first['sgv']} -> {last['sgv']})."
            ),
            timestamp=last["time"],
            details={"roc_mgdl_per_min": round(roc, 2), "from": first["sgv"], "to": last["sgv"]},
        )]

    # -- 3. IOB-contextual -------------------------------------------------

    def _get_iob_cob(self, current_time: datetime) -> tuple[float, float, Optional[float], str]:
        """
        Returns (iob, cob, eventual_bg, source). Prefers the loop's own
        devicestatus snapshot when it's fresh; falls back to a manual
        bolus-decay estimate (no COB/eventualBG available in that case).
        """
        try:
            devicestatus = self.client.get_latest_devicestatus(count=1)
            snapshot = extract_loop_snapshot(devicestatus)
        except requests.RequestException:
            snapshot = None

        if snapshot:
            staleness_min = (current_time - snapshot.timestamp).total_seconds() / 60.0
            if staleness_min <= self.config.devicestatus_max_staleness_min:
                return snapshot.iob, snapshot.cob, snapshot.eventual_bg, "devicestatus"

        # Fallback: compute from raw treatment history
        treatments = self.client.get_recent_treatments(hours=self.config.dia_minutes // 60 + 1)
        iob = compute_iob(treatments, self.config.dia_minutes, self.config.peak_minutes, now=current_time)
        return iob, 0.0, None, "computed"

    def _check_iob_contextual(self, entries: list[dict]) -> list[Anomaly]:
        current = entries[-1]
        iob, cob, eventual_bg, source = self._get_iob_cob(current["time"])

        anomalies = []
        cob_note = f", {cob:.0f}g carbs still absorbing" if cob > 0 else ", no carbs left to absorb"

        # Case A: glucose looks "acceptable" but a lot of insulin is still active and dropping,
        # with no carbs left in the pipeline to counteract it.
        if iob >= self.config.iob_high_units and current["sgv"] <= self.config.low_glucose_with_iob_threshold:
            anomalies.append(Anomaly(
                type=AnomalyType.IOB_CONTEXTUAL,
                severity=AnomalySeverity.URGENT,
                message=(
                    f"Glucose is {current['sgv']} mg/dL with {iob:.2f}U insulin still active "
                    f"(IOB{cob_note}). High risk of continued drop into hypoglycemia."
                ),
                timestamp=current["time"],
                details={"sgv": current["sgv"], "iob": iob, "cob": cob, "source": source},
            ))
            return anomalies  # avoid double-flagging with case B/C

        # Case B: falling trend combined with high IOB, even if current value looks OK
        window = timedelta(minutes=self.config.roc_window_minutes)
        window_entries = [e for e in entries if current["time"] - e["time"] <= window]
        if len(window_entries) >= 2:
            first = window_entries[0]
            minutes_elapsed = (current["time"] - first["time"]).total_seconds() / 60.0
            if minutes_elapsed > 0:
                roc = (current["sgv"] - first["sgv"]) / minutes_elapsed
                if roc <= -self.config.falling_with_iob_roc and iob >= self.config.iob_high_units:
                    anomalies.append(Anomaly(
                        type=AnomalyType.IOB_CONTEXTUAL,
                        severity=AnomalySeverity.WARNING,
                        message=(
                            f"Glucose falling ({roc:.1f} mg/dL/min) with {iob:.2f}U IOB still active"
                            f"{cob_note}. Current value {current['sgv']} mg/dL may drop further."
                        ),
                        timestamp=current["time"],
                        details={"sgv": current["sgv"], "iob": iob, "cob": cob, "roc_mgdl_per_min": round(roc, 2), "source": source},
                    ))
                    return anomalies

        # Case C: the loop's own short-term prediction sees a low coming, even though
        # current glucose and trend look fine right now. Only available when reading
        # real devicestatus (oref0 predicts using autosens/COB, not something we can
        # replicate from raw treatments alone).
        if source == "devicestatus" and eventual_bg is not None and eventual_bg <= self.config.predicted_low_threshold:
            anomalies.append(Anomaly(
                type=AnomalyType.IOB_CONTEXTUAL,
                severity=AnomalySeverity.WARNING,
                message=(
                    f"Current glucose is {current['sgv']} mg/dL, but the loop's own prediction "
                    f"(eventualBG) projects a drop to {eventual_bg:.0f} mg/dL based on {iob:.2f}U "
                    f"IOB{cob_note}."
                ),
                timestamp=current["time"],
                details={"sgv": current["sgv"], "iob": iob, "cob": cob, "eventual_bg": eventual_bg, "source": source},
            ))

        return anomalies


# ---------------------------------------------------------------------------
# Example usage (as a Check-In Agent tool)
# ---------------------------------------------------------------------------

def build_detector_from_env() -> AnomalyDetector:
    """
    Convenience constructor reading config from environment variables,
    for easy wiring into the Docker service:
        NIGHTSCOUT_URL, NIGHTSCOUT_TOKEN
    """
    config = SugarBuddyConfig(
        nightscout_base_url=os.environ["NIGHTSCOUT_URL"],
        api_token=os.environ.get("NIGHTSCOUT_TOKEN"),
    )
    return AnomalyDetector(config)


# ---------------------------------------------------------------------------
# Device-synced polling loop
# ---------------------------------------------------------------------------
#
# Rather than polling on a fixed wall-clock interval (which drifts out of
# sync with when the sensor actually uploads), this looks at the timestamp
# of the most recent reading and schedules the next check for
# (last_reading_time + expected_interval + buffer). If a reading is late,
# it backs off to short retries instead of waiting a full cycle — which also
# feeds naturally into the BIG_GAP anomaly if the sensor really has dropped.

import time as _time  # local import so the module has no hard dependency for library-only use


def run_synced_polling(
    detector: AnomalyDetector,
    on_anomalies=None,
    on_clean_cycle=None,
    on_suppressed=None,
    upload_buffer_seconds: int = 45,
    retry_interval_seconds: int = 30,
    max_retry_wait_minutes: int = 20,
    case_state_file: Optional[str] = None,
) -> None:
    """
    Blocking loop that stays in sync with the CGM's actual upload cadence
    instead of polling on an independent timer.

    Anomalies are passed through a CaseTracker before triggering the
    pipeline: an anomaly belonging to an already-open case (e.g. a hypo
    that's still ongoing) does NOT re-trigger on_anomalies — only genuinely
    new cases do. See CaseTracker for the resolution logic.

    on_anomalies(list[Anomaly])   — called with NEW cases only (this is what should trigger the Structured Questionnaire)
    on_clean_cycle()              — called when a cycle finds nothing at all (optional)
    on_suppressed(list[Anomaly])  — called with anomalies that were detected but belong to an already-open case (optional, useful for logging)
    case_state_file                — path to persist open-case state across restarts. Point this at a
                                      mounted persistent volume in production; leave as None for
                                      quick local testing (state will reset on restart).
    """
    last_processed_reading_time: Optional[datetime] = None
    case_tracker = CaseTracker(
        resolution_readings_required=detector.config.case_resolution_readings,
        state_file=case_state_file,
    )

    while True:
        try:
            raw_entries = detector.client.get_recent_entries(count=1)
            latest = detector._normalize_entries(raw_entries)
            latest_time = latest[-1]["time"] if latest else None
        except requests.RequestException as e:
            print(f"[polling] fetch failed, will retry: {e}")
            latest_time = None

        is_new_reading = latest_time is not None and latest_time != last_processed_reading_time

        if is_new_reading or latest_time is None:
            # Either fresh data arrived, or we genuinely can't reach Nightscout —
            # either way, run the full check (big-gap detection covers the latter).
            all_anomalies = detector.check_for_anomalies()
            last_processed_reading_time = latest_time

            new_events = case_tracker.filter_new_events(all_anomalies)
            suppressed = [a for a in all_anomalies if a not in new_events]

            if new_events:
                if on_anomalies:
                    on_anomalies(new_events)
                else:
                    for a in new_events:
                        print(f"[{a.severity.value.upper()}] {a.type.value}: {a.message}")

            if suppressed:
                if on_suppressed:
                    on_suppressed(suppressed)
                else:
                    for a in suppressed:
                        print(f"[suppressed - open case] {a.type.value}: {a.message}")

            if not all_anomalies:
                if on_clean_cycle:
                    on_clean_cycle()

        # Decide how long to sleep before checking again.
        now = datetime.now(timezone.utc)
        if latest_time is not None:
            expected_next = (
                latest_time
                + timedelta(minutes=detector.config.expected_reading_interval_min)
                + timedelta(seconds=upload_buffer_seconds)
            )
            sleep_seconds = (expected_next - now).total_seconds()
        else:
            sleep_seconds = -1  # force short retry path below

        if sleep_seconds <= 0:
            # Reading is late (or fetch failed) — back off to short retries
            # rather than waiting a full cycle, but don't hammer the server.
            sleep_seconds = retry_interval_seconds

        # Safety net: never sleep so long that a real gap goes unnoticed
        # far past the configured big-gap threshold.
        sleep_seconds = min(sleep_seconds, max_retry_wait_minutes * 60)

        _time.sleep(max(sleep_seconds, 5))


if __name__ == "__main__":
    # One-shot manual test — set NIGHTSCOUT_URL (and NIGHTSCOUT_TOKEN if needed) first:
    #   export NIGHTSCOUT_URL="https://your-site.herokuapp.com"
    #   python sugarbuddy_anomaly_detector.py
    #
    # For continuous, device-synced polling instead of a one-shot check, run:
    #   python -c "from sugarbuddy_anomaly_detector import *; run_synced_polling(build_detector_from_env())"
    detector = build_detector_from_env()
    found = detector.check_for_anomalies()
    if not found:
        print("No anomalies detected.")
    for a in found:
        print(f"[{a.severity.value.upper()}] {a.type.value}: {a.message}")

