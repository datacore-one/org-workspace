"""NodeView: stateless, non-caching read-only view over OrgNode.

NodeView holds a reference to the underlying OrgNode plus the workspace's
StateConfig, but stores no mutable state of its own. All mutations go through
workspace methods.

NodeView instances are ephemeral — created on iteration, not cached. Staleness
is detected via a generation counter.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from org_workspace._compat import get_multiline_property
from org_workspace._types import ChecklistItem, parse_checklists

if TYPE_CHECKING:
    from org_workspace._vendor.orgparse.node import OrgNode

    from org_workspace._types import StateConfig


class StaleNodeError(Exception):
    """Raised when accessing a NodeView whose file has been reloaded."""


class NodeView:
    """Stateless view over OrgNode. No cached state, no mutation methods."""

    __slots__ = ("_node", "_path", "_state_config", "_generation", "_gen_check")

    def __init__(
        self,
        node: OrgNode,
        path: Path,
        state_config: StateConfig | None = None,
        generation: int = 0,
        gen_check: callable = None,
    ):
        self._node = node
        self._path = path
        self._state_config = state_config
        self._generation = generation
        self._gen_check = gen_check  # callable() -> current generation for path

    def _check_stale(self) -> None:
        if self._gen_check is not None:
            current = self._gen_check()
            if current != self._generation:
                raise StaleNodeError(
                    f"NodeView stale: created at gen {self._generation}, "
                    f"file now at gen {current}"
                )

    @property
    def node(self) -> OrgNode:
        """Access underlying OrgNode (for workspace mutation methods)."""
        self._check_stale()
        return self._node

    @property
    def path(self) -> Path:
        """File path this node belongs to."""
        return self._path

    @property
    def heading(self) -> str:
        self._check_stale()
        return self._node.heading

    @property
    def todo(self) -> str | None:
        self._check_stale()
        return self._node.todo

    @property
    def tags(self) -> set[str]:
        self._check_stale()
        return set(self._node.tags)

    @property
    def shallow_tags(self) -> set[str]:
        """Tags on this node only (not inherited from parents)."""
        self._check_stale()
        return set(self._node.shallow_tags) if hasattr(self._node, "shallow_tags") else self.tags

    @property
    def properties(self) -> dict:
        self._check_stale()
        return dict(self._node.properties)

    @property
    def scheduled(self):
        self._check_stale()
        return self._node.scheduled

    @property
    def deadline(self):
        self._check_stale()
        return self._node.deadline

    @property
    def closed(self):
        self._check_stale()
        return self._node.closed

    @property
    def clock(self):
        self._check_stale()
        return self._node.clock if hasattr(self._node, "clock") else []

    @property
    def body(self) -> str:
        self._check_stale()
        return self._node.body

    @property
    def level(self) -> int:
        self._check_stale()
        return self._node.level

    @property
    def parent(self) -> NodeView | None:
        self._check_stale()
        p = self._node.parent
        if p is None or p.level == 0:  # root node
            return None
        return NodeView(p, self._path, self._state_config, self._generation, self._gen_check)

    @property
    def children(self) -> list[NodeView]:
        self._check_stale()
        return [
            NodeView(c, self._path, self._state_config, self._generation, self._gen_check)
            for c in self._node.children
        ]

    @property
    def priority(self) -> str | None:
        self._check_stale()
        return self._node.priority if hasattr(self._node, "priority") else None

    def id(self) -> str | None:
        """Read :ID: property, or None if not set."""
        self._check_stale()
        return self._node.properties.get("ID")

    def get_property(self, key: str) -> str | None:
        """Read a property with multiline continuation support.

        For standard properties, returns the value directly.
        For multiline properties (`:KEY: |`), reads continuation lines
        and returns the joined value.
        """
        self._check_stale()
        return get_multiline_property(self._node, key)

    # --- Pure computation methods ---

    _EFFORT_HMM_RE = re.compile(r"^(\d+):(\d{2})$")
    _EFFORT_NH_RE = re.compile(r"^(\d+)h$", re.IGNORECASE)

    def effort_duration(self) -> timedelta | None:
        """Parse Effort property into timedelta.

        Supports: "H:MM" (e.g. "2:00"), "Nh" (e.g. "3h").
        orgparse may auto-convert to int minutes — handles that too.
        Returns None for unparseable values.
        """
        self._check_stale()
        effort = self._node.properties.get("Effort")
        if effort is None:
            return None
        # orgparse auto-converts Effort to minutes (int)
        if isinstance(effort, (int, float)):
            return timedelta(minutes=effort)
        m = self._EFFORT_HMM_RE.match(effort)
        if m:
            return timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
        m = self._EFFORT_NH_RE.match(effort)
        if m:
            return timedelta(hours=int(m.group(1)))
        return None

    def checklists(self) -> list[ChecklistItem]:
        """Parse checklist items from body text."""
        self._check_stale()
        return parse_checklists(self._node.body)

    def progress(self) -> tuple[int, int]:
        """Return (checked, total) checklist counts."""
        items = self.checklists()
        if not items:
            return (0, 0)
        checked = sum(1 for i in items if i.checked)
        return (checked, len(items))

    # --- Identity ---

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NodeView):
            return NotImplemented
        # Same underlying node object
        if self._node is other._node:
            return True
        # Fall back to ID comparison
        my_id = self._node.properties.get("ID")
        other_id = other._node.properties.get("ID")
        if my_id and other_id:
            return my_id == other_id
        # No ID: compare by (path, identity)
        return self._path == other._path and self._node is other._node

    def __hash__(self) -> int:
        node_id = self._node.properties.get("ID")
        if node_id:
            return hash(node_id)
        return hash(id(self._node))

    def __repr__(self) -> str:
        state = f" {self.todo}" if self.todo else ""
        node_id = self._node.properties.get("ID", "")
        id_part = f" [{node_id}]" if node_id else ""
        return f"<NodeView{state} '{self.heading}'{id_part}>"
