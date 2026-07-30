# org-workspace Overview

Python library for AI agent org-mode workflows. Wraps orgparse (with PR #77 write support) to provide workspace management, state machines, concurrency, plans-as-DAGs, structured logging, and archive operations.

**Repository**: `github.com/datacore-one/org-workspace`
**Version**: 0.5.1 (254 tests, 79% coverage)
**Python**: >= 3.10
**Key dependency**: orgparse fork at `datacore-one/orgparse@pr-77`

## Architecture Decisions

### Why orgparse as Foundation

Built on top of orgparse rather than custom parser because orgparse handles full org-mode syntax. The fork at `karlicoss/orgparse` has PR #77 adding write support (`dumps()`, `_line_items`, mutation methods). Writing a correct org-mode parser from scratch would be multi-month effort.

**Tradeoff**: orgparse's model is designed for reading, not mutation — forced several workarounds.

### NodeView: Stateless, Non-Caching

NodeView wraps OrgNode but stores no mutable state. Every property access resolves the underlying OrgNode fresh via the workspace's current parse tree. A **generation counter** per file tracks reloads — NodeView raises `StaleNodeError` if the backing file was reloaded since creation.

**Critical pattern**: In mutation loops (refile, archive), re-resolve NodeViews by ID after each operation:
```python
node_id = parent.id()
for item in items:
    parent = ws.find_by_id(node_id)  # re-resolve after each mutation
    ws.refile(item, target, target_parent=parent)
```

### OrgNode.properties Setter Trap

`OrgNode.properties` returns a **fresh dict on each access**. This silently does nothing:
```python
node.properties['KEY'] = 'value'  # writes to throwaway dict
```
org-workspace enforces read-copy-merge-assign via `workspace.set_property()`.

### Refile: Serialize + Remove + Insert

Can't move nodes between files via tree manipulation (OrgEnv mismatch — each `load()` creates independent environment). Instead:
1. Serialize full subtree to text (`_dumps_subtree()`)
2. Remove from source file text
3. Insert at correct position in target file text
4. Reload both files

### Content-Addressed IDs

Format: `org-YYYYMMDD-HHMMSS-{sha256(heading)[:8]}`

- **Dedup**: Same heading → same hash → `create_node(dedup=True)` returns existing
- **Temporal provenance**: Date+time embedded
- **Grep-friendly**: `org-2026` finds all 2026 nodes
- **No location encoding**: Items get refiled; file prefix would rot

### Known Weakness: `_find_subtree_end`

Uses `file_text.find(node_text)` — string matching. Fragile with duplicate headings. Acknowledged fix: use orgparse `_line_items` offsets.

## orgparse Fork Chain

- **Upstream**: `karlicoss/orgparse` (maintained fork of `tkf/orgparse`)
- **PR #77**: Adds `dumps()`, `_line_items`, mutation methods
- **Datacore fork**: `datacore-one/orgparse` — ensures PR #77 available regardless of upstream
- **Gaps**: `dumps()` is single-node only (no children), properties returns fresh dict, no LOGBOOK write API

## Module Structure

| Phase | Module | Purpose |
|-------|--------|---------|
| 0 | `_compat.py`, `_types.py` | orgparse adapter, StateConfig, ChecklistItem |
| 1 | `node_view.py` | Stateless node wrapper with staleness detection |
| 2 | `identifiers.py` | Content-addressed IDs, dedup, IdIndex |
| 3 | `workspace.py` | File management, create/refile/remove, dirty tracking |
| 4 | `concurrency.py` | FileLock, OptimisticLock, TaskClaim |
| 5 | `log.py` | LOGBOOK insertion, SessionLog |
| 6 | `plan.py` | Dependency DAG (BLOCKS/AFTER/WAITING), topological sort |
| 7 | `query.py` | Agenda, deadlines, overdue, stale, AI tasks |
| 8 | `archive.py` | Archive with hierarchy mirroring (DIP-0009) |
| 9 | `context.py`, `prompt.py` | Agent prompt building, context extraction |

## Bug Patterns

All four launch bugs share root cause: **text-append-and-reload needs precise insertion positioning**.

1. **create_node(parent=X)** appended to EOF ignoring parent position → fixed with `_find_subtree_end()`
2. **refile loses children** because `orgparse.dumps()` is single-node → fixed with `_dumps_subtree()`
3. **stale() false positives** on dateless tasks → fixed by requiring resolvable date
4. **archive drops hierarchy** → fixed with `_ensure_archive_hierarchy()`

### State Vocabulary: Seeded Baseline + File-Additive (v0.5.0)

Commit `07961bd` (2026-07-25) made the org-workspace parser the single canonical source for DIP-0009 v1.1 task-state vocabulary. Previously the vocabulary was declared independently in four places (DIP-0009 spec, parser code, per-file `#+SEQ_TODO:` headers, query tooling) with no mechanism to catch drift between them.

**Design**: The parser environment is seeded with the canonical DIP-0009 v1.1 vocabulary as a baseline. Per-file `#+SEQ_TODO:` declarations then ADD to that seeded set — they never restrict or replace it.

**Tradeoff (deliberate)**: This departs from strict org-mode semantics, where a file's SEQ_TODO header is normally authoritative/exhaustive for that file. The seeded-baseline + additive approach is defensive: a writer's task state is never silently swallowed or misparsed just because one file's header didn't declare that keyword. Treat additive-not-restrictive parsing in `workspace.py`/`_types.py` as intentional, not a bug.

Touched: `pyproject.toml`, `src/org_workspace/_types.py`, `src/org_workspace/_vendor/orgparse/node.py`, `src/org_workspace/workspace.py`, `tests/test_state_vocabulary.py`, `tests/test_types.py`, `tests/test_workspace.py`.

## Real-World Testing Results

Against 193KB next_actions.org (367 nodes):
- Round-trip INV-1: perfect (zero byte differences)
- Only 3/367 nodes had `:ID:` → drove content-addressed ID design
- 101/197 tasks missing `:CREATED:` → drove auto-CREATED on create_node
- `OrgDate` wrapper is never None (check inner `.start` value)
- Curly quotes (Unicode U+2019) preserved by orgparse — match exact characters
