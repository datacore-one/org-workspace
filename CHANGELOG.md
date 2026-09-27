# Changelog

## 0.7.0 (unreleased)

### Changed (breaking)

- `OrgWorkspace.load()` refuses duplicate `:ID:`s. A file whose headings
  repeat an id, or an id already indexed from another file, raises
  `DuplicateIdError` naming the id and file, and nothing is loaded. Loading
  used to give the later copy a fresh random id in memory; the next unrelated
  `save()` wrote it to disk, and a stale copy of a dismissed task came back as
  a new open task (TSK-2).
- `OrgWorkspace(repair_duplicate_ids=True)` keeps the old in-memory
  regeneration for deliberate repair tools.
- `Query.agenda()` keeps open tasks whose SCHEDULED date has passed (they
  used to drop out the day after) and skips terminal-state tasks (TSK-7).
- New helpers: `find_duplicate_ids(root)` (read-only) and
  `refuse_duplicate_ids(root, path=...)`. `dedup_ids()` is unchanged and is
  now only the explicit repair.

### Upgrading

Reconcile duplicate ids before upgrading (e.g. Datacore's
`org_resolve_id_conflicts.py`), or readers of those files will stop with
`DuplicateIdError`.

## 0.6.0 (unreleased)

### Changed (breaking for default-config readers)

- `StateConfig.default()` now seeds the DIP-0009 v2.0 vocabulary:
  `TODO NEXT WAITING REVIEW | DONE DEFERRED CANCELLED`.
  - QUEUED, WORKING and FAILED are retired from the baseline. A file that
    still uses one of them parses it only if its own `#+TODO` / `#+SEQ_TODO`
    header declares it. In a headerless file the keyword is read as part of
    the heading text, so the node is not a task.
  - DEFERRED moved into the done class (right of `|`). It stays non-terminal:
    it can wake to TODO. Terminal states are DONE and CANCELLED.
- `StateConfig.nightshift()` remains a deprecated alias for `default()`.

### Upgrading

Before upgrading, make sure no authored org file uses QUEUED, WORKING or
FAILED without declaring it in its header. Either migrate the headings
(QUEUED -> NEXT, WORKING -> NEXT, FAILED -> REVIEW, as DIP-0009 v2.0 does) or
add a header that declares the legacy keywords. A reader that must keep the
old reading can pass its own `StateConfig`.

Earlier releases (0.5.x and before) are not recorded in this file.
