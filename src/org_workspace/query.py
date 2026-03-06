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

        Checks CLOSED timestamp and SCHEDULED date. Tasks without any
        date reference are considered stale if they exist.
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
            # Check if there's recent activity
            closed = node.closed
            if closed:
                closed_date = _to_date(closed)
                if closed_date and closed_date >= cutoff:
                    continue

            sched = node.scheduled
            if sched:
                sched_date = _to_date(sched)
                if sched_date and sched_date >= cutoff:
                    continue

            dl = node.deadline
            if dl:
                dl_date = _to_date(dl)
                if dl_date and dl_date >= cutoff:
                    continue

            # No recent timestamps — consider stale
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


def _to_date(value) -> date | None:
    """Convert orgparse date value to date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # orgparse OrgDate wrapper
    if hasattr(value, "start"):
        start = value.start
        if isinstance(start, datetime):
            return start.date()
        if isinstance(start, date):
            return start
    return None
