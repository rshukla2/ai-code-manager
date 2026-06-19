# PRD To Atomic Tasks Prompt

Convert the provided PRD into a JSON array of atomic implementation tasks.

Each task must use this shape:

```json
{
  "id": 1,
  "title": "Short task title",
  "description": "Implementation-focused description",
  "status": "pending",
  "depends_on": [],
  "acceptance_criteria": [],
  "test_command": "",
  "notes": ""
}
```

Rules:

- Break work into small, independently reviewable tasks.
- Include dependencies only when one task truly requires another.
- Include concrete acceptance criteria.
- Keep every task status as `pending`.
- Do not include prose outside the JSON array.
