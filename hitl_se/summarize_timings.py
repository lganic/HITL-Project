"""Print per-state and per-workflow timing summaries from hitl_step_timings.csv."""
import csv
import sys
from collections import defaultdict
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("hitl_step_timings.csv")
if not path.is_file():
    raise SystemExit(f"Timing file not found: {path}")

by_state = defaultdict(lambda: [0, 0.0])
by_workflow = defaultdict(lambda: [0, 0.0])
failed = 0
with path.open(encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        duration = float(row["duration_seconds"])
        state = row["state"]
        workflow = state.split(".", 1)[0]
        by_state[state][0] += 1
        by_state[state][1] += duration
        by_workflow[workflow][0] += 1
        by_workflow[workflow][1] += duration
        failed += row["status"] != "success"

print("STEP TIMINGS (seconds)")
print(f"{'State':<25} {'Runs':>5} {'Total':>12} {'Average':>12}")
for name, (count, total) in sorted(by_state.items()):
    print(f"{name:<25} {count:>5} {total:>12.3f} {total/count:>12.3f}")
print("\nWORKFLOW TOTALS (seconds)")
for name, (count, total) in sorted(by_workflow.items()):
    print(f"{name:<15} {count:>5} {total:>12.3f}")
print(f"\nTotal automated time: {sum(x[1] for x in by_state.values()):.3f} seconds")
print(f"Failed steps recorded: {failed}")
print("Note: Human approval/waiting time and unrecorded gate operations are excluded.")
