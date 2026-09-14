# org-workspace Architecture Notes

Internal design decisions that are non-obvious from the code alone. Aimed at
contributors touching the serializer, refile logic, or property handling.

---

## Multiline property drawers

### Format

org-workspace uses a `|`-continuation convention for properties whose values
span multiple lines:

```org
* TODO Archive this task
  :PROPERTIES:
  :ID:       abc123
  :BOOTSTRAP: |
  :   First line of context
  :   Second line of context
  :   Third line
  :END:
```

The first line of a multiline property has the value `|`. Continuation lines
start with `:   ` (colon, three spaces) and are treated as part of the same
property value by org-workspace's helpers — but **not** by standard orgparse,
which returns `"|"` for the property value and ignores the rest.

### When they appear

`BOOTSTRAP` and `CONTEXT` property drawers are the primary source of multiline
values. These fields hold rich agent-readable context for a task (background,
instructions, acceptance criteria) and routinely span 10–50 lines.

Any property can be set as multiline via `set_property` / `OrgWorkspace.set_property`:

```python
ws.set_property(node, "CONTEXT", "Line one\nLine two\nLine three")
# Serialized as:
# :CONTEXT: |
# :   Line one
# :   Line two
# :   Line three
```

### Reading and writing

`_compat.get_multiline_property(node, key)` and `set_multiline_property(node,
key, value)` are the canonical helpers. They operate on `node._line_items`
(the vendored orgparse PR-77 internals) to read continuation lines and inject
or replace them during mutation.

`OrgWorkspace.get_property` / `set_property` call these helpers automatically.
Do not read `node.properties[key]` directly for keys that may be multiline —
you will get `"|"` instead of the full value.

---

## Shrink guard

### Problem

The serializer (`dumps()`) reconstructs the full file text from the in-memory
tree. A parser or serializer bug can emit a truncated result — e.g. a malformed
property drawer causes the dumps pass to produce a string half the expected
length. Writing that back to disk silently destroys data.

This happened twice in production (2026-05-16 and 2026-05-18): `~50%` of
`next_actions.org` disappeared between read and write because continuation
lines in a property drawer confused the serializer.

### Guard design

`OrgWorkspace._safe_write(path, content, *, expected_delta=0)` wraps every
disk write. Before writing it compares line counts:

```
old_lines  = current lines on disk
new_lines  = lines in the serialized content
floor      = int((old_lines - expected_delta) * (1 - _MAX_SHRINK_FRACTION))

if new_lines < floor:
    raise CatastrophicShrinkError(...)
```

`_MAX_SHRINK_FRACTION = 0.25` — a file may shrink by at most 25% of its
expected post-edit size before the guard fires.

The guard is skipped for files with ≤ 20 lines (tiny test fixtures would
produce false positives).

### The `expected_delta` contract

`expected_delta` is the number of lines the caller **intentionally** removed
from the file. The guard bases its floor on `old_lines - expected_delta`, not
on `old_lines`, so that a planned removal of a large node does not trip it.

**Callers that pass a non-zero `expected_delta`:**

| Caller | What it passes |
|--------|----------------|
| `refile()` source write | `subtree_text.count("\n")` — the serialized size of the extracted subtree |

All other write paths (`save()`, `set_property`, etc.) use the default
`expected_delta=0` because they are not intentionally removing large blocks.

**When to add `expected_delta` to a new caller:**

Pass it when your operation intentionally deletes a block of lines (extract,
archive, batch-delete). The value should be the line count of the removed
content **before** serialization. If the removed block contains multiline
property drawers, those continuation lines must be included in the count —
that is the root cause of the v0.5.4 fix (see below).

### Failure mode

When `CatastrophicShrinkError` is raised, the on-disk file is **left
untouched**. The error propagates to the caller. No partial write occurs
because `_safe_write` uses an atomic temp-file + `os.replace()` pattern.

---

## v0.5.4 fix — refile + multiline shrink guard

**Bug (fixed in v0.5.4, PR #13):** `refile()` passed `expected_delta` as the
subtree's line count, but the subtree was serialized *without* its
`|`-continuation property lines. When a node had a large `BOOTSTRAP` or
`CONTEXT` drawer, the serialized subtree was much shorter than the content
actually removed from the source file. The gap between the true removal size
and the declared `expected_delta` pushed `new_lines` below the guard floor,
raising `CatastrophicShrinkError` and aborting legitimate refile operations.

**Fix:** `_dumps_subtree()` now includes continuation lines in its output, so
`subtree_text.count("\n")` accurately reflects the lines removed from the
source file. `expected_delta` and the actual removal are in agreement; the
guard fires only on genuine anomalies.

**Traceability:**
- Bug introduced: v0.5.3 (initial refile implementation)
- Fixed: v0.5.4 (`fix(refile): account for planned subtree removal in shrink guard`, commit `4a52c4b`)
- Issue: datacore-one/org-workspace#15
