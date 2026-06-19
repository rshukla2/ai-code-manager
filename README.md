# AI Code Manager

AI Code Manager is a local orchestration tool for managing coding-agent implementation work one task at a time across multiple product projects. Each local project has its own PRD, project context, task queue, agent state, logs, result files, and target repo configuration.

The reusable tool code lives in this repository. Your real project workspaces live under `projects/` and are ignored by Git by default.

## Requirements

- Python 3.10 or newer.
- A coding-agent CLI that can receive a prompt on stdin and write the required result JSON.
- Codex CLI is the built-in default runner if no custom `AGENT_COMMAND` is configured.
- An AI provider API key only if you use PRD normalization or AI task deduplication.

## Quick Start

```bash
git clone https://github.com/rshukla2/ai-code-manager.git
cd ai-code-manager
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 manager.py projects create my-app --target-repo /path/to/my-app --set-active
```

Then add product context and requirements:

```text
projects/my-app/PROJECT_CONTEXT.md
projects/my-app/prd.md
```

If `prd.md` is a human-readable PRD, normalize it first:

```bash
python3 scripts/normalize_prd.py --project my-app
```

This creates:

```text
projects/my-app/agent_prd.md
```

Then generate and review tasks:

```bash
python3 scripts/parse_prd.py --project my-app --summary
python3 scripts/parse_prd.py --project my-app
```

Run coding-agent automation:

```bash
python3 manager.py --project my-app run-one --dry-run
python3 manager.py --project my-app run-one
python3 manager.py --project my-app run-loop --limit 5
```

## Private Files Warning

Do not commit local workspaces, secrets, logs, or task result files. They may contain private PRDs, local target repo paths, coding-agent command output, implementation summaries, or project-specific details.

These files are ignored by default:

```text
.env
projects.json
projects/<name>/
```

Use `templates/project/` and `examples/sample-project/` for public starter files. Keep your real projects in `projects/`.

## Project Workflow

1. Create a project workspace.
2. Write a human PRD in `prd.md`.
3. Normalize `prd.md` into `agent_prd.md`, or write `agent_prd.md` directly.
4. Parse `agent_prd.md` into `tasks.json`.
5. Review the generated tasks.
6. Run one coding-agent task or a bounded task loop.
7. Inspect the target repo diff after automation finishes.

The manager runs one project at a time. If `--project` is omitted, commands use the active project from your local `projects.json`.

## Project Commands

```bash
python3 manager.py projects list
python3 manager.py projects active
python3 manager.py projects set-active my-app
python3 manager.py projects create second-app --target-repo /path/to/second-app --set-active
```

Run commands against a specific project:

```bash
python3 manager.py --project my-app status
python3 manager.py --project my-app next
python3 manager.py --project my-app prompt
python3 manager.py --project my-app approve
python3 manager.py --project my-app fail
python3 manager.py --project my-app block
python3 manager.py --project my-app import-result
python3 manager.py --project my-app reset-task --id 12
python3 manager.py --project my-app run-one
python3 manager.py --project my-app run-loop --limit 5
```

## Project Layout

Local project workspaces use this structure:

```text
projects/
  my-app/
    project.json
    prd.md
    agent_prd.md
    PROJECT_CONTEXT.md
    tasks.json
    agent_state.json
    logs/
    task_results/
```

Each project has a `project.json`:

```json
{
  "name": "my-app",
  "target_repo": "/path/to/my-app",
  "agent_command": "",
  "auto_complete_agent_success": true,
  "agent_timeout_seconds": 1800,
  "codex_sandbox": "workspace-write",
  "codex_approval_policy": "never",
  "auto_complete_codex_success": true,
  "max_tasks_per_run": 5,
  "codex_timeout_seconds": 1800
}
```

`agent_command` is optional. The runner selection order is:

1. If `AGENT_COMMAND` or project-level `agent_command` is set, AI Code Manager uses that custom coding-agent command.
2. If no custom agent command is set, AI Code Manager uses the built-in Codex command builder.

`CODEX_COMMAND` is still useful because Codex is the default built-in runner. It is ignored when `AGENT_COMMAND` is set.

`AGENT_COMMAND` supports these placeholders:

- `{target_repo}` or `{project_root}`
- `{workspace}`
- `{manager_root}`

Example:

```bash
AGENT_COMMAND="your-agent-cli --cwd {target_repo} --workspace {workspace} -"
```

Default Codex setup:

```bash
AGENT_COMMAND=
CODEX_COMMAND=codex
```

Custom agent setup:

```bash
AGENT_COMMAND="your-agent-cli --cwd {target_repo} --workspace {workspace} -"
CODEX_COMMAND=codex
```

Global `.env` is only for shared secrets and defaults:

```bash
AI_PROVIDER=
AI_API_KEY=
AI_MODEL=

# Optional custom coding-agent command. Overrides the built-in Codex runner when set.
AGENT_COMMAND=

# Built-in default runner. Used only when AGENT_COMMAND is blank.
CODEX_COMMAND=codex
```

## PRD Files

AI Code Manager uses two PRD files so the workflow stays clear:

- `prd.md`: the human-readable product requirements document. Write this naturally.
- `agent_prd.md`: the normalized implementation plan with explicit `TASK:` and `RULE:` lines. This is what the parser reads.

The normalization step is optional. If you already have an agent-compatible PRD, put it directly in `agent_prd.md` and skip `normalize_prd.py`.

## Human PRD To Agent PRD

For a natural-language PRD in `projects/my-app/prd.md`, run:

```bash
python3 scripts/normalize_prd.py --project my-app
```

By default, this reads:

```text
projects/my-app/prd.md
```

and writes:

```text
projects/my-app/agent_prd.md
```

Safety and provider options:

```bash
python3 scripts/normalize_prd.py --project my-app --dry-run
python3 scripts/normalize_prd.py --project my-app --overwrite
python3 scripts/normalize_prd.py --project my-app --provider anthropic --model claude-sonnet-4-5
```

Provider SDKs are optional. Install the one you want to use:

```bash
python3 -m pip install openai
python3 -m pip install anthropic
```

## Agent PRD To Tasks

For an agent-compatible PRD in `projects/my-app/agent_prd.md`:

```bash
python3 scripts/parse_prd.py --project my-app --summary
python3 scripts/parse_prd.py --project my-app
```

The parser writes to:

```text
projects/my-app/tasks.json
```

If your agent PRD is somewhere else:

```bash
python3 scripts/parse_prd.py --project my-app --input path/to/agent_prd.md
```

If you need a versioned task export for another tool, use `--output`:

```bash
python3 scripts/parse_prd.py --project my-app --output tasks.v1.json
```

AI Code Manager itself uses `projects/my-app/tasks.json` as the task queue by default.

## Result Handoff

Every generated task prompt tells the coding agent to inspect the target repo before coding. If functionality already exists, the agent verifies it and writes a result file under the selected project:

```text
projects/<name>/task_results/task_<id>_result.json
```

Supported result outcomes:

- `already_exists_verified`
- `implemented`
- `blocked`
- `failed`

If the coding agent reports `already_exists_verified` or `implemented` with `tests_passed: true`, the manager marks the task completed and starts the next ready task.

## Public Release Checklist

Before publishing or pushing changes, scan for private local details:

```bash
rg -n "/Users/|chief-assistant|kidlin|personal_token|secondary_token|credentials\\.json" . --glob '!README.md'
```

Then confirm local workspaces are ignored:

```bash
git status --ignored
```
