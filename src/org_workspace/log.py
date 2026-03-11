"""LOGBOOK extensions and session logging.

Per-node LOGBOOK insertion at line level using _line_items.
SessionLog for per-session buffered logging.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from org_workspace._vendor.orgparse.lines import TextLine

if TYPE_CHECKING:
    from org_workspace._vendor.orgparse.node import OrgNode


def _format_timestamp(dt: datetime | None = None) -> str:
    """Format datetime as org timestamp: [YYYY-MM-DD Day HH:MM]."""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("[%Y-%m-%d %a %H:%M]")


def _find_logbook_range(node: OrgNode) -> tuple[int, int] | None:
    """Find :LOGBOOK: start and :END: indices in _line_items.

    Returns (start_idx, end_idx) or None if no LOGBOOK drawer.
    """
    start = None
    for i, item in enumerate(node._line_items):
        raw = getattr(item, "_raw", "")
        if ":LOGBOOK:" in raw:
            start = i
        elif start is not None and ":END:" in raw:
            return (start, i)
    return None


def _ensure_logbook(node: OrgNode) -> int:
    """Ensure node has a :LOGBOOK: drawer. Returns index after :LOGBOOK: line.

    Creates the drawer after the property drawer (or after heading if no props).
    """
    existing = _find_logbook_range(node)
    if existing is not None:
        return existing[0] + 1  # insert after :LOGBOOK: line

    # Find insertion point: after property drawer :END:, or after heading
    insert_at = 1  # after heading by default
    for i, item in enumerate(node._line_items):
        getattr(item, "_raw", "")
        # Look for property drawer end
        if hasattr(item, "key"):  # PropertyEntryLine — inside props
            continue
        if "PropertyDrawerEndLine" in type(item).__name__:
            insert_at = i + 1
            break
        if "PropertyDrawerStartLine" in type(item).__name__:
            continue

    # Insert :LOGBOOK: and :END:
    indent = "  "
    node._insert_line_item(insert_at, TextLine(f"{indent}:LOGBOOK:"))
    node._insert_line_item(insert_at + 1, TextLine(f"{indent}:END:"))
    return insert_at + 1  # after :LOGBOOK: line


def add_logbook_entry(
    node: OrgNode,
    message: str,
    agent: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Add a text entry to the node's :LOGBOOK: drawer.

    Creates the drawer if missing. Inserts at the top (newest first).
    """
    ts = _format_timestamp(timestamp)
    agent_part = f" by:{agent}" if agent else ""
    entry_text = f"  - {message} {ts}{agent_part}"

    insert_at = _ensure_logbook(node)
    node._insert_line_item(insert_at, TextLine(entry_text))


def add_state_change_entry(
    node: OrgNode,
    old_state: str,
    new_state: str,
    agent: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Add a state change entry to LOGBOOK.

    Format: - State "NEW" from "OLD" [timestamp] by:agent
    """
    ts = _format_timestamp(timestamp)
    agent_part = f" by:{agent}" if agent else ""
    entry = f'  - State "{new_state}" from "{old_state}" {ts}{agent_part}'

    insert_at = _ensure_logbook(node)
    node._insert_line_item(insert_at, TextLine(entry))


def add_clock_entry(
    node: OrgNode,
    start: datetime,
    end: datetime,
) -> None:
    """Add a CLOCK entry to LOGBOOK with duration.

    Format: CLOCK: [start]--[end] =>  H:MM
    """
    duration = end - start
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)

    start_ts = start.strftime("[%Y-%m-%d %a %H:%M]")
    end_ts = end.strftime("[%Y-%m-%d %a %H:%M]")
    entry = f"  CLOCK: {start_ts}--{end_ts} =>  {hours}:{minutes:02d}"

    insert_at = _ensure_logbook(node)
    node._insert_line_item(insert_at, TextLine(entry))


class SessionLog:
    """Per-session buffered log that flushes to an org-format file."""

    def __init__(self, session_id: str | None = None):
        self._session_id = session_id or str(uuid.uuid4())[:8]
        self._entries: list[dict] = []
        self._start_time = datetime.now()

    @property
    def session_id(self) -> str:
        return self._session_id

    def log(
        self,
        message: str,
        node_id: str | None = None,
        agent: str | None = None,
    ) -> None:
        """Buffer a log entry."""
        self._entries.append({
            "timestamp": datetime.now(),
            "message": message,
            "node_id": node_id,
            "agent": agent,
        })

    def flush(self, directory: Path) -> Path:
        """Write buffered entries as an org-format session file.

        Returns the path to the written file.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        filename = f"session-{self._session_id}-{self._start_time:%Y%m%d-%H%M}.org"
        path = directory / filename

        lines = [
            f"* Session {self._session_id}",
            "  :PROPERTIES:",
            f"  :SESSION_ID: {self._session_id}",
            f"  :START_TIME: {_format_timestamp(self._start_time)}",
            f"  :END_TIME: {_format_timestamp()}",
            f"  :ENTRY_COUNT: {len(self._entries)}",
            "  :END:",
        ]

        for entry in self._entries:
            ts = _format_timestamp(entry["timestamp"])
            agent_part = f" [by:{entry['agent']}]" if entry.get("agent") else ""
            node_part = f" (node:{entry['node_id']})" if entry.get("node_id") else ""
            lines.append(f"  - {ts}{agent_part}{node_part} {entry['message']}")

        path.write_text("\n".join(lines) + "\n")
        self._entries.clear()
        return path
