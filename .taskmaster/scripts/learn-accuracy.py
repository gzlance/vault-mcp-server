#!/usr/bin/env python3
"""Analyze estimation accuracy from time tracking data."""
import json, sys
from pathlib import Path

STATE_FILE = Path(".taskmaster/state/time-tracking.json")

def main():
    if not STATE_FILE.is_file():
        print(json.dumps({"ok": False, "error": "No time tracking data found"}))
        sys.exit(1)

    data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
    tasks = data.get("tasks", {})

    completed = {k: v for k, v in tasks.items() if v.get("status") == "done" and "duration_minutes" in v}

    if not completed:
        print(json.dumps({"ok": True, "message": "No completed tasks with timing data", "count": 0}))
        return

    durations = [v["duration_minutes"] for v in completed.values()]
    avg_duration = sum(durations) / len(durations)

    print(json.dumps({
        "ok": True,
        "tasks_analyzed": len(completed),
        "average_duration_minutes": round(avg_duration, 1),
        "total_minutes": round(sum(durations), 1),
        "tasks": {k: v.get("duration_minutes") for k, v in completed.items()},
    }, indent=2))

if __name__ == "__main__":
    main()
