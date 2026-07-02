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
