# Contributing

Thanks for helping improve AI Code Manager.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Create a local project workspace before running manager commands:

```bash
python3 manager.py projects create my-app --target-repo /path/to/my-app --set-active
```

## Development Guidelines

- Keep real project workspaces, generated results, logs, and secrets out of commits.
- Use generic examples in docs and tests.
- Prefer focused tests for parser, prompt generation, project resolution, and result import behavior.
- Do not commit `.env`, `projects.json`, or anything under `projects/<name>/`.

## Checks

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/ai-code-manager-pycache python3 -m py_compile manager.py scripts/ai_provider.py scripts/generate_prompt.py scripts/normalize_prd.py scripts/parse_prd.py scripts/project_workspace.py
```
