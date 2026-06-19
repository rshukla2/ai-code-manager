# Local Projects

This directory is for your local AI Code Manager project workspaces.

Project workspaces are intentionally ignored by Git because they can contain private PRDs, target repo paths, task history, coding-agent logs, and result JSON files.

Create a workspace with:

```bash
python3 manager.py projects create my-app --target-repo /path/to/my-app --set-active
```
