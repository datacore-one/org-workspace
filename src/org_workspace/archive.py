"""Archive operations for completed tasks and plans.

Per DIP-0009 §8.4:
- Target: sibling file (next_actions.org -> next_actions_archive.org)
- Adds :ARCHIVE_TIME: and :ARCHIVE_REASON: properties
- Focus area (**) and tier (*) headings are structural — never archived
- Project headings kept until ALL children archived
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from org_workspace.node_view import StaleNodeError
from org_workspace.query import _to_date

if TYPE_CHECKING:
    from org_workspace.node_view import NodeView
    from org_workspace.plan import Plan
    from org_workspace.workspace import OrgWorkspace


def default_archive_path(source: Path) -> Path:
    """Compute DIP-0009 archive sibling path.

    next_actions.org -> next_actions_archive.org
    """
    return source.with_name(source.stem + "_archive" + source.suffix)


def archive_node(
    workspace: OrgWorkspace,
    node: NodeView,
    target: Path | None = None,
    reason: str = "completed",
) -> str:
    """Archive a single node to the target archive file.

    Sets :ARCHIVE_TIME: and :ARCHIVE_REASON: before moving.
    Mirrors the source heading hierarchy in the archive file (DIP-0009).
    Refuses to archive structural headings (level <= 2).

    Returns the node ID or heading for confirmation.
    """
    # Capture metadata before any reloads make the view stale
    identifier = node.id() or node.heading
    level = node.level
    source_path = node.path

    if level <= 2:
        raise ValueError(
            f"Cannot archive structural heading (level {level}): {identifier}"
        )

    # Capture ancestor chain for hierarchy mirroring
    ancestor_headings = _get_ancestor_headings(node)

    if target is None:
        target = default_archive_path(source_path)

    # Ensure target file exists and is loaded
    _ensure_archive_file(workspace, target)

    # Create/find matching hierarchy in archive file
    archive_parent = _ensure_archive_hierarchy(workspace, target, ancestor_headings)

    # Re-resolve node after potential file load and hierarchy creation
    node_id = node._node.properties.get("ID")
    if node_id:
        node = workspace.find_by_id(node_id)
        if node is None:
            raise RuntimeError(f"Failed to re-resolve node {node_id}")

    # Set archive properties
    now = datetime.now()
    workspace.set_property(node, "ARCHIVE_TIME", now.strftime("[%Y-%m-%d %a %H:%M]"))
    workspace.set_property(node, "ARCHIVE_REASON", reason)

    # Refile to archive under matching hierarchy
    workspace.refile(node, target, target_parent=archive_parent)

    return identifier


def archive_plan(
    workspace: OrgWorkspace,
    plan: "Plan",
    target: Path | None = None,
    reason: str = "plan completed",
) -> list[str]:
    """Archive an entire plan (root + all children).

    Returns list of archived node identifiers.
    """
    root = plan.root
    # Capture identifiers before any reloads
    identifiers = [root.id() or root.heading]
    for step in plan.steps():
        identifiers.append(step.id() or step.heading)

    source_path = root.path
    root_id = root.id()

    if target is None:
        target = default_archive_path(source_path)

    _ensure_archive_file(workspace, target)

    # Re-resolve root after potential file load
    if root_id:
        root = workspace.find_by_id(root_id)
        if root is None:
            raise RuntimeError(f"Failed to re-resolve plan root {root_id}")

    # Set archive properties on root
    now = datetime.now()
    workspace.set_property(root, "ARCHIVE_TIME", now.strftime("[%Y-%m-%d %a %H:%M]"))
    workspace.set_property(root, "ARCHIVE_REASON", reason)

    # Refile root (includes all children)
    workspace.refile(root, target)

    return identifiers


def archive_done(
    workspace: OrgWorkspace,
    older_than_days: int = 30,
    min_level: int = 3,
) -> list[str]:
    """Batch archive terminal-state tasks older than `older_than_days`.

    Skips structural headings (level < min_level).
    Returns list of archived node identifiers.
    """
    cutoff = date.today() - timedelta(days=older_than_days)
    state_config = workspace.state_config
    archived = []

    # Collect candidate IDs first (NodeViews go stale after each archive)
    candidate_ids = []
    for node in workspace.all_nodes():
        todo = node.todo
        if not todo or not state_config.is_terminal(todo):
            continue
        if node.level < min_level:
            continue

        closed = node.closed
        if closed is None:
            continue
        closed_date = _to_date(closed)
        if closed_date is None or closed_date >= cutoff:
            continue

        node_id = node.id()
        if node_id:
            candidate_ids.append(node_id)

    # Archive each candidate by re-resolving fresh NodeView
    for node_id in candidate_ids:
        node = workspace.find_by_id(node_id)
        if node is None:
            continue
        try:
            identifier = archive_node(workspace, node, reason="auto-archived (done)")
            archived.append(identifier)
        except (ValueError, RuntimeError, StaleNodeError):
            continue

    return archived


def _get_ancestor_headings(node: "NodeView") -> list[str]:
    """Walk up the tree to collect ancestor headings (excluding root).

    Returns list from top to bottom, e.g. ["Personal", "Health"] for a
    node at `* Personal / ** Health / *** Buy vitamins`.
    Only includes structural ancestors (level < node.level).
    """
    ancestors = []
    current = node.parent
    while current is not None:
        ancestors.append(current.heading)
        current = current.parent
    ancestors.reverse()
    return ancestors


def _ensure_archive_hierarchy(
    workspace: "OrgWorkspace",
    archive_path: Path,
    ancestor_headings: list[str],
) -> "NodeView | None":
    """Find or create matching heading hierarchy in the archive file.

    Given ancestors ["Personal", "Health"], ensures the archive file has:
        * Personal
        ** Health

    Returns the deepest parent NodeView, or None if no ancestors.
    """
    if not ancestor_headings:
        return None

    archive_path = Path(archive_path).resolve()
    current_parent = None

    for depth, heading in enumerate(ancestor_headings):
        target_level = depth + 1

        # Search for existing heading at this level under current_parent
        found = None
        for n in workspace.all_nodes():
            if n.path != archive_path:
                continue
            if n.heading == heading and n.level == target_level:
                # Check parentage matches
                if current_parent is None and n.parent is None:
                    found = n
                    break
                if current_parent is not None and n.parent is not None:
                    if n.parent.heading == current_parent.heading:
                        found = n
                        break

        if found is not None:
            current_parent = found
        else:
            # Create the structural heading
            current_parent = workspace.create_node(
                archive_path,
                heading,
                parent=current_parent,
                level=target_level if current_parent is None else None,
            )

    return current_parent


def _ensure_archive_file(workspace: "OrgWorkspace", path: Path) -> None:
    """Ensure archive file exists and is loaded in workspace."""
    path = Path(path).resolve()
    if path not in workspace.files():
        if not path.exists():
            path.write_text("")
        workspace.load(path)
