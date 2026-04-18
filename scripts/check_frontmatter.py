#!/usr/bin/env python3
"""Validate Skill and Agent YAML frontmatter against Anthropic plugin rules.

Usage:
    python3 scripts/check_frontmatter.py .claude-plugin/marketplace.json

Rules enforced:
    - Every SKILL.md and agent *.md has YAML frontmatter (between two --- lines)
    - Skills: 'name' matches directory name, 'description' ≤ 1024 chars
    - Agents: 'name' matches filename (without .md),
      no forbidden fields (hooks, mcpServers, permissionMode)
    - SKILL.md > 500 lines without references/ — WARN (not error)

Exit code: 0 on success, 1 on errors. Warnings do not affect exit code.

Uses PyYAML when available (preinstalled on ubuntu-latest CI runners);
otherwise falls back to a minimal built-in parser that handles the
scalar, folded (>), literal (|), and quoted forms this project uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-not-found]
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


FORBIDDEN_AGENT_FIELDS = ("hooks", "mcpServers", "permissionMode")
DESCRIPTION_LIMIT = 1024
SKILL_LINE_WARN = 500


def load_frontmatter(path: Path) -> tuple[dict[str, object] | None, int, bool]:
    """Parse the YAML frontmatter block at the top of path.

    Returns (frontmatter_dict, line_count, error_already_reported).
    - frontmatter_dict is None on any failure; callers should stop processing.
    - line_count is the total number of lines in the file (for SKILL.md size warnings).
    - error_already_reported is True when this function printed its own specific
      ERROR line (unreadable file, missing closing ---, YAML parse error).
      Callers must NOT emit a generic "has no YAML frontmatter" message in that
      case; the specific error is authoritative.

    The caller is responsible for the "has no YAML frontmatter" message when
    the file genuinely has no opening --- delimiter (error_already_reported is False).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"ERROR: cannot read {path}: {e}")
        return None, 0, True

    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    line_count = len(text.splitlines())

    if not text.startswith("---"):
        return None, line_count, False  # caller emits generic missing-frontmatter message

    lines = text.split("\n")
    in_fm = False
    closed = False
    fm_lines: list[str] = []
    for line in lines:
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            closed = True
            break
        if in_fm:
            fm_lines.append(line)

    if not closed:
        print(
            f"ERROR: {path}: frontmatter opens with '---' but the closing delimiter "
            f"is missing — treat the block as invalid"
        )
        return None, line_count, True

    fm_text = "\n".join(fm_lines)
    if HAS_YAML:
        try:
            data = yaml.safe_load(fm_text)
        except yaml.YAMLError as e:
            print(f"ERROR: {path}: YAML parse error — {e}")
            return None, line_count, True
        return (data if isinstance(data, dict) else {}), line_count, False

    return _parse_simple_yaml(fm_text), line_count, False


def _parse_simple_yaml(text: str) -> dict[str, str]:
    """Minimal fallback parser: top-level scalar/folded/literal/quoted keys only."""
    result: dict[str, str] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or (line and line[0].isspace()):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value in (">", ">-", "|", "|-"):
            folded = value.startswith(">")
            strip_trailing = value.endswith("-")
            block: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() == "":
                    block.append("")
                    j += 1
                    continue
                if nxt and nxt[0].isspace():
                    block.append(nxt.strip())
                    j += 1
                else:
                    break
            joined = " ".join(b for b in block if b) if folded else "\n".join(block)
            if strip_trailing:
                joined = joined.rstrip("\n")
            result[key] = joined.strip()
            i = j
            continue

        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            inner = value[1:-1]
            result[key] = (
                inner.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n").replace("\\t", "\t")
            )
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            result[key] = value[1:-1].replace("''", "'")
        else:
            result[key] = value
        i += 1
    return result


def resolve_dir(source: str, rel: str | None, default: str) -> Path:
    if rel:
        return (Path(source) / ".claude-plugin" / rel).resolve()
    return (Path(source) / default).resolve()


def _check_frontmatter_common(
    path: Path, plugin_id: str, expected_name: str,
) -> tuple[dict[str, object], int] | None:
    """Shared checks. Returns (fm, line_count) on success; prints + returns None on failure."""
    fm, line_count, err_reported = load_frontmatter(path)
    if fm is None:
        if not err_reported:
            print(f"ERROR: '{plugin_id}': {path.name} has no YAML frontmatter")
        return None

    name = str(fm.get("name", "")).strip()
    if not name:
        print(f"ERROR: '{plugin_id}': frontmatter missing 'name'")
        return None
    if name != expected_name:
        kind = "directory" if path.name == "SKILL.md" else "filename"
        print(f"ERROR: '{plugin_id}': frontmatter name='{name}' mismatches {kind} '{expected_name}'")
        return None
    return fm, line_count


def check_plugin(plugin_name: str, source: str) -> int:
    """Return error count for a single plugin."""
    errors = 0
    plugin_json = Path(source) / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return 0

    manifest = json.loads(plugin_json.read_text(encoding="utf-8"))
    skills_dir = resolve_dir(source, manifest.get("skills"), "skills")
    agents_dir = resolve_dir(source, manifest.get("agents"), "agents")

    # Skills
    if skills_dir.is_dir():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            skill_name = skill_md.parent.name
            id_ = f"{plugin_name}/{skill_name}"
            result = _check_frontmatter_common(skill_md, id_, skill_name)
            if result is None:
                errors += 1
                continue
            fm, line_count = result

            desc = str(fm.get("description", ""))
            if not desc:
                print(f"ERROR: '{id_}': frontmatter missing 'description'")
                errors += 1
                continue
            if len(desc) > DESCRIPTION_LIMIT:
                print(
                    f"ERROR: '{id_}': description is {len(desc)} chars, "
                    f"exceeds Anthropic hard limit {DESCRIPTION_LIMIT}"
                )
                errors += 1
                continue

            print(f"OK: '{id_}' frontmatter ({len(desc)}ch)")
            if line_count > SKILL_LINE_WARN and not (skill_md.parent / "references").is_dir():
                print(
                    f"WARN: '{id_}': SKILL.md is {line_count} lines (>{SKILL_LINE_WARN}) "
                    f"and has no references/ — consider splitting"
                )

    # Agents
    if agents_dir.is_dir():
        for agent_md in sorted(agents_dir.glob("*.md")):
            if "references" in agent_md.parts:
                continue
            agent_name = agent_md.stem
            id_ = f"{plugin_name}/{agent_name}"
            result = _check_frontmatter_common(agent_md, id_, agent_name)
            if result is None:
                errors += 1
                continue
            fm, _ = result

            found_forbidden = False
            for forbidden in FORBIDDEN_AGENT_FIELDS:
                if forbidden in fm:
                    print(
                        f"ERROR: '{id_}': forbidden field '{forbidden}' in agent frontmatter "
                        f"(plugin-shipped agents must not declare hooks/mcpServers/permissionMode)"
                    )
                    errors += 1
                    found_forbidden = True
            if not found_forbidden:
                print(f"OK: '{id_}' agent frontmatter")

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: check_frontmatter.py <marketplace.json>", file=sys.stderr)
        return 2

    mkt_path = Path(sys.argv[1])
    if not mkt_path.is_file():
        print(f"ERROR: {mkt_path} not found")
        return 1

    marketplace = json.loads(mkt_path.read_text(encoding="utf-8"))
    total_errors = sum(
        check_plugin(p["name"], p["source"]) for p in marketplace.get("plugins", [])
    )

    if total_errors:
        print(f"\nErrors: {total_errors}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
