"""Process inbox.org: route items to research_learning.org and next_actions.org.

One-time script. Uses org-workspace API for all operations.
"""

from pathlib import Path
from org_workspace.workspace import OrgWorkspace

import sys

# Use copies for dry run, real files for production
if "--real" in sys.argv:
    PERSONAL = Path("/Users/gregor/Data/0-personal/org")
else:
    PERSONAL = Path("/tmp/inbox-test")
    print("*** DRY RUN on copies ***\n")

INBOX = PERSONAL / "inbox.org"
NA = PERSONAL / "next_actions.org"
RL = PERSONAL / "research_learning.org"


def find_node(ws, path, heading_prefix, level=None):
    """Find a node by heading prefix in a specific file."""
    path = path.resolve()
    for n in ws.all_nodes():
        if n.path != path:
            continue
        if level and n.level != level:
            continue
        if n.heading.startswith(heading_prefix):
            return n
    return None


def find_or_create_focus_area(ws, path, tier_heading, focus_heading):
    """Find or create a focus area (L2) under a tier (L1) in target file."""
    path = path.resolve()
    # Find the tier
    tier = find_node(ws, path, tier_heading, level=1)
    if tier is None:
        raise RuntimeError(f"Tier '{tier_heading}' not found in {path.name}")

    # Find focus area under tier
    for n in ws.all_nodes():
        if n.path != path or n.level != 2:
            continue
        if n.heading == focus_heading and n.parent and n.parent.heading.startswith(tier_heading):
            return n

    # Create it
    return ws.create_node(path, focus_heading, parent=tier, level=None)


def refile_inbox_item(ws, heading_prefix, target_path, target_parent, tags=None, extra_body=None):
    """Find an inbox item by heading prefix, optionally set tags, refile to target."""
    node = find_node(ws, INBOX, heading_prefix, level=2)
    if node is None:
        # Try level 3 (for nested items we might want individually)
        node = find_node(ws, INBOX, heading_prefix)
    if node is None:
        print(f"  SKIP (not found): {heading_prefix[:60]}")
        return False

    heading = node.heading[:60]

    # Set tags if provided
    if tags:
        existing = list(node.tags)
        for t in tags:
            if t not in existing:
                existing.append(t)
        ws.set_tags(node, existing)

    # Refile
    ws.refile(node, target_path, target_parent=target_parent)
    print(f"  OK: {heading}")
    return True


