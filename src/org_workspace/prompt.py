"""PROMPT property and body-as-prompt extraction.

Provides AI execution prompt from node properties with body fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org_workspace.node_view import NodeView


def get_prompt(node: NodeView) -> str | None:
    """Get execution prompt for a node.

    Returns PROMPT property if set, otherwise falls back to body text.
    Returns None if neither is available.
    """
    prompt = node.properties.get("PROMPT")
    if prompt:
        return prompt
    body = node.body
    if body and body.strip():
        return body.strip()
    return None


def get_role(node: NodeView) -> str | None:
    """Get ROLE property for AI agent persona."""
    return node.properties.get("ROLE") or None
