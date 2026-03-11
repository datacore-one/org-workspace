# org-workspace

Python library that makes org-mode files first-class citizens for AI agent workflows.

Built on a vendored fork of [orgparse](https://github.com/karlicoss/orgparse) with write support (PR #77), org-workspace adds multi-file workspace management, structured mutations, concurrency primitives, and query capabilities designed for autonomous AI agents.

## Install

```bash
pip install org-workspace
```

## Quick start

```python
from pathlib import Path
from org_workspace import OrgWorkspace, Query

# Load workspace
ws = OrgWorkspace(roots=[Path("~/org")])

# Query tasks
q = Query(ws)
next_up = q.next_action()
ai_tasks = q.ai_tasks(states=["TODO"])
deadlines = q.deadlines(days=14)

# Create a task
task = ws.create_node(
    file=Path("~/org/inbox.org"),
    heading="Research org-mode parsing",
    state="TODO",
    tags=["AI", "research"],
    body="Investigate approaches for org-mode mutation",
)

# Transition state
ws.transition(task, "DONE", agent="my-agent")

# Save changes (only modified files are written)
ws.save()
```

## Features

### Workspace management
- Multi-file loading with dirty-file tracking
- Content-addressed ID generation with dedup
- Round-trip safe serialization (zero byte-diff on unchanged files)

### NodeView pattern
- Stateless, non-caching read-only views over org nodes
- Generation-counter staleness detection
- Safe for concurrent access patterns

### Mutations (via OrgWorkspace)
- `create_node()` &mdash; create headings with state, tags, properties, body
- `refile()` &mdash; move nodes between files preserving subtree
- `remove_node()` &mdash; delete nodes from files
- `transition()` &mdash; state changes with LOGBOOK entries
- `set_property()`, `set_heading()`, `set_tags()`

### Query system
- `agenda()`, `deadlines()`, `overdue()`, `stale()`
- `by_state()`, `by_tag()`, `by_property()`
- `ai_tasks()` &mdash; find `:AI:` tagged tasks for agent execution
- `next_action()` &mdash; GTD next action selection

### Dependency DAG (Plan)
- Parse `DEPENDS_ON` properties into dependency graphs
- Topological sort for execution ordering
- `ready_tasks()`, `blocked_tasks()`, cycle detection

### Concurrency
- `FileLock` &mdash; file-level locking
- `OptimisticLock` &mdash; hash-based conflict detection
- `TaskClaim` &mdash; agent-level task claiming with staleness timeout
- `multi_lock()` &mdash; deadlock-free multi-file locking (lexicographic order)

### LOGBOOK and session logging
- `add_logbook_entry()`, `add_state_change_entry()`, `add_clock_entry()`
- `SessionLog` for buffered per-session logging

### Archive
- `archive_node()` &mdash; archive with hierarchy preservation
- `archive_done()` &mdash; bulk archive completed tasks
- `archive_plan()` &mdash; archive entire dependency plans

### Context extraction (for AI agents)
- `build_execution_context()` &mdash; structured context from task properties
- `get_prompt()` &mdash; PROMPT property with body fallback
- `get_role()` &mdash; agent persona from ROLE property

## GTD state configuration

```python
from org_workspace import StateConfig

# Default GTD states
config = StateConfig.default()
# sequences: {"gtd": ["TODO", "NEXT", "WAITING", "DONE"]}

# With nightshift (autonomous execution) states
config = StateConfig.nightshift()
# adds: QUEUED, EXECUTING, REVIEW, FAILED
```

## License

BSD 2-Clause. See [LICENSE](LICENSE).

This library includes a vendored copy of [orgparse](https://github.com/karlicoss/orgparse) (BSD 2-Clause, Copyright 2012 Takafumi Arakaki) with modifications from [datacore-one/orgparse PR #77](https://github.com/datacore-one/orgparse) adding write support.
