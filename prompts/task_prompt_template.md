# Focused Coding-Agent Task

You are implementing exactly one task. Stay tightly scoped.

## Project Context

{{PROJECT_CONTEXT}}

## Current Task

```json
{{TASK_JSON}}
```

## Mandatory Existing Functionality Check

Before writing or changing any code:

1. Inspect the target repository for existing functionality that already satisfies this task.
2. Search and read the relevant files, tests, routes, commands, docs, and configuration.
3. If the functionality already exists, do not modify code. Verify it with the most relevant test command available. If no exact test exists, run the strongest practical verification or explain why verification is limited.
4. Write a result JSON file for AI Code Manager at `{{RESULT_FILE}}`.
5. Stop after writing the result and reporting what you found.

Use this result JSON shape:

```json
{
  "task_id": 1,
  "outcome": "already_exists_verified",
  "summary": "The requested functionality already exists in these files...",
  "evidence": ["path/to/file.py", "tests/test_feature.py"],
  "tests_run": ["./venv/bin/python -m pytest tests/test_feature.py"],
  "tests_passed": true,
  "changed_files": [],
  "notes": ""
}
```

Supported outcomes:

- `already_exists_verified`: functionality already exists and verification passed.
- `implemented`: you made changes and the task needs human review.
- `blocked`: you could not verify or implement safely.
- `failed`: verification or implementation failed.

## Instructions

- Implement only this task.
- Do not touch unrelated files.
- Follow the acceptance criteria exactly.
- Reuse existing project patterns and keep changes small.
- Run the task-specific test command when provided. Otherwise run or suggest the most relevant tests.
- If you make code changes, create or update focused tests when appropriate, run the relevant tests, write a result JSON with `outcome: "implemented"`, and list changed files.
- Summarize changed files and verification results.
- Stop after this task. AI Code Manager will import the result and decide whether to continue.
