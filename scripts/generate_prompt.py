#!/usr/bin/env python3
"""Generate a focused coding-agent prompt for the current task."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8")


def generate_prompt(project_root: Path, task: dict[str, Any]) -> str:
    context = read_text(project_root / "PROJECT_CONTEXT.md")
    template = read_text(ROOT / "prompts" / "task_prompt_template.md")
    task_json = json.dumps(task, indent=2)
    result_file = str((project_root / "task_results" / f"task_{task['id']}_result.json").resolve())

    return (
        template.replace("{{PROJECT_CONTEXT}}", context.strip())
        .replace("{{TASK_JSON}}", task_json)
        .replace("{{RESULT_FILE}}", result_file)
        .strip()
    )


def load_current_task(project_root: Path) -> dict[str, Any]:
    tasks_path = project_root / "tasks.json"
    state_path = project_root / "agent_state.json"

    try:
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing required file: {exc.filename}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON: {exc}") from exc

    current_task_id = state.get("current_task_id")
    task = next((item for item in tasks if item.get("id") == current_task_id), None)
    if not task:
        raise SystemExit("No current task found. Run `python3 manager.py next` first.")
    return task


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    task = load_current_task(project_root)
    print(generate_prompt(project_root, task))
    return 0


if __name__ == "__main__":
    sys.exit(main())
