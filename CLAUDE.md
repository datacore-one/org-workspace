# CLAUDE.md

## org-workspace

> TODO: Add project description, development setup, and key files.

## Datacore Space Context

This project lives inside a Datacore space. Session lifecycle commands are available:

- `/wrap-up` — write session entry to team journal, commit and push
- `/continue` — resume from yesterday's continuation notes; `--save` persists current work
- `/standup` — generate/post standup from recent team journals
- `/today` — daily briefing (incremental if already generated)

| Key | Value |
|-----|-------|
| Space | `2-datacore` |
| Journal | `~/Data/2-datacore/journal/YYYY-MM-DD.md` |
| Org | `~/Data/2-datacore/org/next_actions.org` |

When `/wrap-up` runs, use the team journal schema: `## @contributor` narrative sections + `## Session Metadata` YAML block.