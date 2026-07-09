"""Pin hooks.json matchers/commands against the shipped hook scripts (#358).

Catches drift where the manifest matcher, script tool gate, or basename filter
disagree (e.g. PostToolUse missing MultiEdit while PreToolUse includes it).
"""

import json
import os
import re
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOKS_DIR = os.path.normpath(os.path.join(_TESTS_DIR, "..", "plugin", "hooks"))
_HOOKS_JSON = os.path.join(_HOOKS_DIR, "hooks.json")
_PRE_EDIT = os.path.join(_HOOKS_DIR, "pre-edit-deps.sh")
_POST_EDIT = os.path.join(_HOOKS_DIR, "post-edit-deps.sh")

_EXPECTED_MATCHER = "Edit|Write|MultiEdit"
_TOOL_GATE_RE = re.compile(
    r'case\s+"\$TOOL_NAME"\s+in\s*\n\s*Edit\|Write\|MultiEdit\)\s*;;',
    re.MULTILINE,
)


def _load_hooks_json():
    with open(_HOOKS_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def _command_entries(event_hooks):
    """Flatten hooks.json event entries into (matcher, command) pairs."""
    pairs = []
    for entry in event_hooks:
        matcher = entry.get("matcher", "")
        for hook in entry.get("hooks", []):
            pairs.append((matcher, hook.get("command", "")))
    return pairs


class HooksJsonPinTest(unittest.TestCase):
    """Manifest ↔ script agreement for PreToolUse and PostToolUse."""

    def test_pre_and_post_matchers_include_multiedit(self):
        data = _load_hooks_json()
        hooks = data["hooks"]
        for event in ("PreToolUse", "PostToolUse"):
            with self.subTest(event=event):
                pairs = _command_entries(hooks[event])
                self.assertTrue(pairs, f"{event} has no command hooks")
                matchers = [m for m, _ in pairs]
                self.assertTrue(
                    any(m == _EXPECTED_MATCHER for m in matchers),
                    f"{event} matchers {matchers!r} missing {_EXPECTED_MATCHER!r}",
                )

    def test_commands_point_at_expected_scripts(self):
        data = _load_hooks_json()
        hooks = data["hooks"]

        pre_cmds = [c for _, c in _command_entries(hooks["PreToolUse"])]
        self.assertTrue(
            any(c.endswith("/hooks/pre-edit-deps.sh") or c.endswith("pre-edit-deps.sh") for c in pre_cmds),
            f"PreToolUse commands {pre_cmds!r} missing pre-edit-deps.sh",
        )
        self.assertTrue(
            all("${CLAUDE_PLUGIN_ROOT}/hooks/pre-edit-deps.sh" in c for c in pre_cmds),
            f"PreToolUse commands must use CLAUDE_PLUGIN_ROOT: {pre_cmds!r}",
        )

        post_cmds = [c for _, c in _command_entries(hooks["PostToolUse"])]
        self.assertTrue(
            all("${CLAUDE_PLUGIN_ROOT}/hooks/post-edit-deps.sh" in c for c in post_cmds),
            f"PostToolUse commands must use CLAUDE_PLUGIN_ROOT: {post_cmds!r}",
        )

    def test_script_tool_gates_match_manifest_matcher(self):
        for path in (_PRE_EDIT, _POST_EDIT):
            with self.subTest(script=os.path.basename(path)):
                with open(path, encoding="utf-8") as fh:
                    body = fh.read()
                self.assertRegex(
                    body,
                    _TOOL_GATE_RE,
                    f"{os.path.basename(path)} tool gate must match {_EXPECTED_MATCHER}",
                )

    def test_script_basename_gates_cover_build_files(self):
        # Both scripts must accept the core build-file basenames the matcher
        # is meant to protect. Pre-edit also accepts *.versions.toml (#359);
        # post-edit currently pins libs.versions.toml — assert each script's
        # own documented set so a silent narrowing is caught.
        required = (
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
            "pom.xml",
        )
        with open(_PRE_EDIT, encoding="utf-8") as fh:
            pre = fh.read()
        with open(_POST_EDIT, encoding="utf-8") as fh:
            post = fh.read()

        for name in required:
            self.assertIn(name, pre, f"pre-edit-deps.sh missing basename {name}")
            self.assertIn(name, post, f"post-edit-deps.sh missing basename {name}")

        self.assertIn("*.versions.toml", pre)
        self.assertIn("libs.versions.toml", post)

    def test_hook_script_files_exist(self):
        self.assertTrue(os.path.isfile(_PRE_EDIT), _PRE_EDIT)
        self.assertTrue(os.path.isfile(_POST_EDIT), _POST_EDIT)
        self.assertTrue(os.path.isfile(_HOOKS_JSON), _HOOKS_JSON)


if __name__ == "__main__":
    unittest.main()
