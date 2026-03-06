"""Runtime context assembly for AI task execution.

Extracts CONTEXT, KEY_FILES, REFS, ACCEPTANCE_CRITERIA, ROLE, TOOLS from
node properties. Supports multiline properties via _compat layer.

Engram resolution is a caller responsibility — this module provides hooks
for context assembly; the caller provides engrams.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from org_workspace._compat import get_multiline_property
from org_workspace.prompt import get_prompt, get_role

if TYPE_CHECKING:
    from org_workspace.node_view import NodeView


def get_context(node: NodeView) -> dict:
    """Extract structured context from node properties.

    Returns dict with keys: context, key_files, acceptance_criteria, role, tools.
    Only includes keys that have values.
    """
    result = {}
    raw_node = node.node

    # Multiline properties
    for prop, key in [
        ("CONTEXT", "context"),
        ("ACCEPTANCE_CRITERIA", "acceptance_criteria"),
        ("TOOLS", "tools"),
    ]:
        value = get_multiline_property(raw_node, prop)
        if not value:
            value = node.properties.get(prop)
        if value and value != "|":
            result[key] = value

    # Role
    role = get_role(node)
    if role:
        result["role"] = role

    # KEY_FILES / REFS
    refs = get_refs(node)
    if refs:
        result["key_files"] = refs

    return result


def get_refs(node: NodeView) -> list[str]:
    """Parse REFS or KEY_FILES property into list of paths.

    Handles both multiline (pipe continuation) and comma/newline separated.
    """
    raw_node = node.node
    for prop in ("KEY_FILES", "REFS"):
        value = get_multiline_property(raw_node, prop)
        if not value:
            value = node.properties.get(prop)
        if value and value != "|":
            # Split by newlines and commas
            paths = []
            for line in value.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Handle comma-separated within a line
                for part in line.split(","):
                    part = part.strip()
                    if part:
                        paths.append(part)
            return paths
    return []


def build_execution_context(
    node: NodeView,
    engrams: list[str] | None = None,
    extra_context: dict | None = None,
) -> dict:
    """Assemble complete execution context for AI task.

    Aggregates prompt, structured context, refs, and caller-provided engrams.
    """
    result = {}

    # Prompt
    prompt = get_prompt(node)
    if prompt:
        result["prompt"] = prompt

    # Structured context from properties
    ctx = get_context(node)
    result.update(ctx)

    # Engrams (caller-provided, not stored on node)
    if engrams:
        result["engrams"] = engrams

    # Extra context
    if extra_context:
        result.update(extra_context)

    return result
