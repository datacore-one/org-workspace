"""Compatibility layer for orgparse PR #77.

Provides:
- Import-time assertions that orgparse has the required internals
- Multiline property get/set (Datacore extension: `:KEY: |` continuation)
- Round-trip safe dumps wrapper
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from org_workspace._vendor.orgparse import dumps as _orgparse_dumps
from org_workspace._vendor.orgparse.lines import TextLine
from org_workspace._vendor.orgparse.node import OrgNode

if TYPE_CHECKING:
    from org_workspace._vendor.orgparse.node import OrgBaseNode

# --- Compatibility assertions ---
# Fail fast if vendored orgparse has the required internals (PR #77 features)
# _line_items is an instance attr (set in __init__), so we probe a parsed node.
from org_workspace._vendor.orgparse import loads as _loads

_probe = _loads("* probe\n").children[0]
assert hasattr(_probe, "_line_items"), (
    "orgparse missing _line_items — requires PR #77 fork "
    "(github.com/datacore-one/orgparse branch pr-77)"
)
assert hasattr(_probe, "_insert_line_item"), (
    "orgparse missing _insert_line_item — requires PR #77 fork"
)
assert hasattr(_probe, "_remove_line_item"), (
    "orgparse missing _remove_line_item — requires PR #77 fork"
)
del _probe, _loads


def dumps(root: OrgBaseNode) -> str:
    """Round-trip safe dumps: preserves trailing newline if original had one."""
    result = _orgparse_dumps(root)
    # orgparse dumps() strips trailing newline; we restore it for file round-trip
    if not result.endswith("\n"):
        result += "\n"
    return result


# --- Multiline property support ---
# Datacore extension: properties can span multiple lines using `|` continuation:
#   :CONTEXT: |
#   :   First line
#   :   Second line
#
# orgparse sees the first line as `|` and ignores continuations.
# We parse them from the raw line items.

_MULTILINE_CONT_RE = re.compile(r"^\s*:\s{3}(.*)$")


def get_multiline_property(node: OrgNode, key: str) -> str | None:
    """Read a multiline property value from a node.

    For single-line properties, returns the value directly.
    For multiline (value == '|'), reads continuation lines from the property
    drawer and joins them.
    """
    value = node.properties.get(key)
    if value is None:
        return None
    # orgparse may auto-convert some properties (e.g. Effort -> int minutes)
    if not isinstance(value, str):
        return value
    if value != "|":
        return value

    # Find the property line in _line_items and read continuations
    # Line items have _raw attribute with the original text
    lines = []
    found_key = False
    for item in node._line_items:
        raw = getattr(item, "_raw", "")
        if not found_key:
            # Look for PropertyEntryLine with matching key
            if hasattr(item, "key") and item.key == key:
                found_key = True
            continue
        # After finding the key, read continuation lines (TextLine with :   prefix)
        m = _MULTILINE_CONT_RE.match(raw)
        if m:
            lines.append(m.group(1))
        else:
            break

    return "\n".join(lines) if lines else "|"


def set_multiline_property(node: OrgNode, key: str, value: str) -> None:
    """Set a multiline property on a node.

    If value contains newlines, writes as multiline with `|` continuation.
    Otherwise writes as a normal single-line property.

    Uses the read-copy-merge-assign protocol for the properties dict.
    """
    lines = value.split("\n")
    if len(lines) == 1:
        # Single-line: use normal property setter
        props = dict(node.properties)
        props[key] = value
        node.properties = props
        return

    # Multiline: set the marker value, then insert continuation lines
    props = dict(node.properties)
    props[key] = "|"
    node.properties = props

    # Find the property line in _line_items and replace/insert continuations
    for i, item in enumerate(node._line_items):
        if hasattr(item, "key") and item.key == key:
            # Remove existing continuation lines
            j = i + 1
            while j < len(node._line_items):
                raw = getattr(node._line_items[j], "_raw", "")
                if _MULTILINE_CONT_RE.match(raw):
                    node._remove_line_item(j)
                else:
                    break
            # Insert new continuation lines (reverse order for correct positioning)
            indent = "  "  # standard org property drawer indent
            for line in reversed(lines):
                cont_text = f"{indent}:   {line}"
                node._insert_line_item(i + 1, TextLine(cont_text))
            break
