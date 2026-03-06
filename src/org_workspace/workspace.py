"""OrgWorkspace: multi-file container with all mutation methods.

The workspace owns all mutations. NodeView is read-only.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

from orgparse import dumps as _orgparse_dumps
from orgparse import load
from orgparse.node import OrgNode, OrgRootNode

from org_workspace._compat import dumps
from org_workspace._types import StateConfig
from org_workspace.identifiers import IdIndex
from org_workspace.node_view import NodeView


class InvalidTransitionError(Exception):
    """Raised when a state transition violates StateConfig rules."""


class OrgWorkspace:
    """Multi-file org-mode workspace with mutation tracking.

    All mutation methods mark affected files dirty and validate invariants.
    """

    def __init__(
        self,
        roots: list[Path] | None = None,
        state_config: StateConfig | None = None,
    ):
        self._state_config = state_config or StateConfig.default()
        self._files: dict[Path, OrgRootNode] = {}
        self._dirty: set[Path] = set()
        self._generations: dict[Path, int] = {}
        self._id_index = IdIndex()

        if roots:
            for root in roots:
                path = Path(root)
                if path.is_dir():
                    for f in sorted(path.glob("*.org")):
                        self.load(f)
                elif path.is_file():
                    self.load(path)

    @property
    def state_config(self) -> StateConfig:
        return self._state_config

    # --- File operations ---

    def load(self, path: Path) -> None:
        """Load or reload an org file into the workspace."""
        path = Path(path).resolve()
        # If reloading, remove old index entries and bump generation
        if path in self._files:
            self._id_index.remove_file(path)
        root = load(str(path))
        self._files[path] = root
        self._dirty.discard(path)
        self._generations[path] = self._generations.get(path, 0) + 1
        self._id_index.add_file(path, root)

    def reload(self, path: Path) -> None:
        """Reload a file from disk, invalidating existing NodeViews."""
        self.load(path)

    def _reload_preserving_dirty(self, path: Path) -> None:
        """Reload a file without clearing its dirty status."""
        path = Path(path).resolve()
        if path in self._files:
            self._id_index.remove_file(path)
        root = load(str(path))
        self._files[path] = root
        self._generations[path] = self._generations.get(path, 0) + 1
        self._id_index.add_file(path, root)

    def files(self) -> dict[Path, OrgRootNode]:
        return dict(self._files)

    def file_paths(self) -> list[Path]:
        return list(self._files.keys())

    # --- Node iteration and lookup ---

    def _make_view(self, node: OrgNode, path: Path) -> NodeView:
        gen = self._generations.get(path, 0)
        return NodeView(
            node, path, self._state_config, gen,
            gen_check=lambda p=path: self._generations.get(p, 0),
        )

    def _iter_nodes(self, root: OrgNode, path: Path) -> Iterator[NodeView]:
        for child in root.children:
            yield self._make_view(child, path)
            yield from self._iter_nodes(child, path)

    def all_nodes(self) -> Iterator[NodeView]:
        """Iterate all nodes across all loaded files."""
        for path, root in self._files.items():
            yield from self._iter_nodes(root, path)

    def find_by_id(self, node_id: str) -> NodeView | None:
        """Find a node by :ID: property across all files."""
        result = self._id_index.resolve(node_id)
        if result is None:
            return None
        path, node = result
        return self._make_view(node, path)

    def find_by_state(self, *states: str) -> list[NodeView]:
        """Find all nodes matching any of the given states."""
        state_set = set(states)
        return [n for n in self.all_nodes() if n.todo in state_set]

    def find_by_tag(self, tag: str) -> list[NodeView]:
        """Find all nodes with the given tag."""
        return [n for n in self.all_nodes() if tag in n.tags]

    def find_ai_tasks(self, states: list[str] | None = None) -> list[NodeView]:
        """Find nodes tagged with :AI: (optionally filtered by state)."""
        results = []
        for n in self.all_nodes():
            tags = n.tags
            is_ai = any(t == "AI" or t.startswith("AI") for t in tags)
            if not is_ai:
                # Check shallow tags for AI prefix
                continue
            if states and n.todo not in states:
                continue
            results.append(n)
        return results

    # --- Mutation methods (all mark dirty, all validate invariants) ---

    def _mark_dirty(self, path: Path) -> None:
        self._dirty.add(path)

    def transition(
        self,
        node: NodeView,
        new_state: str,
        agent: str | None = None,
    ) -> None:
        """Change a node's TODO state with validation.

        INV-4: Only valid transitions allowed.
        Sets CLOSED timestamp when transitioning to terminal state.
        Sets COMPLETED_BY when agent is provided.
        """
        old_state = node.todo
        if old_state == new_state:
            return

        # Validate transition
        if old_state and not self._state_config.can_transition(old_state, new_state):
            raise InvalidTransitionError(
                f"Cannot transition from {old_state} to {new_state}"
            )
        if new_state not in self._state_config.all_states:
            raise InvalidTransitionError(
                f"Unknown state: {new_state}"
            )

        raw_node = node.node  # checks staleness
        raw_node.todo = new_state
        self._mark_dirty(node.path)

        # Terminal state: set CLOSED timestamp
        if self._state_config.is_terminal(new_state):
            now = datetime.now()
            raw_node.closed = now

        # Agent attribution
        if agent:
            self.set_property(node, "COMPLETED_BY", agent)

    def set_property(self, node: NodeView, key: str, value: str) -> None:
        """Set a property on a node using read-copy-merge-assign protocol."""
        raw_node = node.node
        props = dict(raw_node.properties)
        props[key] = value
        raw_node.properties = props
        self._mark_dirty(node.path)

    def set_heading(self, node: NodeView, text: str) -> None:
        """Change a node's heading text."""
        raw_node = node.node
        raw_node.heading = text
        self._mark_dirty(node.path)

    def set_tags(self, node: NodeView, tags: list[str]) -> None:
        """Set tags on a node."""
        raw_node = node.node
        raw_node.tags = tags
        self._mark_dirty(node.path)

    def update_progress_cookie(self, node: NodeView) -> None:
        """Rewrite [n/m] progress cookie in heading based on checklist counts."""
        checked, total = node.progress()
        if total == 0:
            return
        raw_node = node.node
        heading = raw_node.heading
        # Replace existing cookie or prepend
        new_cookie = f"[{checked}/{total}]"
        if re.search(r"\[\d+/\d+\]", heading):
            new_heading = re.sub(r"\[\d+/\d+\]", new_cookie, heading)
        else:
            new_heading = f"{new_cookie} {heading}"
        if new_heading != heading:
            raw_node.heading = new_heading
            self._mark_dirty(node.path)

    # --- Structural mutations ---

    def create_node(
        self,
        file: Path,
        heading: str,
        state: str | None = None,
        parent: NodeView | None = None,
        level: int | None = None,
        tags: list[str] | None = None,
        body: str | None = None,
        **props: str,
    ) -> NodeView:
        """Create a new node in the specified file.

        Uses text-append-and-reload approach because orgparse's children
        setter requires same OrgEnv, and loads() creates a separate env.
        """
        file = Path(file).resolve()
        if file not in self._files:
            raise ValueError(f"File not loaded: {file}")

        # Determine level
        if parent is not None:
            target_level = parent.level + 1
        elif level is not None:
            target_level = level
        else:
            target_level = 1

        # Build org string
        stars = "*" * target_level
        state_part = f" {state}" if state else ""
        tag_part = ""
        if tags:
            tag_str = ":".join(tags)
            tag_part = f" :{tag_str}:"
        org_lines = [f"{stars}{state_part} {heading}{tag_part}"]

        # Indent: 2 spaces per level (standard)
        indent = "  "
        if props:
            org_lines.append(f"{indent}:PROPERTIES:")
            for k, v in props.items():
                org_lines.append(f"{indent}:{k}: {v}")
            org_lines.append(f"{indent}:END:")

        if body:
            for line in body.split("\n"):
                org_lines.append(f"{indent}{line}")

        new_text = "\n".join(org_lines) + "\n"

        # Get current content, append new node text, write, reload
        current_content = dumps(self._files[file])

        # Append to file content
        # When parent is specified, the star level handles nesting correctly
        # (orgparse determines hierarchy by heading level)
        combined = current_content + new_text
        file.write_text(combined)

        # Reload to get proper OrgNode in the right env
        self._reload_preserving_dirty(file)
        self._mark_dirty(file)

        # Find the new node by ID or by heading match at end
        node_id = props.get("ID")
        if node_id:
            result = self.find_by_id(node_id)
            if result:
                return result

        # Fallback: find by heading (last match at correct level)
        for n in reversed(list(self.all_nodes())):
            if n.path == file and n.heading == heading and n.level == target_level:
                return n

        raise RuntimeError("Failed to locate newly created node after reload")

    def remove_node(self, node: NodeView) -> None:
        """Remove a node from its parent (detach from tree)."""
        raw_node = node.node
        parent = raw_node.parent
        if parent is None:
            raise ValueError("Cannot remove root node")

        parent.children = [c for c in parent.children if c is not raw_node]
        self._mark_dirty(node.path)

        # Remove from ID index
        node_id = raw_node.properties.get("ID")
        if node_id and node_id in self._id_index:
            self._id_index.remove_file(node.path)
            self._id_index.add_file(node.path, self._files[node.path])

    def refile(
        self,
        node: NodeView,
        target_file: Path,
        target_parent: NodeView | None = None,
    ) -> NodeView:
        """Move a node from its current file to another file.

        Uses text-level operations: serialize subtree, remove from source,
        append to target, reload both. This avoids OrgEnv mismatch.
        """
        target_file = Path(target_file).resolve()
        if target_file not in self._files:
            raise ValueError(f"Target file not loaded: {target_file}")

        raw_node = node.node
        source_file = node.path
        node_id = raw_node.properties.get("ID")

        # Serialize the subtree text
        subtree_text = _orgparse_dumps(raw_node)
        if not subtree_text.endswith("\n"):
            subtree_text += "\n"

        # Remove from source tree
        parent = raw_node.parent
        if parent is None:
            raise ValueError("Cannot refile root node")
        parent.children = [c for c in parent.children if c is not raw_node]

        # Save source to disk
        source_content = dumps(self._files[source_file])
        source_file.write_text(source_content)

        # Append to target file on disk
        target_content = dumps(self._files[target_file])
        target_file.write_text(target_content + subtree_text)

        # Reload both files
        self._reload_preserving_dirty(source_file)
        self._reload_preserving_dirty(target_file)
        self._mark_dirty(source_file)
        self._mark_dirty(target_file)

        # Find the refiled node in the target
        if node_id:
            result = self.find_by_id(node_id)
            if result:
                return result

        # Fallback: last node in target matching heading
        heading = raw_node.heading
        for n in reversed(list(self.all_nodes())):
            if n.path == target_file and n.heading == heading:
                return n

        raise RuntimeError("Failed to locate refiled node")

    # --- Save / dirty tracking ---

    def dirty_files(self) -> set[Path]:
        """Return set of files with unsaved mutations."""
        return set(self._dirty)

    def save(self, path: Path | None = None, lock: bool = False) -> None:
        """Save dirty file(s) to disk.

        If path is given, saves only that file.
        Otherwise saves all dirty files.
        """
        if path is not None:
            path = Path(path).resolve()
            self._save_file(path)
        else:
            for p in list(self._dirty):
                self._save_file(p)

    def _save_file(self, path: Path) -> None:
        if path not in self._files:
            raise ValueError(f"File not loaded: {path}")
        if path not in self._dirty:
            return
        content = dumps(self._files[path])
        path.write_text(content)
        self._dirty.discard(path)

    def save_all(self) -> None:
        """Save all dirty files."""
        self.save()
