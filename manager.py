#!/usr/bin/env python3
"""Semi-autonomous coding task manager CLI."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.generate_prompt import generate_prompt
from scripts.project_workspace import (
    PROJECTS_DIR,
    REGISTRY_PATH,
    ROOT,
    ProjectWorkspace,
    create_project_workspace,
    list_project_names,
    load_registry,
    resolve_project_workspace,
    save_registry,
)


VALID_STATUSES = {
    "pending",
    "in_progress",
    "awaiting_approval",
    "completed",
    "blocked",
    "failed",
}

VALID_RESULT_OUTCOMES = {
    "already_exists_verified",
    "implemented",
    "blocked",
    "failed",
}

REQUIRED_RESULT_FIELDS = {
    "task_id",
    "outcome",
    "summary",
    "evidence",
    "tests_run",
    "tests_passed",
    "changed_files",
    "notes",
}


def load_json(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path.name}")
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path.name}: {exc}") from exc


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def parse_env_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = shlex.split(value)
    except ValueError:
        return value.strip("\"'")
    if len(parsed) == 1:
        return parsed[0]
    return value


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    config: dict[str, str] = {}
    managed_keys = [
        "AGENT_COMMAND",
        "AGENT_TIMEOUT_SECONDS",
        "AUTO_COMPLETE_AGENT_SUCCESS",
        "CODEX_COMMAND",
        "PROJECT_ROOT",
        "CODEX_SANDBOX",
        "CODEX_APPROVAL_POLICY",
        "AUTO_COMPLETE_CODEX_SUCCESS",
        "MAX_TASKS_PER_RUN",
        "CODEX_TIMEOUT_SECONDS",
    ]
    for key in managed_keys:
        if key in os.environ:
            config[key] = os.environ[key]

    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = parse_env_value(value)
    return config


def config_bool(config: dict[str, str], key: str, default: bool) -> bool:
    value = config.get(key)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def config_int(config: dict[str, str], key: str, default: int) -> int:
    value = config.get(key)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{key} must be an integer.") from exc


def load_tasks(workspace: ProjectWorkspace) -> list[dict[str, Any]]:
    tasks = load_json(workspace.tasks_path)
    if not isinstance(tasks, list):
        raise SystemExit("tasks.json must contain a JSON array.")
    for task in tasks:
        if not isinstance(task, dict):
            raise SystemExit("Each task in tasks.json must be an object.")
        status = task.get("status")
        if status not in VALID_STATUSES:
            raise SystemExit(f"Task {task.get('id')} has unsupported status: {status}")
    return tasks


def load_state(workspace: ProjectWorkspace) -> dict[str, Any]:
    state = load_json(workspace.state_path)
    if not isinstance(state, dict):
        raise SystemExit("agent_state.json must contain a JSON object.")
    return state


def find_task(tasks: list[dict[str, Any]], task_id: int | None) -> dict[str, Any] | None:
    if task_id is None:
        return None
    return next((task for task in tasks if task.get("id") == task_id), None)


def dependencies_completed(task: dict[str, Any], tasks: list[dict[str, Any]]) -> bool:
    completed_ids = {item.get("id") for item in tasks if item.get("status") == "completed"}
    return all(dep_id in completed_ids for dep_id in task.get("depends_on", []))


def find_next_ready_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for task in tasks:
        if task.get("status") == "pending" and dependencies_completed(task, tasks):
            return task
    return None


def select_next_ready_task(tasks: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any] | None:
    task = find_next_ready_task(tasks)
    if task:
        task["status"] = "in_progress"
        state["current_task_id"] = task["id"]
        return task
    state["current_task_id"] = None
    return None


def expected_result_path(workspace: ProjectWorkspace, task_id: int) -> Path:
    return (workspace.task_results_dir / f"task_{task_id}_result.json").resolve()


def load_result(path: Path) -> dict[str, Any]:
    result = load_json(path)
    if not isinstance(result, dict):
        raise SystemExit("Result file must contain a JSON object.")
    return result


def validate_result(result: dict[str, Any], current_task_id: int) -> str | None:
    missing_fields = sorted(REQUIRED_RESULT_FIELDS - set(result))
    if missing_fields:
        return f"Result file is missing required field(s): {', '.join(missing_fields)}"

    if result.get("task_id") != current_task_id:
        return f"Result task_id {result.get('task_id')} does not match current task {current_task_id}."

    outcome = result.get("outcome")
    if outcome not in VALID_RESULT_OUTCOMES:
        return f"Unsupported result outcome: {outcome}"

    list_fields = ["evidence", "tests_run", "changed_files"]
    for field in list_fields:
        if not isinstance(result.get(field), list):
            return f"Result field `{field}` must be a list."

    if not isinstance(result.get("tests_passed"), bool):
        return "Result field `tests_passed` must be true or false."

    return None


def attach_result_to_task(task: dict[str, Any], result: dict[str, Any]) -> None:
    task["last_result"] = {
        "outcome": result["outcome"],
        "summary": result["summary"],
        "evidence": result["evidence"],
        "tests_run": result["tests_run"],
        "tests_passed": result["tests_passed"],
        "changed_files": result["changed_files"],
        "notes": result["notes"],
    }


def apply_result_to_state(
    workspace: ProjectWorkspace,
    tasks: list[dict[str, Any]],
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    *,
    auto_complete_implemented: bool,
    agent_exit_code: int | None = None,
) -> str:
    attach_result_to_task(task, result)
    if agent_exit_code is not None:
        task["last_agent_exit_code"] = agent_exit_code

    outcome = result["outcome"]
    tests_passed = result["tests_passed"]

    if outcome in {"already_exists_verified", "implemented"} and not tests_passed:
        task["status"] = "failed"
        task["completion_type"] = "tests_failed"
        state["current_task_id"] = None
        save_json(workspace.tasks_path, tasks)
        save_json(workspace.state_path, state)
        print(f"Task #{task['id']} marked failed because tests_passed is false.")
        return "failed"

    if outcome == "already_exists_verified":
        task["status"] = "completed"
        task["completion_type"] = "verified_existing"
        state["last_completed_task_id"] = task["id"]
        next_task = select_next_ready_task(tasks, state)
        save_json(workspace.tasks_path, tasks)
        save_json(workspace.state_path, state)
        print(f"Task #{task['id']} verified as already existing and marked completed.")
        if next_task:
            print(f"Started next task #{next_task['id']}: {next_task['title']}")
        else:
            print("No next pending task is ready.")
        return "completed"

    if outcome == "implemented":
        if auto_complete_implemented:
            task["status"] = "completed"
            task["completion_type"] = "agent_implemented"
            state["last_completed_task_id"] = task["id"]
            next_task = select_next_ready_task(tasks, state)
            save_json(workspace.tasks_path, tasks)
            save_json(workspace.state_path, state)
            print(f"Task #{task['id']} implemented by the coding agent and marked completed.")
            if next_task:
                print(f"Started next task #{next_task['id']}: {next_task['title']}")
            else:
                print("No next pending task is ready.")
            return "completed"

        task["status"] = "awaiting_approval"
        save_json(workspace.tasks_path, tasks)
        save_json(workspace.state_path, state)
        print(f"Task #{task['id']} marked awaiting_approval.")
        return "awaiting_approval"

    if outcome in {"blocked", "failed"}:
        task["status"] = outcome
        state["current_task_id"] = None
        save_json(workspace.tasks_path, tasks)
        save_json(workspace.state_path, state)
        print(f"Task #{task['id']} marked {outcome}.")
        return outcome

    print(f"Unsupported result outcome: {outcome}")
    return "failed"


def command_status(_: argparse.Namespace) -> int:
    workspace = _.workspace
    tasks = load_tasks(workspace)
    state = load_state(workspace)
    counts = Counter(task["status"] for task in tasks)
    current = find_task(tasks, state.get("current_task_id"))

    print(f"Project: {workspace.name}")
    print("Task status:")
    for status in sorted(VALID_STATUSES):
        print(f"  {status}: {counts.get(status, 0)}")

    if current:
        print(f"\nCurrent task: #{current['id']} - {current['title']} ({current['status']})")
    else:
        print("\nCurrent task: none")

    return 0


def command_next(_: argparse.Namespace) -> int:
    workspace = _.workspace
    tasks = load_tasks(workspace)
    state = load_state(workspace)

    current = find_task(tasks, state.get("current_task_id"))
    if current and current.get("status") in {"in_progress", "awaiting_approval"}:
        print(f"Current task is already active: #{current['id']} - {current['title']}")
        return 0

    task = select_next_ready_task(tasks, state)
    if task:
        save_json(workspace.tasks_path, tasks)
        save_json(workspace.state_path, state)
        print(f"Started task #{task['id']}: {task['title']}")
        return 0

    print("No pending task is ready. Check dependencies or add more tasks.")
    return 1


def command_prompt(_: argparse.Namespace) -> int:
    workspace = _.workspace
    tasks = load_tasks(workspace)
    state = load_state(workspace)
    task = find_task(tasks, state.get("current_task_id"))
    if not task:
        print("No current task. Run `python3 manager.py next` first.")
        return 1
    if task.get("status") not in {"in_progress", "awaiting_approval"}:
        print(f"Current task must be active before prompting. Status: {task.get('status')}")
        return 1

    print(generate_prompt(workspace.root, task))
    return 0


def set_current_status(workspace: ProjectWorkspace, status: str) -> int:
    tasks = load_tasks(workspace)
    state = load_state(workspace)
    task = find_task(tasks, state.get("current_task_id"))
    if not task:
        print("No current task is selected.")
        return 1

    task["status"] = status
    if status == "completed":
        state["last_completed_task_id"] = task["id"]
        state["current_task_id"] = None
    elif status in {"failed", "blocked"}:
        state["current_task_id"] = None

    save_json(workspace.tasks_path, tasks)
    save_json(workspace.state_path, state)
    print(f"Task #{task['id']} marked {status}.")
    return 0


def command_approve(_: argparse.Namespace) -> int:
    workspace = _.workspace
    tasks = load_tasks(workspace)
    state = load_state(workspace)
    task = find_task(tasks, state.get("current_task_id"))
    if not task:
        print("No current task is selected.")
        return 1
    if task.get("status") not in {"in_progress", "awaiting_approval"}:
        print("Only in_progress or awaiting_approval tasks can be approved.")
        return 1
    return set_current_status(workspace, "completed")


def command_fail(_: argparse.Namespace) -> int:
    return set_current_status(_.workspace, "failed")


def command_block(_: argparse.Namespace) -> int:
    return set_current_status(_.workspace, "blocked")


def command_reset_task(args: argparse.Namespace) -> int:
    workspace = args.workspace
    tasks = load_tasks(workspace)
    state = load_state(workspace)
    task = find_task(tasks, args.id)
    if not task:
        print(f"Task not found: {args.id}")
        return 1

    task["status"] = "pending"
    if state.get("current_task_id") == args.id:
        state["current_task_id"] = None

    save_json(workspace.tasks_path, tasks)
    save_json(workspace.state_path, state)
    print(f"Task #{args.id} reset to pending.")
    return 0


def command_import_result(args: argparse.Namespace) -> int:
    workspace = args.workspace
    tasks = load_tasks(workspace)
    state = load_state(workspace)
    task = find_task(tasks, state.get("current_task_id"))
    if not task:
        print("No current task is selected.")
        return 1

    result_path = Path(args.file) if args.file else expected_result_path(workspace, task["id"])
    if not result_path.is_absolute():
        result_path = workspace.root / result_path

    result = load_result(result_path)
    error = validate_result(result, task["id"])
    if error:
        print(f"Result rejected: {error}")
        return 1

    config = load_env()
    status = apply_result_to_state(
        workspace,
        tasks,
        state,
        task,
        result,
        auto_complete_implemented=config_value_bool(
            workspace,
            config,
            "auto_complete_agent_success",
            "AUTO_COMPLETE_AGENT_SUCCESS",
            config_value_bool(workspace, config, "auto_complete_codex_success", "AUTO_COMPLETE_CODEX_SUCCESS", True),
        ),
    )
    return 0 if status in {"completed", "awaiting_approval"} else 1


def get_runner_task(
    workspace: ProjectWorkspace,
    tasks: list[dict[str, Any]],
    state: dict[str, Any],
    *,
    dry_run: bool,
) -> tuple[dict[str, Any] | None, bool]:
    current = find_task(tasks, state.get("current_task_id"))
    if current:
        if current.get("status") != "in_progress":
            print(f"Current task #{current['id']} is {current.get('status')}; automation only runs in_progress tasks.")
            return None, False
        return current, False

    task = find_next_ready_task(tasks)
    if not task:
        print("No pending task is ready.")
        return None, False

    if not dry_run:
        task["status"] = "in_progress"
        state["current_task_id"] = task["id"]
        save_json(workspace.tasks_path, tasks)
        save_json(workspace.state_path, state)
        print(f"Started task #{task['id']}: {task['title']}")
    return task, True


def find_cursor_codex_binary() -> str | None:
    extension_root = Path.home() / ".cursor" / "extensions"
    if not extension_root.exists():
        return None

    candidates = sorted(
        extension_root.glob("openai.chatgpt-*-darwin-arm64/bin/macos-aarch64/codex")
    )
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None
    return str(existing[-1])


def resolve_codex_command(command_parts: list[str]) -> list[str]:
    if not command_parts:
        command_parts = ["codex"]

    executable = command_parts[0]
    has_path_separator = "/" in executable or "\\" in executable

    if has_path_separator:
        if Path(executable).exists():
            return command_parts
        fallback = shutil.which("codex") or find_cursor_codex_binary()
    else:
        fallback = shutil.which(executable)
        if not fallback and executable == "codex":
            fallback = find_cursor_codex_binary()

    if fallback:
        return [fallback, *command_parts[1:]]
    return command_parts


def config_value(
    workspace: ProjectWorkspace,
    config: dict[str, str],
    project_key: str,
    env_key: str,
    default: Any,
) -> Any:
    value = workspace.config.get(project_key)
    if value not in (None, ""):
        return value
    value = config.get(env_key)
    if value not in (None, ""):
        return value
    return default


def config_value_bool(
    workspace: ProjectWorkspace,
    config: dict[str, str],
    project_key: str,
    env_key: str,
    default: bool,
) -> bool:
    value = config_value(workspace, config, project_key, env_key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def format_agent_command(command_template: str, workspace: ProjectWorkspace, project_root: Path) -> list[str]:
    try:
        formatted = command_template.format(
            project_root=str(project_root),
            target_repo=str(project_root),
            workspace=str(workspace.root),
            manager_root=str(ROOT),
        )
    except KeyError as exc:
        raise SystemExit(f"Unknown placeholder in AGENT_COMMAND: {exc}") from exc
    return shlex.split(formatted)


def runner_config(workspace: ProjectWorkspace, config: dict[str, str]) -> tuple[list[str], Path, int]:
    project_root = workspace.target_repo
    if not project_root.exists():
        raise SystemExit(f"PROJECT_ROOT does not exist: {project_root}")

    agent_command = str(config_value(workspace, config, "agent_command", "AGENT_COMMAND", "")).strip()
    if agent_command:
        command = format_agent_command(agent_command, workspace, project_root)
        timeout = int(config_value(workspace, config, "agent_timeout_seconds", "AGENT_TIMEOUT_SECONDS", 1800))
        return command, project_root, timeout

    codex_command = config.get("CODEX_COMMAND", "codex").strip() or "codex"
    command = resolve_codex_command(shlex.split(codex_command))

    command.extend(
        [
            "--sandbox",
            str(config_value(workspace, config, "codex_sandbox", "CODEX_SANDBOX", "workspace-write")),
            "--ask-for-approval",
            str(config_value(workspace, config, "codex_approval_policy", "CODEX_APPROVAL_POLICY", "never")),
            "exec",
            "--skip-git-repo-check",
            "--cd",
            str(project_root),
            "--add-dir",
            str(workspace.root),
            "-",
        ]
    )

    timeout = int(
        config_value(
            workspace,
            config,
            "agent_timeout_seconds",
            "AGENT_TIMEOUT_SECONDS",
            config_value(workspace, config, "codex_timeout_seconds", "CODEX_TIMEOUT_SECONDS", 1800),
        )
    )
    return command, project_root, timeout


def write_log(path: Path, content: str | bytes | None) -> None:
    if content is None:
        content = ""
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    path.write_text(content, encoding="utf-8")


def run_agent(
    workspace: ProjectWorkspace,
    command: list[str],
    prompt: str,
    task_id: int,
    timeout: int,
) -> int:
    workspace.logs_dir.mkdir(exist_ok=True)
    stdout_path = workspace.logs_dir / f"task_{task_id}_agent_stdout.log"
    stderr_path = workspace.logs_dir / f"task_{task_id}_agent_stderr.log"

    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        write_log(stderr_path, f"Agent command not found: {command[0]}\n")
        return 127
    except subprocess.TimeoutExpired as exc:
        write_log(stdout_path, exc.stdout)
        write_log(stderr_path, (exc.stderr or "") + f"\nAgent timed out after {timeout} seconds.\n")
        return 124

    write_log(stdout_path, completed.stdout)
    write_log(stderr_path, completed.stderr)
    return completed.returncode


def command_run_one(args: argparse.Namespace) -> int:
    workspace = args.workspace
    config = load_env()
    command, project_root, timeout = runner_config(workspace, config)
    tasks = load_tasks(workspace)
    state = load_state(workspace)
    task, _ = get_runner_task(workspace, tasks, state, dry_run=args.dry_run)
    if not task:
        return 1

    result_path = expected_result_path(workspace, task["id"])
    prompt = generate_prompt(workspace.root, task)

    if args.dry_run:
        print(f"Task: #{task['id']} - {task['title']}")
        print(f"Project root: {project_root}")
        print(f"Result path: {result_path}")
        print(f"Agent command: {shlex.join(command)}")
        print("Dry run only. The coding agent was not invoked and no state was changed.")
        return 0

    if result_path.exists():
        result_path.unlink()

    print(f"Running coding agent for task #{task['id']}: {task['title']}")
    print(f"Result path: {result_path}")
    exit_code = run_agent(workspace, command, prompt, task["id"], timeout)
    if exit_code != 0:
        print(f"Coding agent exited with code {exit_code}. Checking for a result file anyway.")

    if not result_path.exists():
        print(f"Missing result JSON: {result_path}")
        stdout_log = workspace.logs_dir / f"task_{task['id']}_agent_stdout.log"
        stderr_log = workspace.logs_dir / f"task_{task['id']}_agent_stderr.log"
        print(f"Agent stdout log: {stdout_log}")
        print(f"Agent stderr log: {stderr_log}")
        return 1

    result = load_result(result_path)
    error = validate_result(result, task["id"])
    if error:
        print(f"Result rejected: {error}")
        return 1

    status = apply_result_to_state(
        workspace,
        tasks,
        state,
        task,
        result,
        auto_complete_implemented=config_value_bool(
            workspace,
            config,
            "auto_complete_agent_success",
            "AUTO_COMPLETE_AGENT_SUCCESS",
            config_value_bool(workspace, config, "auto_complete_codex_success", "AUTO_COMPLETE_CODEX_SUCCESS", True),
        ),
        agent_exit_code=exit_code,
    )
    return 0 if status == "completed" else 1


def command_run_loop(args: argparse.Namespace) -> int:
    workspace = args.workspace
    config = load_env()
    default_limit = int(config_value(workspace, config, "max_tasks_per_run", "MAX_TASKS_PER_RUN", 5))
    limit = args.limit if args.limit is not None else default_limit
    if limit < 1:
        print("--limit must be at least 1.")
        return 1

    if args.dry_run:
        args_for_one = argparse.Namespace(dry_run=True, workspace=workspace)
        return command_run_one(args_for_one)

    completed_count = 0
    for _ in range(limit):
        result = command_run_one(argparse.Namespace(dry_run=False, workspace=workspace))
        if result != 0:
            print(f"Run loop stopped after {completed_count} completed task(s).")
            return result

        completed_count += 1
        tasks = load_tasks(workspace)
        state = load_state(workspace)
        current = find_task(tasks, state.get("current_task_id"))
        if not current and not find_next_ready_task(tasks):
            print(f"Run loop finished after {completed_count} task(s). No ready tasks remain.")
            return 0

    print(f"Run loop reached limit of {limit} task(s).")
    return 0


def command_projects_list(_: argparse.Namespace) -> int:
    registry = load_registry()
    active = registry.get("active_project")
    names = list_project_names()
    if not names:
        print("No projects exist.")
        return 0

    for name in names:
        marker = "*" if name == active else " "
        workspace = resolve_project_workspace(name)
        print(f"{marker} {name} -> {workspace.target_repo}")
    return 0


def command_projects_active(_: argparse.Namespace) -> int:
    registry = load_registry()
    active = registry.get("active_project")
    if not active:
        print("No active project is set.")
        return 1
    workspace = resolve_project_workspace(str(active))
    print(f"{workspace.name} -> {workspace.target_repo}")
    return 0


def command_projects_set_active(args: argparse.Namespace) -> int:
    workspace = resolve_project_workspace(args.name)
    registry = load_registry()
    registry["active_project"] = workspace.name
    save_registry(registry)
    print(f"Active project set to {workspace.name}.")
    return 0


def command_projects_create(args: argparse.Namespace) -> int:
    workspace = create_project_workspace(args.name, args.target_repo)
    if args.set_active:
        registry = load_registry()
        registry["active_project"] = workspace.name
        save_registry(registry)
    print(f"Created project {workspace.name} at {workspace.root}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage semi-autonomous coding tasks.")
    parser.add_argument("--project", help="Project name to use. Defaults to projects.json active_project.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    projects_parser = subparsers.add_parser("projects")
    projects_subparsers = projects_parser.add_subparsers(dest="projects_command", required=True)
    projects_subparsers.add_parser("list").set_defaults(func=command_projects_list)
    projects_subparsers.add_parser("active").set_defaults(func=command_projects_active)
    set_active_parser = projects_subparsers.add_parser("set-active")
    set_active_parser.add_argument("name")
    set_active_parser.set_defaults(func=command_projects_set_active)
    create_parser = projects_subparsers.add_parser("create")
    create_parser.add_argument("name")
    create_parser.add_argument("--target-repo", required=True)
    create_parser.add_argument("--set-active", action="store_true")
    create_parser.set_defaults(func=command_projects_create)

    subparsers.add_parser("status").set_defaults(func=command_status)
    subparsers.add_parser("next").set_defaults(func=command_next)
    subparsers.add_parser("prompt").set_defaults(func=command_prompt)
    subparsers.add_parser("approve").set_defaults(func=command_approve)
    subparsers.add_parser("fail").set_defaults(func=command_fail)
    subparsers.add_parser("block").set_defaults(func=command_block)

    run_one_parser = subparsers.add_parser("run-one")
    run_one_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the agent command and selected task without invoking the coding agent or changing state.",
    )
    run_one_parser.set_defaults(func=command_run_one)

    run_loop_parser = subparsers.add_parser("run-loop")
    run_loop_parser.add_argument("--limit", type=int, help="Maximum number of tasks to run.")
    run_loop_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the first agent command without invoking the coding agent or changing state.",
    )
    run_loop_parser.set_defaults(func=command_run_loop)

    import_parser = subparsers.add_parser("import-result")
    import_parser.add_argument(
        "--file",
        help="Path to a coding agent result JSON file. Defaults to task_results/task_<id>_result.json.",
    )
    import_parser.set_defaults(func=command_import_result)

    reset_parser = subparsers.add_parser("reset-task")
    reset_parser.add_argument("--id", type=int, required=True, help="Task ID to reset.")
    reset_parser.set_defaults(func=command_reset_task)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command != "projects":
        args.workspace = resolve_project_workspace(args.project)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
