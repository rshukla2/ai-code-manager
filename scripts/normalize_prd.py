#!/usr/bin/env python3
"""Convert a human PRD into the TASK:/RULE: PRD format using an AI provider."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ai_provider import call_structured_ai
from project_workspace import ROOT, resolve_project_workspace

DEFAULT_INPUT: Path | None = None
DEFAULT_OUTPUT: Path | None = None
PROMPT_PATH = ROOT / "prompts" / "prd_to_agent_prd_prompt.md"
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.5"


PRD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "overview", "sections"],
    "properties": {
        "title": {"type": "string"},
        "overview": {"type": "string"},
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["heading", "summary", "tasks", "rules"],
                "properties": {
                    "heading": {"type": "string"},
                    "summary": {"type": "string"},
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["text", "acceptance_criteria"],
                            "properties": {
                                "text": {"type": "string"},
                                "acceptance_criteria": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                    "rules": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    return values


def read_text(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Missing file: {path}")
    return path.read_text(encoding="utf-8")


def clean_line(value: str) -> str:
    return " ".join(value.strip().split())


def validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan.get("title"), str) or not plan["title"].strip():
        raise SystemExit("AI provider response is missing a non-empty title.")
    if not isinstance(plan.get("overview"), str):
        raise SystemExit("AI provider response is missing an overview string.")
    sections = plan.get("sections")
    if not isinstance(sections, list) or not sections:
        raise SystemExit("AI provider response must contain at least one section.")

    task_count = 0
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            raise SystemExit(f"Section {index} must be an object.")
        if not clean_line(str(section.get("heading", ""))):
            raise SystemExit(f"Section {index} is missing a heading.")
        if not isinstance(section.get("tasks"), list):
            raise SystemExit(f"Section {index} tasks must be a list.")
        if not isinstance(section.get("rules"), list):
            raise SystemExit(f"Section {index} rules must be a list.")

        for task in section["tasks"]:
            if not isinstance(task, dict) or not clean_line(str(task.get("text", ""))):
                raise SystemExit(f"Section {index} contains an invalid task.")
            criteria = task.get("acceptance_criteria")
            if not isinstance(criteria, list):
                raise SystemExit(f"Task `{task.get('text')}` acceptance_criteria must be a list.")
            task_count += 1

        for rule in section["rules"]:
            if not isinstance(rule, str) or not clean_line(rule):
                raise SystemExit(f"Section {index} contains an invalid rule.")

    if task_count == 0:
        raise SystemExit("AI provider response did not produce any tasks.")


def render_agent_prd(plan: dict[str, Any]) -> str:
    validate_plan(plan)
    lines: list[str] = [f"# Product Requirements Document: {clean_line(plan['title'])}", ""]
    overview = clean_line(plan.get("overview", ""))
    if overview:
        lines.extend([overview, ""])

    for index, section in enumerate(plan["sections"], start=1):
        heading = clean_line(section["heading"])
        lines.extend([f"## {index}. {heading}", ""])

        summary = clean_line(section.get("summary", ""))
        if summary:
            lines.extend([summary, ""])

        for task in section["tasks"]:
            task_text = clean_line(task["text"])
            lines.extend([f"TASK: {task_text}", ""])
            criteria = [clean_line(item) for item in task.get("acceptance_criteria", []) if clean_line(item)]
            if criteria:
                joined = "; ".join(criteria)
                lines.extend([f"RULE: Acceptance criteria for `{task_text}`: {joined}", ""])

        for rule in section["rules"]:
            lines.extend([f"RULE: {clean_line(rule)}", ""])

    return "\n".join(lines).rstrip() + "\n"


def load_json_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON fixture: {exc}") from exc
    validate_plan(plan)
    return plan


def resolve_input_path(path: Path, workspace_root: Path) -> Path:
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return workspace_root / path


def resolve_ai_config(args: argparse.Namespace, env: dict[str, str]) -> tuple[str, str, str]:
    provider = args.provider or env.get("AI_PROVIDER") or DEFAULT_PROVIDER
    provider_key_prefix = provider.upper().replace("-", "_")
    model = (
        args.model
        or env.get("AI_MODEL")
        or env.get(f"{provider_key_prefix}_MODEL")
        or DEFAULT_MODEL
    )
    api_key = (
        args.api_key
        or env.get("AI_API_KEY")
        or env.get(f"{provider_key_prefix}_API_KEY")
    )
    if not api_key:
        raise SystemExit(
            "An AI provider API key is required. Set AI_API_KEY, "
            f"{provider_key_prefix}_API_KEY, or pass --api-key."
        )
    return provider, model, api_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize a human PRD into TASK:/RULE: Markdown.")
    parser.add_argument("--project", help="Project name. Defaults to projects.json active_project.")
    parser.add_argument("--input", type=Path, help="Human PRD input path. Defaults to the selected project's prd.md.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Generated agent PRD output path. Defaults to the selected project's agent_prd.md.",
    )
    parser.add_argument("--provider", help="AI provider adapter to use. Defaults to AI_PROVIDER.")
    parser.add_argument("--model", help="AI model to use. Defaults to AI_MODEL.")
    parser.add_argument("--api-key", help="AI provider API key. Defaults to AI_API_KEY or provider-specific env.")
    parser.add_argument("--dry-run", action="store_true", help="Print generated Markdown without writing a file.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing output file.")
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Render from an existing structured JSON plan instead of calling an AI provider.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    workspace = resolve_project_workspace(args.project)
    output_path = args.output or workspace.agent_prd_path
    output_path = output_path if output_path.is_absolute() else workspace.root / output_path

    if args.from_json:
        plan = load_json_plan(resolve_input_path(args.from_json, ROOT))
    else:
        input_path = args.input or workspace.prd_path
        input_path = resolve_input_path(input_path, workspace.root)
        env = load_env()
        provider, model, api_key = resolve_ai_config(args, env)
        prd_text = read_text(input_path)
        prompt = read_text(PROMPT_PATH)
        try:
            plan = call_structured_ai(
                provider=provider,
                system_prompt=prompt,
                user_text=prd_text,
                model=model,
                api_key=api_key,
                schema_name="agent_prd_plan",
                schema=PRD_SCHEMA,
            )
        except RuntimeError as exc:
            print(exc)
            return 1
        validate_plan(plan)

    markdown = render_agent_prd(plan)

    if args.dry_run:
        print(markdown, end="")
        return 0

    if output_path.exists() and not args.overwrite:
        print(f"Output file already exists: {output_path}. Use --overwrite to replace it.")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote agent-compatible PRD to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
