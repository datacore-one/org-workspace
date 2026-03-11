"""Identifier management: auto-ID generation and cross-file resolution."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org_workspace._vendor.orgparse.node import OrgNode


class DuplicateIdError(Exception):
    """Raised when the same :ID: appears in multiple nodes (INV-3)."""


def generate_id(
    heading: str,
    timestamp: datetime | None = None,
    disambiguator: str | None = None,
) -> str:
    """Generate a content-addressed ID from heading text.

    Format: org-YYYYMMDD-HHMMSS-{sha256(heading)[:8]}

    The hash enables deduplication: same heading → same hash suffix.
    The timestamp provides creation context and uniqueness.

    If disambiguator is provided, it's mixed into the hash to produce
    a unique ID even for identical headings created at the same time.
    """
    ts = timestamp or datetime.now()
    hash_input = heading if disambiguator is None else f"{heading}\0{disambiguator}"
    content_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
    return f"org-{ts.strftime('%Y%m%d-%H%M%S')}-{content_hash}"


def heading_hash(heading: str) -> str:
    """Return the 8-char content hash for a heading.

    Used for dedup checks independent of timestamp.
    """
    return hashlib.sha256(heading.encode()).hexdigest()[:8]


def ensure_id(node: OrgNode) -> str:
    """Ensure node has an :ID: property. Generates content-addressed ID if missing.

    Returns the (possibly new) ID value.
    """
    existing = node.properties.get("ID")
    if existing:
        return existing

    new_id = generate_id(node.heading)
    props = dict(node.properties)
    props["ID"] = new_id
    node.properties = props
    return new_id


class IdIndex:
    """Cross-file ID resolution index.

    Maintains a mapping from :ID: values to (path, node) tuples.
    Enforces INV-3: no duplicate IDs within a workspace.
    """

    def __init__(self) -> None:
        self._index: dict[str, tuple[Path, OrgNode]] = {}

    def add_file(self, path: Path, root) -> None:
        """Index all nodes with :ID: properties from a parsed file.

        Args:
            path: File path for reference
            root: Parsed OrgRootNode

        Raises:
            DuplicateIdError: If any ID already exists in the index (INV-3)
        """
        for node in root.children:
            self._add_subtree(path, node)

    def _add_subtree(self, path: Path, node: OrgNode) -> None:
        node_id = node.properties.get("ID")
        if node_id:
            if node_id in self._index:
                existing_path, _ = self._index[node_id]
                raise DuplicateIdError(
                    f"Duplicate ID '{node_id}' found in {path} and {existing_path}"
                )
            self._index[node_id] = (path, node)
        for child in node.children:
            self._add_subtree(path, child)

    def resolve(self, node_id: str) -> tuple[Path, OrgNode] | None:
        """Resolve an ID to its (path, node) tuple, or None."""
        return self._index.get(node_id)

    def duplicates(self) -> list[str]:
        """Return list of duplicate IDs. (Always empty if add_file enforced.)"""
        # This exists for diagnostic use; add_file prevents duplicates
        return []

    def remove_file(self, path: Path) -> None:
        """Remove all entries for a file (used on reload)."""
        to_remove = [k for k, (p, _) in self._index.items() if p == path]
        for k in to_remove:
            del self._index[k]

    def __len__(self) -> int:
        return len(self._index)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._index
