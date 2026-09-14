# org-workspace Architecture Notes

Internal design decisions for maintainers — covers non-obvious invariants and
contracts that are not fully explained by reading the code alone.

---

## Multiline Property Drawers

### What they are

org-mode property drawers hold key-value metadata for a heading:

```org
* TODO Process inbox
  :PROPERTIES:
  :ID:       abc-123
  :CONTEXT:  First line of the value
  |          Continuation line one
  |          Continuation line two
  :END:
```

Continuation lines begin with `|` (a pipe and a space). They belong to the
property immediately above them — they are **not** separate properties. A single
property value can span many lines this way; `BOOTSTRAP` and `CONTEXT` blocks in
Datacore task templates commonly run 5–15 lines.

### Serializer behavior

`dumps()` (via orgparse's `OrgDocument.dumps()`) serializes continuation lines
inline after the property they extend. The line count of a serialized node is
therefore `1 (heading) + 2 (drawer delimiters) + N (properties) + K (continuation
lines)` — where `K` can be large for rich task templates.

This is important because the shrink guard (below) measures **lines**, not
characters. A node with a 10-line BOOTSTRAP block contributes 10 more lines to the
floor calculation than a plain node with the same heading.

---

## Shrink Guard — `_safe_write`

### Why it exists

Two serializer regressions on 2026-05-16 and 2026-05-18 caused `next_actions.org`
to lose ~50 % of its content between a `load()` and a `save()`. The root cause: a
malformed drawer edge case in the parser produced a truncated `dumps()` output that
was written to disk without any check.

`_safe_write` is the defense-in-depth layer: before any write it compares the new
line count to the on-disk line count and refuses to write if the drop is too large.

### The policy

```
_MAX_SHRINK_FRACTION = 0.25
```

A write is allowed if:

```
new_lines >= (old_lines - expected_delta) * (1 - 0.25)
           = expected_remaining * 0.75
```

`expected_remaining` is `max(0, old_lines - expected_delta)`.

The guard only enforces when `old_lines > 20` to avoid false positives on tiny
test fixtures.

### The `expected_delta` contract

```python
def _safe_write(self, path: Path, content: str, *, expected_delta: int = 0) -> None:
```

`expected_delta` is the number of lines the caller *intentionally* removed before
calling `_safe_write`. Without it, refiling a large node (say, 30 lines including
continuation properties) would always trip the guard even though the removal is
correct.

**How to set it:** count the lines in the subtree being extracted or deleted. In
`refile()` this is:

```python
removed_lines = subtree_text.count("\n")
self._safe_write(source_file, source_content, expected_delta=removed_lines)
```

**When not to set it:** ordinary mutations that don't remove a whole subtree (state
changes, property edits, appending nodes). These leave `expected_delta` at the
default of 0, so the guard sees the full `old_lines` as the baseline.

### Failure mode

When the guard triggers, it raises `CatastrophicShrinkError` with a detailed
message showing `old → new` line counts, the planned delta, and the allowed floor.
The on-disk file is **left untouched** — the atomic temp-file/rename pattern means
the write never began.

```
CatastrophicShrinkError: Refusing to write next_actions.org: serialized output
would shrink the file from 4200 → 850 lines (79.8% loss). Expected ~4170 lines
after planned removal of 30 lines; floor is 3127. This usually means a
parser/serializer bug. The existing on-disk file has been left untouched.
```

### What triggered the v0.5.4 fix

Before v0.5.4, `_safe_write` existed but used `old_lines * 0.75` as the floor
without any `expected_delta` adjustment. Refiling a node whose BOOTSTRAP/CONTEXT
block spanned 12 lines caused the serialized source to drop by 14 lines — just
enough to breach the 25 % floor on a moderately-sized file. The fix thread:

- PR #13 (`fix/refile-multiline-shrink-guard`) introduced `expected_delta`
- Released in v0.5.4
- Issue #15 documents this note

---

## When to use continuation properties

Use `|`-continuation lines when a property value is longer than ~80 characters or
spans multiple logical sentences. The `BOOTSTRAP` and `CONTEXT` keys used by
Datacore agents are the canonical examples:

```org
  :BOOTSTRAP: Short summary of the task
  |           Extended context that spans
  |           multiple lines as needed.
  :CONTEXT:   What the agent needs to know:
  |           key facts, links, and scope.
```

Keep in mind:
- `refile()` handles multiline properties correctly via `expected_delta`.
- `remove_node()` does not pass `expected_delta` — it calls `_safe_write` with the
  default 0 — so removing a large continuation-heavy node from a small file may
  trigger the guard. In practice this is rare because small files have `old_lines ≤
  20` and the guard is skipped. If you hit it in tests, pass the subtree line count.
