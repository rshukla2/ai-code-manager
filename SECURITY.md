# Security

## Supported Versions

This project is currently pre-1.0. Security fixes should target the latest public version.

## Reporting A Vulnerability

Please report security issues privately through the GitHub repository's security advisory flow if it is enabled. If it is not enabled, open an issue with minimal detail and ask for a private disclosure path.

## Secret Handling

Do not commit:

- `.env`
- `projects.json`
- `projects/<name>/project.json`
- `projects/<name>/PROJECT_CONTEXT.md`
- `projects/<name>/prd.md`
- `projects/<name>/agent_prd.md`
- `projects/<name>/tasks.json`
- `projects/<name>/agent_state.json`
- `projects/<name>/logs/`
- `projects/<name>/task_results/`

Coding agent logs and result files may include local paths, generated code summaries, command output, or project-specific details. Treat them as private local artifacts.
