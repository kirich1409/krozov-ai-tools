#!/usr/bin/env python3
"""Validate Skill and Agent YAML frontmatter against Anthropic plugin rules.

Usage:
    python3 scripts/check_frontmatter.py .claude-plugin/marketplace.json

Rules enforced:
    - Every SKILL.md and agent *.md has YAML frontmatter (between two --- lines)
    - Frontmatter has 'name' field; for skills: matches directory name;
      for agents: matches filename (without .md)
    - Skill 'description' ≤ 1024 chars (Anthropic hard limit)
    - Agent frontmatter has no forbidden fields: hooks, mcpServers, permissionMode
    - SKILL.md > 500 lines without references/ — WARN (not error)

Exit code: 0 on success, 1 on errors. Warnings do not affect exit code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


FORBIDDEN_AGENT_FIELDS = ("hooks", "mcpServers", "permissionMode")
DESCRIPTION_LIMIT = 1024
SKILL_LINE_WARN = 500


def extract_frontmatter(path: Path) -> dict[str, str] | None:
    """Return dict of top-level string scalar keys from YAML frontmatter, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"ERROR: cannot read {path}: {e}")
        return None

    if not text.startswith("---"):
        return None

    # Split on first two '---' boundary lines
    lines = text.split("\n")
    in_fm = False
    fm_lines: list[str] = []
    for line in lines:
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            break
        if in_fm:
            fm_lines.append(line)

    return parse_simple_yaml("\n".join(fm_lines))


def parse_simple_yaml(text: str) -> dict[str, str]:
    """Parse simplified YAML: top-level keys, scalars, folded (> / >-) and literal (| / |-) blocks.

    Does NOT support nested mappings, sequences, anchors, or tags.
    Sufficient for SKILL.md / agent frontmatter.
    """
    result: dict[str, str] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # top-level key (no leading indent)
        if not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value in (">", ">-", "|", "|-"):
                # collect indented continuation
                folded = value.startswith(">")
                block: list[str] = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt.strip() == "":
                        block.append("")
                        j += 1
                        continue
                    if nxt[0].isspace():
                        block.append(nxt.strip())
                        j += 1
                    else:
                        break
                if folded:
                    joined = " ".join(b for b in block if b != "")
                else:
                    joined = "\n".join(block)
                if value.endswith("-"):
                    joined = joined.rstrip("\n")
                result[key] = joined.strip()
                i = j
                continue
            # quoted value
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                # simple unescape
                result[key] = value[1:-1].encode().decode("unicode_escape")
            elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
                result[key] = value[1:-1].replace("''", "'")
            else:
                result[key] = value
            i += 1
            continue
        i += 1
    return result


def resolve_dir(source: str, rel: str | None, default: str) -> Path:
    base = Path(source) / ".claude-plugin"
    if not rel:
        # default is plugin-root relative (e.g. "skills" or "agents")
        return (Path(source) / default).resolve()
    return (base / rel).resolve()


def check_plugin(plugin_name: str, source: str) -> tuple[int, int]:
    """Return (errors, warnings) for a single plugin."""
    errors = 0
    warnings = 0
    plugin_json = Path(source) / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return 0, 0

    manifest = json.loads(plugin_json.read_text(encoding="utf-8"))
    skills_dir = resolve_dir(source, manifest.get("skills"), "skills")
    agents_dir = resolve_dir(source, manifest.get("agents"), "agents")

    # --- Skills ---
    if skills_dir.is_dir():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            skill_name = skill_md.parent.name
            id_ = f"{plugin_name}/{skill_name}"
            fm = extract_frontmatter(skill_md)
            if fm is None:
                print(f"ERROR: '{id_}': SKILL.md has no YAML frontmatter")
                errors += 1
                continue
            name = fm.get("name", "").strip()
            if not name:
                print(f"ERROR: '{id_}': frontmatter missing 'name'")
                errors += 1
            elif name != skill_name:
                print(
                    f"ERROR: '{id_}': frontmatter name='{name}' mismatches directory '{skill_name}'"
                )
                errors += 1

            desc = fm.get("description", "")
            if not desc:
                print(f"ERROR: '{id_}': frontmatter missing 'description'")
                errors += 1
            elif len(desc) > DESCRIPTION_LIMIT:
                print(
                    f"ERROR: '{id_}': description is {len(desc)} chars, exceeds Anthropic hard limit {DESCRIPTION_LIMIT}"
                )
                errors += 1
            else:
                print(f"OK: '{id_}' frontmatter ({len(desc)}ch)")

            # SKILL.md size warning
            line_count = skill_md.read_text(encoding="utf-8").count("\n")
            if line_count > SKILL_LINE_WARN:
                if not (skill_md.parent / "references").is_dir():
                    print(
                        f"WARN: '{id_}': SKILL.md is {line_count} lines (>{SKILL_LINE_WARN}) "
                        f"and has no references/ — consider splitting"
                    )
                    warnings += 1

    # --- Agents ---
    if agents_dir.is_dir():
        for agent_md in sorted(agents_dir.glob("*.md")):
            # skip references/
            if "references" in agent_md.parts:
                continue
            agent_name = agent_md.stem
            id_ = f"{plugin_name}/{agent_name}"
            fm = extract_frontmatter(agent_md)
            if fm is None:
                print(f"ERROR: '{id_}': agent has no YAML frontmatter")
                errors += 1
                continue
            name = fm.get("name", "").strip()
            if not name:
                print(f"ERROR: '{id_}': frontmatter missing 'name'")
                errors += 1
            elif name != agent_name:
                print(
                    f"ERROR: '{id_}': frontmatter name='{name}' mismatches filename '{agent_name}'"
                )
                errors += 1

            for forbidden in FORBIDDEN_AGENT_FIELDS:
                if forbidden in fm:
                    print(
                        f"ERROR: '{id_}': forbidden field '{forbidden}' in agent frontmatter "
                        f"(plugin-shipped agents must not declare hooks/mcpServers/permissionMode)"
                    )
                    errors += 1

            if "name" in fm and name == agent_name:
                print(f"OK: '{id_}' agent frontmatter")

    return errors, warnings


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: check_frontmatter.py <marketplace.json>", file=sys.stderr)
        return 2

    mkt_path = Path(sys.argv[1])
    if not mkt_path.is_file():
        print(f"ERROR: {mkt_path} not found")
        return 1

    marketplace = json.loads(mkt_path.read_text(encoding="utf-8"))

    total_errors = 0
    total_warnings = 0
    for plugin in marketplace.get("plugins", []):
        e, w = check_plugin(plugin["name"], plugin["source"])
        total_errors += e
        total_warnings += w

    if total_warnings:
        print(f"\nWarnings: {total_warnings}")
    if total_errors:
        print(f"\nErrors: {total_errors}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
