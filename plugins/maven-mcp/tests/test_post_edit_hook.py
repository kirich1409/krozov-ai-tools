"""Tests for post-edit-deps.sh — PostToolUse /check-deps reminder.

Runs the hook as a subprocess with crafted stdin. No MCP server stub is
needed: the reminder is pure local heuristics (tool gate + basename +
coordinate-shaped content).

Import style: import unittest.mock + fully-qualified refs (CodeQL
py/import-and-import-from); no unused imports; every except has a comment.
"""

import json
import os
import shutil
import subprocess
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOK_PATH = os.path.normpath(
    os.path.join(_TESTS_DIR, "..", "plugin", "hooks", "post-edit-deps.sh")
)
_HOOKS_JSON = os.path.normpath(
    os.path.join(_TESTS_DIR, "..", "plugin", "hooks", "hooks.json")
)

_HAS_JQ = shutil.which("jq") is not None

_REMINDER_MSG = (
    "Build dependency file was modified. Consider running /check-deps "
    "to verify dependency versions are up to date."
)


def _require_jq(msg="jq not available"):
    """Class-level skipUnless decorator requiring jq."""
    return unittest.skipUnless(_HAS_JQ, msg)


def _run_hook(stdin_obj=None, stdin_raw=None, extra_env=None, proc_timeout=10):
    """Run post-edit-deps.sh; return CompletedProcess.

    Pass either stdin_obj (JSON-serialized) or stdin_raw (bytes/str as-is).
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    if stdin_raw is not None:
        if isinstance(stdin_raw, str):
            payload = stdin_raw.encode()
        else:
            payload = stdin_raw
    else:
        payload = json.dumps(stdin_obj if stdin_obj is not None else {}).encode()
    return subprocess.run(
        ["bash", _HOOK_PATH],
        input=payload,
        capture_output=True,
        env=env,
        timeout=proc_timeout,
    )


def _parse_stdout(stdout_bytes):
    """Parse hook stdout into dict; None if empty or unparseable."""
    text = stdout_bytes.decode().strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # stdout was not valid JSON — treat as no reminder
        return None


def _edit_payload(file_path, new_string, tool_name="Edit"):
    """Build a minimal Edit/Write-shaped PostToolUse payload."""
    if tool_name == "Write":
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": new_string},
        }
    return {
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path, "new_string": new_string},
    }


def _multiedit_payload(file_path, new_strings):
    """Build a MultiEdit-shaped PostToolUse payload."""
    return {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": file_path,
            "edits": [{"old_string": "x", "new_string": s} for s in new_strings],
        },
    }


@_require_jq()
class TestPostEditReminderEmits(unittest.TestCase):
    """Reminder fires when coordinate-shaped content is present."""

    def test_edit_gradle_kts_with_coordinate(self):
        result = _run_hook(
            _edit_payload(
                "/proj/build.gradle.kts",
                'implementation("com.example:lib:1.2.3")',
            )
        )
        self.assertEqual(result.returncode, 0)
        out = _parse_stdout(result.stdout)
        self.assertIsNotNone(out)
        self.assertEqual(out.get("systemMessage"), _REMINDER_MSG)

    def test_write_pom_with_dependency_tags(self):
        result = _run_hook(
            _edit_payload(
                "/proj/pom.xml",
                "<dependency><groupId>com.example</groupId>"
                "<artifactId>lib</artifactId></dependency>",
                tool_name="Write",
            )
        )
        self.assertEqual(result.returncode, 0)
        out = _parse_stdout(result.stdout)
        self.assertIsNotNone(out)
        self.assertEqual(out.get("systemMessage"), _REMINDER_MSG)

    def test_multiedit_gradle_with_coordinate(self):
        result = _run_hook(
            _multiedit_payload(
                "/proj/app/build.gradle",
                [
                    "// formatting only",
                    "implementation 'org.jetbrains.kotlin:kotlin-stdlib:1.9.0'",
                ],
            )
        )
        self.assertEqual(result.returncode, 0)
        out = _parse_stdout(result.stdout)
        self.assertIsNotNone(out)
        self.assertEqual(out.get("systemMessage"), _REMINDER_MSG)

    def test_libs_versions_toml_module(self):
        result = _run_hook(
            _edit_payload(
                "/proj/gradle/libs.versions.toml",
                'okhttp = { module = "com.squareup.okhttp3:okhttp", version = "4.12.0" }',
            )
        )
        self.assertEqual(result.returncode, 0)
        out = _parse_stdout(result.stdout)
        self.assertIsNotNone(out)
        self.assertEqual(out.get("systemMessage"), _REMINDER_MSG)


@_require_jq()
class TestPostEditReminderSkips(unittest.TestCase):
    """No reminder for non-build files, wrong tools, or non-coordinate edits."""

    def test_comment_only_edit_no_reminder(self):
        result = _run_hook(
            _edit_payload(
                "/proj/build.gradle.kts",
                "// just a formatting comment\n",
            )
        )
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(_parse_stdout(result.stdout))

    def test_non_build_file_no_reminder(self):
        result = _run_hook(
            _edit_payload(
                "/proj/src/Main.kt",
                'implementation("com.example:lib:1.0.0")',
            )
        )
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(_parse_stdout(result.stdout))

    def test_wrong_tool_no_reminder(self):
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "file_path": "/proj/build.gradle.kts",
                    "new_string": 'implementation("com.example:lib:1.0.0")',
                },
            }
        )
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(_parse_stdout(result.stdout))

    def test_multiedit_comment_only_no_reminder(self):
        result = _run_hook(
            _multiedit_payload(
                "/proj/build.gradle.kts",
                ["// tidy", "/* still no coords */"],
            )
        )
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(_parse_stdout(result.stdout))


@_require_jq()
class TestPostEditFailOpen(unittest.TestCase):
    """Malformed input / jq failure must exit 0 with empty stdout."""

    def test_malformed_json_exits_zero(self):
        result = _run_hook(stdin_raw=b"not-json{{{")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode().strip(), "")

    def test_empty_stdin_exits_zero(self):
        result = _run_hook(stdin_raw=b"")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode().strip(), "")

    def test_missing_tool_input_exits_zero(self):
        result = _run_hook({"tool_name": "Edit"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode().strip(), "")


class TestPostEditHooksJson(unittest.TestCase):
    """hooks.json PostToolUse matcher includes MultiEdit."""

    def test_post_tool_use_matcher_includes_multiedit(self):
        with open(_HOOKS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        matchers = [
            entry.get("matcher", "")
            for entry in data.get("hooks", {}).get("PostToolUse", [])
        ]
        self.assertTrue(
            any("MultiEdit" in m for m in matchers),
            f"PostToolUse matchers missing MultiEdit: {matchers!r}",
        )
        self.assertTrue(
            any("Edit" in m and "Write" in m for m in matchers),
            f"PostToolUse matchers missing Edit|Write: {matchers!r}",
        )


if __name__ == "__main__":
    unittest.main()
