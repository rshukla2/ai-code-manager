#!/usr/bin/env python3
"""Create a rough tasks.json draft from agent_prd.md.

This simple Version 1 parser is intentionally rule-based. It can later be
replaced with an LLM-based parser that understands dependencies and richer
acceptance criteria.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from ai_provider import call_structured_ai
from project_workspace import ROOT, resolve_project_workspace

DEFAULT_AI_DEDUPE_MODEL = "gpt-4o-mini"
DEFAULT_AI_DEDUPE_PROVIDER = "openai"

AI_DEDUPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tasks"],
    "properties": {
        "tasks": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

SERVICE_NAMES = [
    "Gmail",
    "Google Calendar",
    "Google Contacts",
    "Google Drive",
    "Google Docs",
    "Google Sheets",
    "Google Slides",
    "Google Forms",
    "Google Meet",
]


def clean_markdown_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#{1,6}\s+", "", line)
    line = re.sub(r"^[-*+]\s+", "", line)
    line = re.sub(r"^\d+[.)]\s+", "", line)
    return line.strip()


def extract_task_candidates(text: str) -> list[str]:
    candidates = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if not stripped:
            continue

        if stripped.upper().startswith("TASK:"):
            candidate = re.sub(r"^TASK:\s*", "", stripped, flags=re.IGNORECASE).strip()

            if candidate:
                candidates.append(candidate)

    return candidates


def normalize_task_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_umbrella_service_task(candidate: str, all_candidates: list[str]) -> bool:
    normalized = normalize_task_text(candidate)
    umbrella_patterns = []
    for service_name in SERVICE_NAMES:
        service = normalize_task_text(service_name)
        umbrella_patterns.extend(
            [
                f"implement {service} workflow support",
                f"implement {service} as a supported service",
            ]
        )

    if normalized not in umbrella_patterns:
        return False

    service_words = normalized.removeprefix("implement ").replace(" workflow support", "")
    service_words = service_words.replace(" as a supported service", "")
    detailed_tasks = [
        item
        for item in all_candidates
        if item != candidate and service_words in normalize_task_text(item)
    ]
    return bool(detailed_tasks)


def filter_candidates(candidates: list[str], include_umbrella: bool) -> tuple[list[str], int]:
    if include_umbrella:
        return candidates, 0

    filtered = [
        candidate
        for candidate in candidates
        if not is_umbrella_service_task(candidate, candidates)
    ]
    return filtered, len(candidates) - len(filtered)


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


def build_dedupe_prompt() -> str:
    return (
        "You deduplicate software implementation tasks before they are written to the task queue JSON.\n"
        "Return strict JSON only.\n"
        "Rules:\n"
        "- Preserve the original task wording whenever a kept task is already clear.\n"
        "- Remove exact duplicates, repeated tasks, and tasks fully covered by more specific tasks.\n"
        "- Keep distinct tasks even when they are in the same product area.\n"
        "- Do not invent new product features, statuses, dependencies, or acceptance criteria.\n"
        "- Keep the original order of the surviving tasks as much as possible.\n"
        "- Return at least one task."
    )


def validate_deduped_candidates(data: Any) -> list[str]:
    if not isinstance(data, dict):
        raise ValueError("AI dedupe response must be a JSON object.")

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("AI dedupe response must contain a tasks array.")

    cleaned = []
    seen = set()
    for item in tasks:
        if not isinstance(item, str):
            raise ValueError("AI dedupe tasks must be strings.")
        task = " ".join(item.strip().split())
        if not task:
            continue
        normalized = normalize_task_text(task)
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(task)

    if not cleaned:
        raise ValueError("AI dedupe response did not contain any usable tasks.")

    return cleaned


def dedupe_candidates_with_ai(candidates: list[str], provider: str, model: str, api_key: str) -> list[str]:
    data = call_structured_ai(
        provider=provider,
        system_prompt=build_dedupe_prompt(),
        user_text=json.dumps({"tasks": candidates}, indent=2),
        model=model,
        api_key=api_key,
        schema_name="deduped_prd_tasks",
        schema=AI_DEDUPE_SCHEMA,
    )
    return validate_deduped_candidates(data)


def maybe_dedupe_candidates_with_ai(
    candidates: list[str],
    *,
    enabled: bool,
    strict: bool,
    provider: str,
    model: str,
    api_key: str,
) -> tuple[list[str], int, bool]:
    if not enabled or not candidates:
        return candidates, 0, False

    if not api_key:
        return candidates, 0, False

    try:
        deduped = dedupe_candidates_with_ai(candidates, provider, model, api_key)
    except Exception as exc:
        message = f"AI task dedupe failed; continuing without AI dedupe: {exc}"
        if strict:
            raise SystemExit(message) from exc
        print(f"Warning: {message}", file=sys.stderr)
        return candidates, 0, False

    removed_count = len(candidates) - len(deduped)
    return deduped, max(removed_count, 0), True


def build_tasks(candidates: list[str]) -> list[dict[str, object]]:
    if not candidates:
        candidates = ["Review PRD and define first implementation task"]

    tasks = []
    for index, candidate in enumerate(candidates, start=1):
        tasks.append(
            {
                "id": index,
                "title": candidate[:80],
                "description": f"Implement or refine: {candidate}",
                "status": "pending",
                "depends_on": [],
                "acceptance_criteria": [],
                "test_command": "",
                "notes": "Generated by the simple rule-based PRD parser. Review before use.",
            }
        )
    return tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a rough tasks.json draft from explicit TASK: lines in agent_prd.md."
    )
    parser.add_argument("--project", help="Project name. Defaults to projects.json active_project.")
    parser.add_argument(
        "--input",
        type=Path,
        help="Agent PRD input path. Defaults to the selected project's agent_prd.md.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Task queue output path. Defaults to the selected project's tasks.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated tasks JSON without writing the output file.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only task counts and the first few task titles without writing the output file.",
    )
    parser.add_argument(
        "--include-umbrella",
        action="store_true",
        help="Keep broad service-support tasks even when detailed service tasks exist.",
    )
    parser.add_argument(
        "--no-ai-dedupe",
        action="store_true",
        help="Disable AI-powered task deduplication and keep the rule-based parser flow.",
    )
    parser.add_argument(
        "--ai-dedupe-strict",
        action="store_true",
        help="Fail instead of falling back when AI task deduplication fails.",
    )
    parser.add_argument(
        "--provider",
        help=f"AI provider for dedupe. Defaults to AI_PROVIDER or {DEFAULT_AI_DEDUPE_PROVIDER}.",
    )
    parser.add_argument(
        "--model",
        help=f"AI model for dedupe. Defaults to AI_MODEL or {DEFAULT_AI_DEDUPE_MODEL}.",
    )
    return parser


def resolve_ai_key(env: dict[str, str], provider: str) -> str:
    provider_key_prefix = provider.upper().replace("-", "_")
    return (
        env.get("AI_API_KEY")
        or env.get(f"{provider_key_prefix}_API_KEY")
        or ""
    )


def resolve_input_path(path: Path, workspace_root: Path) -> Path:
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return workspace_root / path


def main() -> int:
    args = build_parser().parse_args()
    workspace = resolve_project_workspace(args.project)
    input_path = args.input or workspace.agent_prd_path
    input_path = resolve_input_path(input_path, workspace.root)
    output_path = args.output or workspace.tasks_path
    output_path = output_path if output_path.is_absolute() else workspace.root / output_path

    if not input_path.exists():
        print(f"Missing agent PRD file: {input_path}")
        print("Create it directly, or run `python3 scripts/normalize_prd.py --project <name>` to generate it from prd.md.")
        return 1

    text = input_path.read_text(encoding="utf-8")
    candidates, skipped_count = filter_candidates(
        extract_task_candidates(text),
        include_umbrella=args.include_umbrella,
    )
    env = load_env()
    ai_dedupe_enabled = not args.no_ai_dedupe
    ai_provider = args.provider or env.get("AI_PROVIDER") or DEFAULT_AI_DEDUPE_PROVIDER
    provider_key_prefix = ai_provider.upper().replace("-", "_")
    ai_model = (
        args.model
        or env.get("AI_MODEL")
        or env.get(f"{provider_key_prefix}_MODEL")
        or DEFAULT_AI_DEDUPE_MODEL
    )
    candidates, ai_dedupe_removed_count, ai_dedupe_used = maybe_dedupe_candidates_with_ai(
        candidates,
        enabled=ai_dedupe_enabled,
        strict=args.ai_dedupe_strict,
        provider=ai_provider,
        model=ai_model,
        api_key=resolve_ai_key(env, ai_provider),
    )
    tasks = build_tasks(candidates)

    if args.summary:
        print(f"Generated task count: {len(tasks)}")
        print(f"Skipped umbrella task count: {skipped_count}")
        if ai_dedupe_enabled:
            if ai_dedupe_used:
                print(f"AI dedupe removed task count: {ai_dedupe_removed_count}")
                print(f"AI dedupe provider: {ai_provider}")
                print(f"AI dedupe model: {ai_model}")
            elif resolve_ai_key(env, ai_provider):
                print("AI dedupe was attempted but not used.")
            else:
                print("AI dedupe skipped: no AI provider API key is set.")
        print("First tasks:")
        for task in tasks[:10]:
            print(f"  {task['id']}. {task['title']}")
        return 0

    if args.dry_run:
        print(json.dumps(tasks, indent=2))
        print(
            (
                f"\nDry run: generated {len(tasks)} task(s); "
                f"skipped {skipped_count} umbrella task(s); "
                f"AI dedupe removed {ai_dedupe_removed_count if ai_dedupe_used else 0} task(s)."
            ),
            file=sys.stderr,
        )
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(tasks)} task(s) to {output_path}.")
    if skipped_count:
        print(f"Skipped {skipped_count} umbrella task(s). Use --include-umbrella to keep them.")
    if ai_dedupe_used:
        print(f"AI dedupe removed {ai_dedupe_removed_count} task(s) using {ai_provider}/{ai_model}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