def main():
    ws = OrgWorkspace(roots=[INBOX, NA, RL])
    print(f"Loaded: inbox={sum(1 for n in ws.all_nodes() if n.path == INBOX.resolve())} nodes")
    print(f"        na={sum(1 for n in ws.all_nodes() if n.path == NA.resolve())} nodes")
    print(f"        rl={sum(1 for n in ws.all_nodes() if n.path == RL.resolve())} nodes")
    print()

    # =========================================================================
    # PHASE 1: Research items → research_learning.org
    # =========================================================================
    print("=== PHASE 1: Research → research_learning.org ===")

    # Research routing table: (heading_prefix, focus_area_heading)
    research_items = [
        # Technology & Innovation
        ("Building one AI brain for every robot", "Technology & Innovation"),
        ("Agents self-improve as Stanford", "Technology & Innovation"),
        ("AI beyond chatbots in 2026", "Technology & Innovation"),
        ("Coinbase rolls out AI tool", "Technology & Innovation"),
        ("Sigil Wen on X", "Technology & Innovation"),
        ("OpenClaw Users Are Allegedly", "Technology & Innovation"),
        ("NullClaw Packs AI Agent", "Technology & Innovation"),
        ("John McBride on X", "Technology & Innovation"),
        ("Zerg.App", "Technology & Innovation"),
        ("An AI Agent Published a Hit Piece", "Technology & Innovation"),

        # Verity (data markets, privacy, Dubai)
        ("Meta\u2019s AI Smart Glasses", "Verity"),
        ("Guri Singh on X", "Verity"),  # Stanford privacy policies
        ("Very important! Should be researched", "Verity"),  # RDA cluster (has children)
        ("Decentralized AI Company 0G", "Verity"),
        ("Dubai Municipality launches DANA", "Verity"),  # Dubai → Verity pilot
        ("Dubai Land Department", "Verity"),  # Dubai → Verity pilot
        ("GITEX Global 2025: Dubai Municipality", "Verity"),  # Dubai → Verity
        ("[[https://www.gitex.com/media/gitex-global-2025-dubai-government", "Verity"),  # GITEX

        # Business & Strategy
        ("Abu Dhabi\u2019s MGX Targets", "Business & Strategy"),
        ("Just 8 months in, India's vibe-coding", "Business & Strategy"),
        ("AI consultancy start-ups cut", "Business & Strategy"),
        ("a16z: The Power Brokers", "Business & Strategy"),
        ("Some Simple Economics of AGI", "Business & Strategy"),

        # Health & Longevity
        ("Billing bottlenecks? Ease Health", "Health & Longevity"),
        ("Mental Health Startup Grow Therapy", "Health & Longevity"),
        ("Bryan Johnson's Protocol", "Health & Longevity"),  # "download, research, integrate"
        ("research heart health", "Health & Longevity"),  # cluster with 3 children

        # Datacore
        ("Bankr", "Datacore"),  # "agent data exchange or datacore"
        ("campfirium/obsidian-tile-line-base", "Datacore"),
        ("tobi/qmd", "Datacore"),  # "compare to datacortex"
        ("manaflow-ai/cmux", "Datacore"),
        ("[[https://x.com/elvissun/status", "Datacore"),  # OpenClaw + Codex swarm

        # Personal
        ("Thoughts on the 700 page reality transurfing", "Personal"),
        ("pashov/skills: Pashov Audit Group", "Technology & Innovation"),  # smart contract skills

        # Datafund
        ("Akshay", "Technology & Innovation"),  # Sim platform

        # Videos to transcribe
        ("(37) Claude Code's Creator Does This", "Datacore"),  # transcribe for workflow
        ("(37) The design process is dead", "Technology & Innovation"),  # transcribe for trends

        # Brickroad cluster → Verity (compare to verity)
        ("Important, check it out! Compare to verity", "Verity"),
    ]

    for heading_prefix, focus_area in research_items:
        # Find the focus area in research_learning.org
        parent = find_node(ws, RL, focus_area, level=2)
        if parent is None:
            print(f"  WARN: Focus area '{focus_area}' not found in RL, creating...")
            tier = find_node(ws, RL, "RESEARCH & LEARNING", level=1)
            parent = ws.create_node(RL, focus_area, parent=tier)

        tags = ["AI", "research"]
        refile_inbox_item(ws, heading_prefix, RL, parent, tags=tags)

    # =========================================================================
    # PHASE 2: Actionable items → next_actions.org
    # =========================================================================
    print()
    print("=== PHASE 2: Actions → next_actions.org ===")

    action_items = [
        # (heading_prefix, focus_area_heading, tier_prefix)
        ("Continue: Finalise cap table", "/Datafund (Core Operations)", "TIER 1"),
        ("Staging deploys go to wrong server", "/FDS (Fair Data Society)", "TIER 2"),
        ("Reconcile master and main branches", "/FDS (Fair Data Society)", "TIER 2"),
        ("Other Services – Sentient Agency", "/Datafund (Core Operations)", "TIER 1"),
        ("Gastroenterološka ambulanta", "/Health & Longevity", "PERSONAL"),
        ("[[https://resources.anthropic.com/hubfs/The-Complete-Guide", "Learning & Education", "PERSONAL"),
        ("Alex Prompter on X", "/Verity", "TIER 1"),  # "important read, do it myself"
        ("Tioga Capital", "/Datafund (Core Operations)", "TIER 1"),
        ("Proof of Talk", "/Datafund (Core Operations)", "TIER 1"),
        ("Wrap up davos", "/Datafund (Core Operations)", "TIER 1"),  # cluster with 7 children
        ("Scarpetta to Rooster", "Home & Family", "PERSONAL"),
        ("Earn your first dollar online", "/Forge", "TIER 1"),
        ("SYNTHESIS", "/Datafund (Core Operations)", "TIER 1"),
        ("Zuitzerland", "/FDS (Fair Data Society)", "TIER 2"),  # correction: FDS
    ]

    for heading_prefix, focus_heading, tier_prefix in action_items:
        parent = None
        for n in ws.all_nodes():
            if n.path != NA.resolve() or n.level != 2:
                continue
            if n.heading == focus_heading:
                parent = n
                break

        if parent is None:
            print(f"  WARN: Focus area '{focus_heading}' not found in NA")
            continue

        refile_inbox_item(ws, heading_prefix, NA, parent)

    # =========================================================================
    # PHASE 3: Skills Library group → next_actions.org / System Development
    # =========================================================================
    print()
    print("=== PHASE 3: Skills Library → next_actions.org / System Development ===")

    # Find System Development focus area
    sys_dev = find_node(ws, NA, "System Development", level=2)
    if sys_dev is None:
        print("  WARN: System Development not found in NA")
    else:
        # Create parent task for skills library
        skills_parent = ws.create_node(
            NA,
            "Design and implement Skills Library module for Datacore",
            state="TODO",
            parent=sys_dev,
            tags=["AI"],
            body=(
                "Create a core module that can analyze, evaluate, and integrate\n"
                "external AI skill collections (Claude skills, prompt libraries,\n"
                "research skill sets) into Datacore. Apply engram-like patterns:\n"
                "skills as versioned, scored, domain-tagged artifacts that can be\n"
                "discovered, imported, adapted, and shared.\n"
                "\n"
                "Sub-tasks below are skill collections to evaluate and integrate."
            ),
        )
        skills_id = skills_parent.id()
        print(f"  Created: {skills_parent.heading[:60]} (ID: {skills_id})")

        # Refile skills items under this parent
        # After each refile, re-resolve skills_parent by ID (refile reloads the file)
        skills_items = [
            "Louis Gleeson on X: \"\U0001f6a8 BREAKING: The most important Claude plugin",
            "shanraisshan/claude-code-best-practice",  # nested under Meer
            "Michael Vandi on X",  # Claude viral prompts
            "Louis Gleeson on X: \"I collected every NotebookLM",  # NotebookLM prompts
            "Meer | AI Tools & News on X: \"Someone just built the missing manual for Claude C",
        ]

        for heading_prefix in skills_items:
            skills_parent = ws.find_by_id(skills_id)
            refile_inbox_item(ws, heading_prefix, NA, skills_parent)

    # =========================================================================
    # SAVE
    # =========================================================================
    print()
    print("=== SAVING ===")
    ws.save_all()

    # Reload and count
    ws2 = OrgWorkspace(roots=[INBOX, NA, RL])
    inbox_count = sum(1 for n in ws2.all_nodes() if n.path == INBOX.resolve())
    na_count = sum(1 for n in ws2.all_nodes() if n.path == NA.resolve())
    rl_count = sum(1 for n in ws2.all_nodes() if n.path == RL.resolve())
    print(f"After: inbox={inbox_count}, na={na_count}, rl={rl_count}")

    # Verify round-trip
    from org_workspace._compat import dumps
    for path, root in ws2.files().items():
        original = path.read_text()
        rt = dumps(root)
        status = "OK" if original == rt else "FAIL"
        print(f"INV-1 {path.name}: {status}")


if __name__ == "__main__":
    main()
