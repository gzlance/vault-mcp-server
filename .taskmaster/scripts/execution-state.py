#!/usr/bin/env python3
"""Manage execution state for crash recovery."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(".taskmaster/state/execution-state.json")

def load():
    if STATE_FILE.is_file():
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    return {}

def save(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2))

def now_iso():
    return datetime.now(timezone.utc).isoformat()

if len(sys.argv) < 2:
    print("Usage: execution-state.py status|start|complete|checkpoint <args>")
    sys.exit(1)

action = sys.argv[1]

if action == "status":
    state = load()
    if not state:
        print(json.dumps({"has_incomplete": False}))
    else:
        print(json.dumps({
            "has_incomplete": state.get("status") == "in_progress",
            **state,
        }, indent=2))

elif action == "start":
    task_id = sys.argv[2] if len(sys.argv) > 2 else None
    subtask_id = sys.argv[3] if len(sys.argv) > 3 else None
    mode = sys.argv[4] if len(sys.argv) > 4 else "sequential"
    state = load()
    state.update({
        "status": "in_progress",
        "current_task": task_id,
        "current_subtask": subtask_id,
        "mode": mode,
        "last_updated": now_iso(),
    })
    save(state)
    print(json.dumps({"ok": True, "action": "started", **state}))

elif action == "complete":
    task_id = sys.argv[2] if len(sys.argv) > 2 else None
    state = load()
    completed = state.get("completed_tasks", [])
    if task_id and task_id not in completed:
        completed.append(task_id)
    state.update({
        "status": "idle",
        "current_task": None,
        "current_subtask": None,
        "completed_tasks": completed,
        "last_updated": now_iso(),
        "last_checkpoint": task_id,
    })
    save(state)
    print(json.dumps({"ok": True, "action": "completed", **state}))

elif action == "checkpoint":
    task_id = sys.argv[2] if len(sys.argv) > 2 else None
    state = load()
    state["last_checkpoint"] = task_id
    state["last_updated"] = now_iso()
    save(state)
    print(json.dumps({"ok": True, "action": "checkpoint", **state}))

else:
    print(json.dumps({"ok": False, "error": f"Unknown action: {action}"}))
    sys.exit(1)
