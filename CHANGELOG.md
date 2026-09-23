# Changelog

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
