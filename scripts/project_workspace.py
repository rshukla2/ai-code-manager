"""Project workspace helpers for AI Code Manager."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECTS_DIR = ROOT / "projects"
REGISTRY_PATH = ROOT / "projects.json"

PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class ProjectWorkspace:
    name: str
    root: Path
    config: dict[str, Any]

    @property
    def project_config_path(self) -> Path:
        return self.root / "project.json"

    @property
    def prd_path(self) -> Path:
        return self.root / "prd.md"

    @property
    def agent_prd_path(self) -> Path:
        return self.root / "agent_prd.md"

    @property
    def context_path(self) -> Path:
        return self.root / "PROJECT_CONTEXT.md"

    @property
    def tasks_path(self) -> Path:
        return self.root / "tasks.json"

    @property
    def state_path(self) -> Path:
        return self.root / "agent_state.json"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def task_results_dir(self) -> Path:
        return self.root / "task_results"

    @property
    def target_repo(self) -> Path:
        return Path(str(self.config.get("target_repo", ""))).expanduser().resolve()


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise SystemExit(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def validate_project_name(name: str) -> str:
    normalized = name.strip()
    if not PROJECT_NAME_PATTERN.match(normalized):
        raise SystemExit(
            "Project names must use lowercase letters, numbers, underscores, or hyphens, "
            "and must start with a letter or number."
        )
    return normalized


def load_registry() -> dict[str, Any]:
    return read_json(REGISTRY_PATH, default={"active_project": None})


def save_registry(registry: dict[str, Any]) -> None:
    write_json(REGISTRY_PATH, registry)


def list_project_names() -> list[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(path.name for path in PROJECTS_DIR.iterdir() if path.is_dir())


def load_project_workspace(name: str) -> ProjectWorkspace:
    project_name = validate_project_name(name)
    project_root = PROJECTS_DIR / project_name
    config_path = project_root / "project.json"
    config = read_json(config_path)
    if not isinstance(config, dict):
        raise SystemExit(f"{config_path} must contain a JSON object.")
    return ProjectWorkspace(project_name, project_root, config)


def resolve_project_workspace(name: str | None = None) -> ProjectWorkspace:
    if name:
        return load_project_workspace(name)

    registry = load_registry()
    active_project = registry.get("active_project")
    if not active_project:
        raise SystemExit(
            "No active project is set. Create one with "
            "`python3 manager.py projects create my-app --target-repo /path/to/my-app --set-active`, "
            "or set an existing project with `python3 manager.py projects set-active <name>`."
        )
    return load_project_workspace(str(active_project))


def create_project_workspace(name: str, target_repo: str) -> ProjectWorkspace:
    project_name = validate_project_name(name)
    project_root = PROJECTS_DIR / project_name
    if project_root.exists():
        raise SystemExit(f"Project already exists: {project_name}")

    project_root.mkdir(parents=True)
    (project_root / "logs").mkdir()
    (project_root / "task_results").mkdir()
    (project_root / "logs" / ".gitkeep").write_text("", encoding="utf-8")
    (project_root / "task_results" / ".gitkeep").write_text("", encoding="utf-8")

    project_config = {
        "name": project_name,
        "target_repo": str(Path(target_repo).expanduser().resolve()),
        "agent_command": "",
        "auto_complete_agent_success": True,
        "agent_timeout_seconds": 1800,
        "codex_sandbox": "workspace-write",
        "codex_approval_policy": "never",
        "auto_complete_codex_success": True,
        "max_tasks_per_run": 5,
        "codex_timeout_seconds": 1800,
    }
    write_json(project_root / "project.json", project_config)
    (project_root / "prd.md").write_text(
        (
            "# Product Requirements Document\n\n"
            "Write the human-readable product requirements here. If you already have an "
            "agent-compatible PRD, place it in agent_prd.md instead.\n"
        ),
        encoding="utf-8",
    )
    (project_root / "agent_prd.md").write_text(
        (
            "# Agent PRD\n\n"
            "Run `python3 scripts/normalize_prd.py --project "
            f"{project_name}` to generate this file from prd.md, or write TASK:/RULE: lines here directly.\n"
        ),
        encoding="utf-8",
    )
    (project_root / "PROJECT_CONTEXT.md").write_text("# Project Context\n", encoding="utf-8")
    write_json(project_root / "tasks.json", [])
    write_json(
        project_root / "agent_state.json",
        {
            "current_task_id": None,
            "last_completed_task_id": None,
            "mode": "semi_autonomous",
            "require_human_approval": True,
        },
    )
    return load_project_workspace(project_name)
