# org-workspace Quick Start

> From install to your first AI-readable task list in under five minutes.

## Install

```bash
pip install org-workspace
```

## Your first five minutes

Assume you have at least one org-mode file. If not, create a minimal one:

```
~/org/inbox.org:

* TODO Write my first task
  :PROPERTIES:
  :ID: abc123
  :END:
  This is what org-workspace can read and write.
```

Now open Python:

```python
from pathlib import Path
from org_workspace import OrgWorkspace, Query

# Point at your org directory (or a single file)
ws = OrgWorkspace(roots=[Path.home() / "org"])

# Find all tasks tagged for AI execution
q = Query(ws)
for task in q.ai_tasks(states=["TODO"]):
    print(task.heading, task.tags)

# Create a task programmatically
new_task = ws.create_node(
    file=Path.home() / "org" / "inbox.org",
    heading="Summarise my meeting notes",
    state="TODO",
    tags=["AI", "research"],
    body="Use the attached notes in ~/org/notes/2026-07-meeting.org",
)

# Save — only modified files are written, unchanged files are left alone
ws.save()
print("Task created:", new_task.id)
```

That's it. You've loaded a workspace, queried it, created a task, and saved safely.

## What just happened

**`OrgWorkspace`** loads and indexes all your org files. It tracks which files are dirty and guarantees round-trip safety — if you read a file and write it back unchanged, the bytes on disk don't change.

**`Query`** is a stateless query layer on top of the workspace. `ai_tasks()` finds any heading tagged `:AI:` — the convention Datacore uses to hand work to autonomous agents overnight.

**`create_node()`** inserts a new heading with a unique content-addressed ID. It will never silently overwrite an existing node.

## The key primitives

| Primitive | What it does |
|-----------|-------------|
| `OrgWorkspace` | Load, index, and safely write org files |
| `Query` | Read-only queries: agenda, deadlines, AI tasks, next action |
| `NodeView` | Stateless view of a single node; detects staleness automatically |
| `TaskClaim` | Atomic task claiming — prevents two agents running the same task |
| `OptimisticLock` | Hash-based conflict detection for concurrent writes |
| `Plan` | Parse `DEPENDS_ON` into a dependency DAG, topological sort |

## Common patterns for AI agents

### Claim a task before executing

```python
from org_workspace import OrgWorkspace, Query
from org_workspace.concurrency import TaskClaim

ws = OrgWorkspace(roots=[Path.home() / "org"])
q = Query(ws)
tc = TaskClaim(ws)

for task in q.ai_tasks(states=["TODO"]):
    if tc.claim(task, agent_id="my-agent"):
        # Only one agent gets here; others skip this task
        ws.transition(task, "EXECUTING", agent="my-agent")
        ws.save()
        # ... do work ...
        ws.transition(task, "DONE", agent="my-agent")
        tc.release(task, "my-agent")
        ws.save()
```

### Find overdue tasks

```python
overdue = q.overdue()
for task in overdue:
    print(f"{task.heading} — deadline: {task.deadline}")
```

### Build a dependency plan

```python
from org_workspace import Plan

# Plan wraps a project subtree — find the root node first
roots = q.by_property("ID", "your-project-id")
if roots:
    plan = Plan(roots[0], ws)
    for task in plan.ready_tasks():
        print("Ready to run:", task.heading)
    for task, blocker in plan.blocked_tasks():
        print("Blocked:", task.heading, "(waiting on:", blocker, ")")
```

## GTD states

org-workspace ships with a default GTD state sequence and an extended nightshift sequence for autonomous execution:

```python
from org_workspace import StateConfig

# Default GTD: TODO → NEXT → WAITING → DONE
config = StateConfig.default()

# Nightshift: adds QUEUED, EXECUTING, REVIEW, FAILED for agent pipelines
config = StateConfig.nightshift()
ws = OrgWorkspace(roots=[...], state_config=config)
```

## Where to go next

- [GitHub](https://github.com/datacore-one/org-workspace) — source, issues, discussions
- `pip install org-workspace` then `python -c "from org_workspace import OrgWorkspace; help(OrgWorkspace)"`
- Issues and feature requests welcome on GitHub
