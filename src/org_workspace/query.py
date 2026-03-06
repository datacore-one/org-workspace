"""Agenda, deadline, and cross-file query operations.

Provides structured queries over OrgWorkspace: agenda views, deadline tracking,
next-action selection, and filtered searches.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org_workspace.node_view import NodeView
    from org_workspace.workspace import OrgWorkspace


class Query:
    """Cross-file query engine over an OrgWorkspace."""

    def __init__(self, workspace: OrgWorkspace):
        self._ws = workspace

    def agenda(self, days: int = 7) -> list[NodeView]:
        """Return nodes SCHEDULED within the next `days` days.

        Sorted by scheduled date ascending.
        """
        today = date.today()
        end = today + timedelta(days=days)
        results = []
        for node in self._ws.all_nodes():
            sched = node.scheduled
            if sched is None:
                continue
            sched_date = _to_date(sched)
            if sched_date is None:
                continue
            if today <= sched_date <= end:
                results.append(node)
        results.sort(key=lambda n: _to_date(n.scheduled))
        return results

    def deadlines(self, days: int = 14) -> list[NodeView]:
        """Return nodes with DEADLINE within the next `days` days.

        Sorted by urgency: overdue first (most overdue first), then soonest.
        """
        today = date.today()
        end = today + timedelta(days=days)
        state_config = self._ws.state_config
        results = []
        for node in self._ws.all_nodes():
            dl = node.deadline
            if dl is None:
                continue
            # Skip terminal-state tasks
            if node.todo and state_config.is_terminal(node.todo):
                continue
            dl_date = _to_date(dl)
            if dl_date is None:
                continue
            if dl_date <= end:
                results.append(node)
        # Sort: overdue first (ascending date = most overdue first)
        results.sort(key=lambda n: _to_date(n.deadline))
        return results

    def next_action(self) -> NodeView | None:
        """Return the highest-priority TODO/NEXT task not claimed.

        Priority: [#A] > [#B] > [#C] > no priority.
        Among equal priority, NEXT before TODO.
        """
        candidates = []
        for node in self._ws.all_nodes():
            todo = node.todo
            if todo not in ("TODO", "NEXT"):
                continue
            # Skip claimed
            if node.properties.get("CLAIMED_BY"):
                continue
            candidates.append(node)

        if not candidates:
            return None

        def sort_key(n):
            prio = n.priority
            prio_rank = {"A": 0, "B": 1, "C": 2}.get(prio, 3)
            state_rank = 0 if n.todo == "NEXT" else 1
            return (prio_rank, state_rank)

        candidates.sort(key=sort_key)
        return candidates[0]

    def by_state(self, *states: str) -> list[NodeView]:
        """Find all nodes matching any of the given states."""
        return self._ws.find_by_state(*states)

    def by_tag(self, tag: str) -> list[NodeView]:
        """Find all nodes with the given tag."""
        return self._ws.find_by_tag(tag)

    def by_property(self, key: str, value: str | None = None) -> list[NodeView]:
        """Find nodes with a specific property (optionally matching value)."""
        results = []
        for node in self._ws.all_nodes():
            props = node.properties
            if key in props:
                if value is None or props[key] == value:
                    results.append(node)
        return results

    def ai_tasks(self, states: list[str] | None = None) -> list[NodeView]:
        """Find :AI: tagged tasks."""
        return self._ws.find_ai_tasks(states)

    def stale(self, days: int = 30) -> list[NodeView]:
        """Return non-terminal tasks with no activity in `days` days.

        A task is stale when ALL of its date signals are older than cutoff.
        Tasks with no date signals at all are NOT considered stale (they're
        just undated — use the file's mtime or CREATED property to determine
        actual age).
        """
        cutoff = date.today() - timedelta(days=days)
        state_config = self._ws.state_config
        results = []
        for node in self._ws.all_nodes():
            todo = node.todo
            if not todo:
                continue
            if state_config.is_terminal(todo):
                continue

            # Collect all date signals for this node
            has_any_date = False
            is_recent = False

            for date_val in (node.closed, node.scheduled, node.deadline):
                d = _to_date(date_val)
                if d is not None:
                    has_any_date = True
                    if d >= cutoff:
                        is_recent = True
                        break

            # Check CREATED property as fallback
            if not has_any_date:
                created = node.properties.get("CREATED")
                if created:
                    has_any_date = True
                    created_date = _parse_org_date_string(created)
                    if created_date and created_date >= cutoff:
                        is_recent = True

            if is_recent:
                continue

            # Only flag as stale if there IS a date signal that's old.
            # No dates = undated, not stale.
            if has_any_date:
                results.append(node)

        return results

    def overdue(self) -> list[NodeView]:
        """Return tasks past their DEADLINE that are not in terminal state."""
        today = date.today()
        state_config = self._ws.state_config
        results = []
        for node in self._ws.all_nodes():
            dl = node.deadline
            if dl is None:
                continue
            if node.todo and state_config.is_terminal(node.todo):
                continue
            dl_date = _to_date(dl)
            if dl_date and dl_date < today:
                results.append(node)
        results.sort(key=lambda n: _to_date(n.deadline))
        return results


def _parse_org_date_string(value: str) -> date | None:
    """Parse an org-mode timestamp string like [2025-01-01 Wed 10:00] to date."""
    if not value:
        return None
    # Extract YYYY-MM-DD from org timestamps
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


def _to_date(value) -> date | None:
    """Convert orgparse date value to date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # orgparse OrgDate wrapper (scheduled/deadline/closed return OrgDate
    # even when no date is set — check start for None)
    if hasattr(value, "start"):
        start = value.start
        if start is None:
            return None
        if isinstance(start, datetime):
            return start.date()
        if isinstance(start, date):
            return start
    return None
