"""Append per-state wall-clock timings for the HITL engine.

The CSV is written to HITL_TIMING_CSV, or ./hitl_step_timings.csv by default.
"""
import csv
import os
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["timestamp_utc", "state", "next_state", "duration_seconds", "status"]


def record_step(state: str, next_state: str, elapsed_ns: int, status: str) -> None:
    path = Path(os.environ.get("HITL_TIMING_CSV", "hitl_step_timings.csv"))
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "next_state": next_state,
            "duration_seconds": f"{elapsed_ns / 1_000_000_000:.6f}",
            "status": status,
        })
