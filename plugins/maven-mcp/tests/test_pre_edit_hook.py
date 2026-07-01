"""Tests for pre-edit-deps.sh — PreToolUse write-time dependency guard.

Runs the hook as a subprocess with crafted stdin and CLAUDE_PLUGIN_ROOT
pointing to a temp dir whose server/server.py is a recording stub that:
  - loops over stdin to EOF (handles 1 or 2 requests),
  - records received arguments to stub_args.json,
  - emits id-correlated canned JSON-RPC responses.

Stub wiring is byte-identical across deny and allow cases; only the canned
payload differs. Every allow-case asserts the stub WAS invoked (positive
control vs a vacuous pass).

Import style: import unittest.mock + fully-qualified refs (CodeQL
py/import-and-import-from); no unused imports; every except has a comment.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import unittest.mock

from _helpers import server

# ---------------------------------------------------------------------------
# Locate hook script
# ---------------------------------------------------------------------------
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOK_PATH = os.path.normpath(
    os.path.join(_TESTS_DIR, "..", "plugin", "hooks", "pre-edit-deps.sh")
)

_HAS_JQ = shutil.which("jq") is not None
_HAS_TIMEOUT = shutil.which("timeout") is not None or shutil.which("gtimeout") is not None


def _require_jq(msg="jq not available"):
    """Class-level skipUnless decorator requiring jq."""
    return unittest.skipUnless(_HAS_JQ, msg)


def _require_jq_and_timeout(msg="jq and timeout/gtimeout required to invoke stub"):
    """Decorator requiring both jq and a timeout command.

    Tests that need the hook to actually invoke python3 (the stub) require
    timeout/gtimeout — the hook exits early (fail-open) when neither is present.
    On macOS without coreutils this skips gracefully; CI (ubuntu-latest) has timeout.
    """
    return unittest.skipUnless(_HAS_JQ and _HAS_TIMEOUT, msg)


# ---------------------------------------------------------------------------
# Shadow-bin helper for fail-open PATH tests
# ---------------------------------------------------------------------------

# All tools the hook invokes via PATH (bash builtins like printf/command excluded).
# Used to build a minimal shadow PATH that is missing exactly one tool, so the
# excluded tool is the only thing absent — all others remain reachable.
_HOOK_SHELL_TOOLS = (
    "bash", "cat", "basename", "mktemp", "grep", "sed",
    "tr", "sort", "head", "wc", "env", "cut", "jq", "python3",
)


def _shadow_bin_without(excluded_tool, tmpdir_root):
    """Build a shadow bin dir under tmpdir_root with symlinks for all _HOOK_SHELL_TOOLS
    except excluded_tool, plus the system timeout command (timeout/gtimeout) if available.

    Returns (shadow_dir, bash_abs_path) on success; (None, None) if any required
    tool (other than excluded_tool) cannot be located on this runner — caller
    should call skipTest() in that case.
    """
    bash_abs = shutil.which("bash")
    if bash_abs is None:
        return None, None

    shadow = os.path.join(tmpdir_root, "shadow_bin")
    os.makedirs(shadow, exist_ok=True)

    for tool in _HOOK_SHELL_TOOLS:
        if tool == excluded_tool:
            continue  # intentionally absent in this shadow env
        real = shutil.which(tool)
        if real is None:
            return None, None  # required tool missing on this runner
        link = os.path.join(shadow, tool)
        if not os.path.exists(link):
            os.symlink(real, link)

    # Also symlink the timeout command (timeout or gtimeout) if available.
    # Required so the python3-absent test reaches the python3 check rather
    # than exiting at the timeout check.
    for tcmd in ("timeout", "gtimeout"):
        if tcmd == excluded_tool:
            continue
        real = shutil.which(tcmd)
        if real is not None:
            link = os.path.join(shadow, tcmd)
            if not os.path.exists(link):
                os.symlink(real, link)
            break  # only one timeout variant needed

    return shadow, bash_abs


# ---------------------------------------------------------------------------
# Stub server templates (Python-3.9-safe)
# ---------------------------------------------------------------------------

# Normal stub: records args, emits canned responses, supports STUB_* env vars.
_STUB_NORMAL = textwrap.dedent("""\
    import json
    import os
    import sys

    _DIR = os.path.dirname(__file__)
    _CONFIG = os.path.join(_DIR, "stub_config.json")
    _ARGS_FILE = os.path.join(_DIR, "stub_args.json")
    _ENV_FILE = os.path.join(_DIR, "stub_env.json")
    _EXIT_CODE = int(os.environ.get("STUB_EXIT_CODE", "0"))
    _SLEEP = float(os.environ.get("STUB_SLEEP", "0"))
    _EMPTY_OUTPUT = os.environ.get("STUB_EMPTY_OUTPUT", "") == "1"
    _GARBAGE_OUTPUT = os.environ.get("STUB_GARBAGE_OUTPUT", "") == "1"

    with open(_ENV_FILE, "w", encoding="utf-8") as _ef:
        json.dump(dict(os.environ), _ef)

    if _SLEEP:
        import time
        time.sleep(_SLEEP)

    with open(_CONFIG, encoding="utf-8") as _cf:
        _config = json.load(_cf)

    _received = []

    if _GARBAGE_OUTPUT:
        for _line in sys.stdin:
            pass  # consume stdin to avoid SIGPIPE in caller
        print("this is not json at all", flush=True)
    elif _EMPTY_OUTPUT:
        for _line in sys.stdin:
            pass  # consume without output
    else:
        for _line in sys.stdin:
            _line = _line.strip()
            if not _line:
                continue
            try:
                _msg = json.loads(_line)
                _mid = _msg.get("id")
                _params = _msg.get("params") or {}
                _targs = _params.get("arguments") or {}
                _tname = _params.get("name", "")
                _received.append({"id": _mid, "name": _tname, "arguments": _targs})
                _canned = _config.get(str(_mid))
                if _canned is not None:
                    _resp = {
                        "jsonrpc": "2.0",
                        "id": _mid,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(_canned)}]
                        },
                    }
                    print(json.dumps(_resp), flush=True)
            except Exception:
                # malformed request line — skip without crashing
                pass

    with open(_ARGS_FILE, "w", encoding="utf-8") as _af:
        json.dump(_received, _af)

    sys.exit(_EXIT_CODE)
""")

# Error stub: emits JSON-RPC error envelopes (no .result).
_STUB_ERROR = textwrap.dedent("""\
    import json
    import os
    import sys

    _DIR = os.path.dirname(__file__)
    _ARGS_FILE = os.path.join(_DIR, "stub_args.json")
    _ENV_FILE = os.path.join(_DIR, "stub_env.json")

    with open(_ENV_FILE, "w", encoding="utf-8") as _ef:
        json.dump(dict(os.environ), _ef)

    _received = []
    for _line in sys.stdin:
        _line = _line.strip()
        if not _line:
            continue
        try:
            _msg = json.loads(_line)
            _received.append({
                "id": _msg.get("id"),
                "name": (_msg.get("params") or {}).get("name", ""),
            })
            _resp = {
                "jsonrpc": "2.0",
                "id": _msg.get("id"),
                "error": {"code": -32601, "message": "Method not found"},
            }
            print(json.dumps(_resp), flush=True)
        except Exception:
            # malformed request line — skip
            pass

    with open(_ARGS_FILE, "w", encoding="utf-8") as _af:
        json.dump(_received, _af)
""")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_fixture(tmpdir, config, error_stub=False):
    """Write stub server/server.py + stub_config.json into tmpdir.

    Returns tmpdir (the CLAUDE_PLUGIN_ROOT value to pass to the hook).
    """
    server_dir = os.path.join(tmpdir, "server")
    os.makedirs(server_dir, exist_ok=True)

    cfg_path = os.path.join(server_dir, "stub_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in config.items()}, f)

    stub_path = os.path.join(server_dir, "server.py")
    stub_text = _STUB_ERROR if error_stub else _STUB_NORMAL
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(stub_text)

    return tmpdir


def _run_hook(fixture_dir, stdin_obj, extra_env=None, proc_timeout=30):
    """Run pre-edit-deps.sh; return CompletedProcess."""
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = fixture_dir
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", _HOOK_PATH],
        input=json.dumps(stdin_obj).encode(),
        capture_output=True,
        env=env,
        timeout=proc_timeout,
    )


def _stub_args(fixture_dir):
    """Load stub_args.json written by the stub; [] if absent."""
    path = os.path.join(fixture_dir, "server", "stub_args.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _stub_env(fixture_dir):
    """Load stub_env.json written by the stub; {} if absent."""
    path = os.path.join(fixture_dir, "server", "stub_env.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_decision(stdout_bytes):
    """Parse hook stdout into dict; None if empty or unparseable."""
    text = stdout_bytes.decode().strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # stdout was not valid JSON — treat as no decision
        return None


# ---------------------------------------------------------------------------
# Canned payload builders
# ---------------------------------------------------------------------------

def _verify_entry(status, group_id, artifact_id, hallucination=False, suggestions=None,
                   typosquat_risk=None):
    """Build one verify_coordinates result entry."""
    entry = {
        "groupId": group_id,
        "artifactId": artifact_id,
        "existenceStatus": status,
        "gaExists": status == "exists",
        "likelyHallucination": hallucination,
    }
    if suggestions is not None:
        entry["suggestions"] = suggestions
    if typosquat_risk is not None:
        entry["typosquatRisk"] = typosquat_risk
    return entry


def _vuln_entry(group_id, artifact_id, version, vulns):
    """Build one get_dependency_vulnerabilities result entry."""
    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "version": version,
        "vulnerabilities": vulns,
        "vulnerabilityCount": len(vulns),
    }


# ---------------------------------------------------------------------------
# Common stdin builder
# ---------------------------------------------------------------------------

def _edit_stdin(filename, new_string, tool="Edit"):
    return {
        "tool_name": tool,
        "tool_input": {"file_path": f"/project/{filename}", "new_string": new_string},
    }


def _write_stdin(filename, content):
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": f"/project/{filename}", "content": content},
    }


def _multi_stdin(filename, edits):
    return {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": f"/project/{filename}",
            "edits": [{"old_string": f"//old{i}", "new_string": e} for i, e in enumerate(edits)],
        },
    }


# ---------------------------------------------------------------------------
# Helper: minimal urlopen mock response for contract-drift tests
# ---------------------------------------------------------------------------

class _MockResp:
    """Minimal urllib response mock (context-manager + .status + .read())."""

    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# ===========================================================================
# T-2 Test classes
# ===========================================================================


@_require_jq_and_timeout()
class ExtractionTest(unittest.TestCase):
    """Coordinate extraction from various build-file syntaxes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _exists_config(self, group_id="com.example", artifact_id="lib"):
        return {1: {"results": [_verify_entry("exists", group_id, artifact_id)]}}

    # ── Gradle / Groovy ──────────────────────────────────────────────────────

    def test_gradle_groovy_single_quotes(self):
        """Groovy: implementation 'g:a:v' — version extracted."""
        _make_fixture(self.tmp, self._exists_config())
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               "implementation 'com.example:lib:1.0.0'"))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1, "stub must be invoked")
        deps = args[0]["arguments"].get("dependencies", [])
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["groupId"], "com.example")
        self.assertEqual(deps[0]["artifactId"], "lib")
        self.assertEqual(deps[0].get("version"), "1.0.0")

    def test_gradle_kotlin_dsl_double_quotes(self):
        """Kotlin DSL: implementation("g:a:v") — version extracted."""
        _make_fixture(self.tmp, self._exists_config())
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle.kts",
                                               'implementation("com.example:lib:2.0.0")'))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1)
        deps = args[0]["arguments"].get("dependencies", [])
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0].get("version"), "2.0.0")

    def test_gradle_dollar_var_becomes_ga_only(self):
        """$var version → GA-only (version key absent in request)."""
        _make_fixture(self.tmp, self._exists_config())
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.example:lib:$someVar"'))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1)
        deps = args[0]["arguments"].get("dependencies", [])
        found = [d for d in deps if d.get("groupId") == "com.example"]
        self.assertGreaterEqual(len(found), 1, "coord should be extracted as GA-only")
        self.assertNotIn("version", found[0], "version must be absent for $var interpolation")

    def test_gradle_dollar_var_excluded_from_vuln_check(self):
        """GA-only coord (dropped $var version) NOT sent to get_dependency_vulnerabilities."""
        _make_fixture(self.tmp, self._exists_config())
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.example:lib:${libs.versions.x}"'))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        ids = [a["id"] for a in args]
        self.assertIn(1, ids, "verify_coordinates (id:1) should be called")
        self.assertNotIn(2, ids, "get_dependency_vulnerabilities (id:2) must NOT be called for GA-only")

    # ── pom.xml ──────────────────────────────────────────────────────────────

    def test_pom_xml_dependency(self):
        """pom.xml <dependency> with groupId+artifactId+version extracted."""
        _make_fixture(self.tmp,
                      {1: {"results": [_verify_entry("exists", "org.apache.commons", "commons-lang3")]}})
        content = (
            "<dependency>"
            "<groupId>org.apache.commons</groupId>"
            "<artifactId>commons-lang3</artifactId>"
            "<version>3.12.0</version>"
            "</dependency>"
        )
        proc = _run_hook(self.tmp, _edit_stdin("pom.xml", content))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1)
        deps = args[0]["arguments"].get("dependencies", [])
        self.assertGreaterEqual(len(deps), 1)
        self.assertEqual(deps[0]["groupId"], "org.apache.commons")
        self.assertEqual(deps[0]["artifactId"], "commons-lang3")

    # ── libs.versions.toml ───────────────────────────────────────────────────

    def test_toml_module_line(self):
        """TOML module = "g:a" extracted."""
        _make_fixture(self.tmp,
                      {1: {"results": [_verify_entry("exists", "com.example", "toml-lib")]}})
        proc = _run_hook(self.tmp, _edit_stdin(
            "libs.versions.toml",
            'toml-lib = { module = "com.example:toml-lib", version = "1.0" }',
        ))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1)
        deps = args[0]["arguments"].get("dependencies", [])
        found = [d for d in deps
                 if d.get("groupId") == "com.example" and d.get("artifactId") == "toml-lib"]
        self.assertGreaterEqual(len(found), 1, "toml module coord should be extracted")

    def test_toml_version_ref_becomes_ga_only_no_vuln_call(self):
        """TOML module-only (no inline version) → GA-only; vuln call absent."""
        _make_fixture(self.tmp,
                      {1: {"results": [_verify_entry("exists", "com.example", "mylib")]}})
        proc = _run_hook(self.tmp, _edit_stdin(
            "libs.versions.toml",
            'mylib = { module = "com.example:mylib", version.ref = "mylib" }',
        ))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        # GA-only → no vuln request
        ids = [a["id"] for a in args]
        self.assertNotIn(2, ids, "vuln check must not fire for GA-only coord")

    # ── MultiEdit ────────────────────────────────────────────────────────────

    def test_multiedit_edits_concatenated(self):
        """MultiEdit: coords from all edits[].new_string combined."""
        _make_fixture(self.tmp,
                      {1: {"results": [_verify_entry("exists", "com.foo", "bar")]}})
        stdin = _multi_stdin("build.gradle", [
            'implementation "com.foo:bar:1.0"',
            "// no coord here",
        ])
        proc = _run_hook(self.tmp, stdin)
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1)
        deps = args[0]["arguments"].get("dependencies", [])
        found = [d for d in deps if d.get("groupId") == "com.foo"]
        self.assertGreaterEqual(len(found), 1)


@_require_jq_and_timeout()
class WriteContentPathTest(unittest.TestCase):
    """Write tool uses .content (not .new_string) — critical distinct code path."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_content_absent_hallucinated_denies_with_coord_in_reason(self):
        """Write .content path: absent+hallucination → deny naming the exact coord."""
        absent = _verify_entry(
            "absent", "com.fake", "nonexistent",
            hallucination=True,
            suggestions=[{"groupId": "com.real", "artifactId": "real-lib",
                          "score": 0.92, "versionCount": 100}],
        )
        exists = _verify_entry("exists", "org.real", "somelib")
        _make_fixture(self.tmp, {1: {"results": [absent, exists]}})
        stdin = _write_stdin(
            "build.gradle",
            'implementation "org.real:somelib:1.0"\nimplementation "com.fake:nonexistent:9.9"\n',
        )
        proc = _run_hook(self.tmp, stdin)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1, "stub invoked via Write .content path (positive control)")
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision, "should produce a deny decision")
        hook_out = decision["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "PreToolUse")
        self.assertEqual(hook_out["permissionDecision"], "deny")
        # Reason must name the offending coord so the agent distinguishes new vs pre-existing
        self.assertIn("com.fake", hook_out["permissionDecisionReason"])


@_require_jq_and_timeout()
class AllowCasesTest(unittest.TestCase):
    """Cases where the hook should allow (exit 0, no stdout decision JSON)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_non_build_file_stub_never_invoked(self):
        """README.md → fast-gate exit; stub must NOT be invoked."""
        _make_fixture(self.tmp, {1: {"results": []}})
        stdin = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/project/README.md",
                "new_string": 'implementation "com.example:lib:1.0"',
            },
        }
        proc = _run_hook(self.tmp, stdin)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")
        self.assertEqual(_stub_args(self.tmp), [], "stub must NOT be invoked for non-build files")

    def test_bare_absent_no_hallucination_no_suggestions_allows(self):
        """absent + likelyHallucination:false + empty suggestions → ALLOW."""
        entry = _verify_entry("absent", "com.internal", "private-dep",
                              hallucination=False, suggestions=[])
        _make_fixture(self.tmp, {1: {"results": [entry]}})
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.internal:private-dep:1.0"'))
        self.assertEqual(proc.returncode, 0)
        self.assertIsNone(_parse_decision(proc.stdout), "bare absent must ALLOW")
        # Positive control: stub invoked (not a vacuous pass)
        self.assertGreaterEqual(len(_stub_args(self.tmp)), 1, "stub must be invoked (positive control)")

    def test_exists_clean_no_vuln_allows(self):
        """exists + no CVE → allow."""
        _make_fixture(self.tmp, {
            1: {"results": [_verify_entry("exists", "com.example", "lib")]},
            2: {"results": [_vuln_entry("com.example", "lib", "1.0", [])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.example:lib:1.0"'))
        self.assertEqual(proc.returncode, 0)
        self.assertIsNone(_parse_decision(proc.stdout))
        self.assertGreaterEqual(len(_stub_args(self.tmp)), 1)

    def test_medium_low_cve_allows(self):
        """MEDIUM/LOW CVEs → allow (not surfaced by the hook)."""
        _make_fixture(self.tmp, {
            1: {"results": [_verify_entry("exists", "org.vuln", "lib")]},
            2: {"results": [_vuln_entry("org.vuln", "lib", "1.0", [
                {"id": "CVE-2024-111", "severity": "MEDIUM"},
                {"id": "CVE-2024-222", "severity": "LOW"},
            ])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "org.vuln:lib:1.0"'))
        self.assertEqual(proc.returncode, 0)
        self.assertIsNone(_parse_decision(proc.stdout))
        self.assertGreaterEqual(len(_stub_args(self.tmp)), 1)

    def test_unknown_status_allows(self):
        """existenceStatus==unknown (degraded) → ALLOW; must not gate."""
        entry = _verify_entry("unknown", "com.unknown", "thing")
        _make_fixture(self.tmp, {1: {"results": [entry]}})
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.unknown:thing:1.0"'))
        self.assertEqual(proc.returncode, 0)
        self.assertIsNone(_parse_decision(proc.stdout))
        self.assertGreaterEqual(len(_stub_args(self.tmp)), 1)


@_require_jq_and_timeout()
class DenyCasesTest(unittest.TestCase):
    """Cases that should produce permissionDecision:'deny'."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_absent_with_hallucination_denies(self):
        """absent + likelyHallucination:true → deny with full envelope."""
        entry = _verify_entry("absent", "com.fake", "nonexistent",
                              hallucination=True, suggestions=[])
        _make_fixture(self.tmp, {1: {"results": [entry]}})
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.fake:nonexistent:1.0"'))
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        hook_out = decision["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "PreToolUse")
        self.assertEqual(hook_out["permissionDecision"], "deny")
        self.assertIn("com.fake", hook_out["permissionDecisionReason"])
        self.assertGreaterEqual(len(_stub_args(self.tmp)), 1)

    def test_absent_with_suggestion_denies_non_imperative(self):
        """absent + non-empty suggestions → deny; reason phrases as candidates-to-verify."""
        entry = _verify_entry(
            "absent", "com.fake", "fake-lib",
            hallucination=False,
            suggestions=[{"groupId": "com.real", "artifactId": "real-lib",
                          "score": 0.9, "versionCount": 50}],
        )
        _make_fixture(self.tmp, {1: {"results": [entry]}})
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.fake:fake-lib:1.0"'))
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        hook_out = decision["hookSpecificOutput"]
        self.assertEqual(hook_out["permissionDecision"], "deny")
        reason = hook_out["permissionDecisionReason"]
        # Suggestion coord appears in reason as candidates-to-verify, not as a replacement directive
        self.assertIn("com.real", reason)
        self.assertNotIn("Replace", reason)
        self.assertNotIn("replace with", reason.lower())

    def test_deny_full_envelope_structure(self):
        """Full hookSpecificOutput envelope matches the PreToolUse contract exactly."""
        entry = _verify_entry("absent", "com.bad", "hallu",
                              hallucination=True, suggestions=[])
        _make_fixture(self.tmp, {1: {"results": [entry]}})
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.bad:hallu:1.0"'))
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        self.assertIn("hookSpecificOutput", decision)
        ho = decision["hookSpecificOutput"]
        self.assertIn("hookEventName", ho)
        self.assertIn("permissionDecision", ho)
        self.assertIn("permissionDecisionReason", ho)
        self.assertEqual(ho["hookEventName"], "PreToolUse")
        self.assertIsInstance(ho["permissionDecisionReason"], str)


@_require_jq_and_timeout()
class AskCasesTest(unittest.TestCase):
    """Cases that should produce permissionDecision:'ask' (CRITICAL/HIGH CVE)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_vuln_case(self, vulns):
        """Run hook with given vuln list; return (proc, decision, args)."""
        _make_fixture(self.tmp, {
            1: {"results": [_verify_entry("exists", "org.vuln", "lib")]},
            2: {"results": [_vuln_entry("org.vuln", "lib", "1.0", vulns)]},
        })
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "org.vuln:lib:1.0"'))
        return proc, _parse_decision(proc.stdout), _stub_args(self.tmp)

    def test_critical_cve_with_fix_asks(self):
        """CRITICAL CVE with fixedVersion → ask; fix version present in reason."""
        proc, decision, args = self._run_vuln_case([
            {"id": "CVE-2024-1234", "severity": "CRITICAL", "fixedVersion": "2.0.0"},
        ])
        self.assertEqual(proc.returncode, 0)
        self.assertIsNotNone(decision)
        ho = decision["hookSpecificOutput"]
        self.assertEqual(ho["hookEventName"], "PreToolUse")
        self.assertEqual(ho["permissionDecision"], "ask")
        self.assertIn("CVE-2024-1234", ho["permissionDecisionReason"])
        self.assertIn("2.0.0", ho["permissionDecisionReason"])
        self.assertGreaterEqual(len(args), 1)

    def test_high_cve_no_fix_still_asks(self):
        """HIGH CVE without fixedVersion → ask (no dead-end deny)."""
        proc, decision, _ = self._run_vuln_case([
            {"id": "CVE-2024-5678", "severity": "HIGH"},
        ])
        self.assertEqual(proc.returncode, 0)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_critical_cve_uses_ask_not_deny(self):
        """CVE arm must use 'ask', never 'deny'."""
        proc, decision, _ = self._run_vuln_case([
            {"id": "CVE-2024-9999", "severity": "CRITICAL", "fixedVersion": "3.0"},
        ])
        self.assertIsNotNone(decision)
        self.assertNotEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")


@_require_jq_and_timeout()
class TyposquatAndMaliciousTest(unittest.TestCase):
    """#322: malicious-vuln deny + typosquatRisk ask + cross-coordinate/ordering
    precedence guarantees."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_malicious_vuln_denies_no_severity_field(self):
        """exists + malicious:true vuln (no severity) → deny."""
        _make_fixture(self.tmp, {
            1: {"results": [_verify_entry("exists", "io.github.leetcrunch", "scribejava-core")]},
            2: {"results": [_vuln_entry("io.github.leetcrunch", "scribejava-core", "1.0.0", [
                {"id": "MAL-2025-2552", "malicious": True},
            ])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin(
            "build.gradle", 'implementation "io.github.leetcrunch:scribejava-core:1.0.0"'))
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        ho = decision["hookSpecificOutput"]
        self.assertEqual(ho["permissionDecision"], "deny")
        self.assertIn("MAL-2025-2552", ho["permissionDecisionReason"])

    def test_typosquat_signal_asks_no_malicious_vuln(self):
        """exists + typosquatRisk.signal:true (no malicious vuln) → ask."""
        entry = _verify_entry(
            "exists", "com.evil", "popularlib",
            typosquat_risk={"signal": True, "reasons": ["low_version_count", "group_mismatch"],
                            "versionCount": 1,
                            "popularMatch": {"groupId": "com.real", "artifactId": "popularlib",
                                             "versionCount": 200}},
        )
        _make_fixture(self.tmp, {
            1: {"results": [entry]},
            2: {"results": [_vuln_entry("com.evil", "popularlib", "1.0.0", [])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin(
            "build.gradle", 'implementation "com.evil:popularlib:1.0.0"'))
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        ho = decision["hookSpecificOutput"]
        self.assertEqual(ho["permissionDecision"], "ask")
        self.assertIn("com.evil:popularlib", ho["permissionDecisionReason"])
        self.assertIn("com.real:popularlib", ho["permissionDecisionReason"])

    def test_both_malicious_and_typosquat_on_same_coordinate_deny_wins(self):
        """exists + malicious vuln AND typosquatRisk.signal on the SAME coordinate
        → deny wins (single decision emitted)."""
        entry = _verify_entry(
            "exists", "com.evil", "popularlib",
            typosquat_risk={"signal": True, "reasons": ["low_version_count"], "versionCount": 1},
        )
        _make_fixture(self.tmp, {
            1: {"results": [entry]},
            2: {"results": [_vuln_entry("com.evil", "popularlib", "1.0.0", [
                {"id": "MAL-2025-9999", "malicious": True},
            ])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin(
            "build.gradle", 'implementation "com.evil:popularlib:1.0.0"'))
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_cross_coordinate_precedence_deny_beats_later_ask(self):
        """Batch of TWO coordinates: A is absent+hallucination (deny), B (a
        DIFFERENT coordinate in the same run) is exists+typosquatRisk.signal
        (would-be ask) → overall decision stays deny."""
        coord_a = _verify_entry("absent", "com.fake", "hallucinated", hallucination=True)
        coord_b = _verify_entry(
            "exists", "com.evil", "popularlib",
            typosquat_risk={"signal": True, "reasons": ["low_version_count"], "versionCount": 1},
        )
        _make_fixture(self.tmp, {1: {"results": [coord_a, coord_b]}})
        proc = _run_hook(
            self.tmp,
            _edit_stdin(
                "build.gradle",
                'implementation "com.fake:hallucinated:1.0"\n'
                'implementation "com.evil:popularlib:2.0"\n',
            ),
        )
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        self.assertEqual(
            decision["hookSpecificOutput"]["permissionDecision"], "deny",
            "an earlier coordinate's deny must not be downgraded by a later coordinate's ask",
        )

    def test_fabricated_high_severity_processed_before_malicious_still_denies(self):
        """A fabricated CRITICAL/HIGH severity (stub-injected -- unreachable live
        today per the hydration gap, but exercisable via the stub), whatever
        loop-order it's processed in relative to the malicious-vuln check,
        still ends in deny (locks in the ordering guarantee ahead of a future
        hydration-gap fix)."""
        _make_fixture(self.tmp, {
            1: {"results": [_verify_entry("exists", "org.vuln", "lib")]},
            2: {"results": [_vuln_entry("org.vuln", "lib", "1.0", [
                {"id": "CVE-2024-1111", "severity": "CRITICAL", "fixedVersion": "2.0.0"},
                {"id": "MAL-2025-8888", "malicious": True},
            ])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "org.vuln:lib:1.0"'))
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_exists_neither_signal_allows(self):
        """exists + neither malicious vuln nor typosquatRisk.signal → allow."""
        entry = _verify_entry(
            "exists", "com.example", "lib",
            typosquat_risk={"signal": False, "reasons": [], "versionCount": 50},
        )
        _make_fixture(self.tmp, {
            1: {"results": [entry]},
            2: {"results": [_vuln_entry("com.example", "lib", "1.0", [])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle",
                                               'implementation "com.example:lib:1.0"'))
        self.assertEqual(proc.returncode, 0)
        self.assertIsNone(_parse_decision(proc.stdout))
        self.assertGreaterEqual(len(_stub_args(self.tmp)), 1)

    def test_popular_match_charset_filtered_in_reason(self):
        """popularMatch.groupId/artifactId are charset-filtered identically to
        suggestions before entering the reason text."""
        entry = _verify_entry(
            "exists", "com.evil", "popularlib",
            typosquat_risk={
                "signal": True, "reasons": ["low_version_count", "group_mismatch"],
                "versionCount": 1,
                "popularMatch": {"groupId": "com.real;rm -rf", "artifactId": "pop$(whoami)ular",
                                 "versionCount": 200},
            },
        )
        _make_fixture(self.tmp, {
            1: {"results": [entry]},
            2: {"results": [_vuln_entry("com.evil", "popularlib", "1.0.0", [])]},
        })
        proc = _run_hook(self.tmp, _edit_stdin(
            "build.gradle", 'implementation "com.evil:popularlib:1.0.0"'))
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
        # The injected charset-invalid content must not survive into the
        # reason verbatim (";" and "$(" here come from the crafted
        # popularMatch fields, not from the hook's own static message text).
        self.assertNotIn("com.real;rm -rf", reason)
        self.assertNotIn("pop$(whoami)ular", reason)
        self.assertNotIn("$(", reason)
        self.assertNotIn("rm -rf", reason)


@_require_jq()
class FailOpenCasesTest(unittest.TestCase):
    """Every error condition must produce exit 0 with no decision JSON."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gradle_stdin(self):
        return _edit_stdin("build.gradle", 'implementation "com.example:lib:1.0"')

    def _assert_fail_open(self, proc):
        self.assertEqual(proc.returncode, 0, "hook must exit 0 (fail-open)")
        self.assertIsNone(_parse_decision(proc.stdout), "no decision JSON on fail-open")

    def test_stub_exits_nonzero(self):
        """python3 exits non-zero → fail-open."""
        _make_fixture(self.tmp, {1: {"results": []}})
        proc = _run_hook(self.tmp, self._gradle_stdin(), extra_env={"STUB_EXIT_CODE": "1"})
        self._assert_fail_open(proc)

    def test_stub_empty_stdout(self):
        """python3 emits empty stdout → fail-open."""
        _make_fixture(self.tmp, {1: {"results": []}})
        proc = _run_hook(self.tmp, self._gradle_stdin(), extra_env={"STUB_EMPTY_OUTPUT": "1"})
        self._assert_fail_open(proc)

    def test_stub_garbage_stdout(self):
        """python3 emits non-JSON stdout → fail-open."""
        _make_fixture(self.tmp, {1: {"results": []}})
        proc = _run_hook(self.tmp, self._gradle_stdin(), extra_env={"STUB_GARBAGE_OUTPUT": "1"})
        self._assert_fail_open(proc)

    def test_stub_jsonrpc_error_envelope(self):
        """JSON-RPC error response (no .result) → fail-open."""
        _make_fixture(self.tmp, {1: {"results": []}}, error_stub=True)
        proc = _run_hook(self.tmp, self._gradle_stdin())
        self._assert_fail_open(proc)

    def test_malformed_stdin(self):
        """Non-JSON stdin → fail-open (hook can't parse tool_name)."""
        _make_fixture(self.tmp, {1: {"results": []}})
        proc = subprocess.run(
            ["bash", _HOOK_PATH],
            input=b"this is not json !!! {broken",
            capture_output=True,
            env={**os.environ, "CLAUDE_PLUGIN_ROOT": self.tmp},
            timeout=30,
        )
        self._assert_fail_open(proc)

    @unittest.skipUnless(_HAS_TIMEOUT, "timeout/gtimeout not available")
    def test_stub_hangs_beyond_timeout(self):
        """Stub sleeping past timeout (exit 124) → fail-open; ~8s wait expected."""
        _make_fixture(self.tmp, {1: {"results": []}})
        proc = _run_hook(
            self.tmp,
            self._gradle_stdin(),
            extra_env={"STUB_SLEEP": "30"},
            proc_timeout=15,  # outer: longer than inner 8s hook timeout
        )
        self._assert_fail_open(proc)

    def test_python3_not_in_path(self):
        """python3 absent from PATH → fail-open at command -v check."""
        _make_fixture(self.tmp, {1: {"results": []}})
        # Build a shadow bin with every hook tool symlinked except python3.
        # Invoke bash by its absolute path so subprocess.run does not depend
        # on PATH to find bash itself (on Linux all tools share /usr/bin,
        # so filtering by directory would also remove bash and cause an error).
        shadow_dir, bash_abs = _shadow_bin_without("python3", self.tmp)
        if shadow_dir is None:
            self.skipTest("could not build shadow bin (required tool missing on this runner)")
        proc = subprocess.run(
            [bash_abs, _HOOK_PATH],
            input=json.dumps(self._gradle_stdin()).encode(),
            capture_output=True,
            env={**os.environ, "CLAUDE_PLUGIN_ROOT": self.tmp, "PATH": shadow_dir},
            timeout=30,
        )
        self._assert_fail_open(proc)

    def test_jq_not_in_path(self):
        """jq absent from PATH → fail-open at very first fast-gate check."""
        _make_fixture(self.tmp, {1: {"results": []}})
        # Build a shadow bin with every hook tool symlinked except jq.
        # Invoke bash by its absolute path so subprocess.run does not depend
        # on PATH to find bash itself (on Linux all tools share /usr/bin,
        # so filtering by directory would also remove bash and cause an error).
        shadow_dir, bash_abs = _shadow_bin_without("jq", self.tmp)
        if shadow_dir is None:
            self.skipTest("could not build shadow bin (required tool missing on this runner)")
        proc = subprocess.run(
            [bash_abs, _HOOK_PATH],
            input=json.dumps(self._gradle_stdin()).encode(),
            capture_output=True,
            env={**os.environ, "CLAUDE_PLUGIN_ROOT": self.tmp, "PATH": shadow_dir},
            timeout=30,
        )
        self._assert_fail_open(proc)


@_require_jq_and_timeout()
class SecurityTest(unittest.TestCase):
    """Security contracts: GITHUB_TOKEN scrub + charset filtering."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_github_token_scrubbed_from_spawned_env(self):
        """GITHUB_TOKEN must NOT be present in the environment the stub sees."""
        _make_fixture(self.tmp, {
            1: {"results": [_verify_entry("exists", "com.example", "lib")]},
        })
        proc = _run_hook(
            self.tmp,
            _edit_stdin("build.gradle", 'implementation "com.example:lib:1.0"'),
            extra_env={"GITHUB_TOKEN": "super-secret-token-xyz"},
        )
        self.assertEqual(proc.returncode, 0)
        env = _stub_env(self.tmp)
        self.assertNotIn(
            "GITHUB_TOKEN", env,
            "GITHUB_TOKEN must be scrubbed from the spawned python env (env -u GITHUB_TOKEN)",
        )

    def test_charset_invalid_coord_dropped(self):
        """Coord token with invalid chars (semicolon) dropped at extraction."""
        _make_fixture(self.tmp, {
            1: {"results": [_verify_entry("exists", "com.example", "lib")]},
        })
        proc = _run_hook(
            self.tmp,
            _edit_stdin(
                "build.gradle",
                # Valid coord followed by an invalid-charset pseudo-coord
                'implementation "com.example:lib:1.0"\n'
                '// implementation "bad;grp:artifact:1.0"\n',
            ),
        )
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        if args:
            deps = args[0]["arguments"].get("dependencies", [])
            for dep in deps:
                self.assertFalse(
                    ";" in dep.get("groupId", "") or ";" in dep.get("artifactId", ""),
                    "coord with ; must not reach the stub",
                )


@_require_jq_and_timeout()
class BoundaryTest(unittest.TestCase):
    """MAX_COORDS cap, deduplication, multi-finding aggregation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_max_coords_capped_at_eight(self):
        """Content with >8 distinct coords → at most 8 sent."""
        lines = [f'implementation "com.lib{i}:art{i}:1.{i}"' for i in range(12)]
        results = [_verify_entry("exists", f"com.lib{i}", f"art{i}") for i in range(8)]
        _make_fixture(self.tmp, {1: {"results": results}})
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle", "\n".join(lines)))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1)
        deps = args[0]["arguments"].get("dependencies", [])
        self.assertLessEqual(len(deps), 8, "at most MAX_COORDS=8 deps sent")

    def test_duplicates_collapsed(self):
        """Same coord repeated 3× → sent exactly once."""
        entry = _verify_entry("exists", "com.example", "lib")
        _make_fixture(self.tmp, {1: {"results": [entry]}})
        content = "\n".join(['implementation "com.example:lib:1.0"'] * 3)
        proc = _run_hook(self.tmp, _edit_stdin("build.gradle", content))
        self.assertEqual(proc.returncode, 0)
        args = _stub_args(self.tmp)
        self.assertGreaterEqual(len(args), 1)
        deps = args[0]["arguments"].get("dependencies", [])
        matching = [d for d in deps
                    if d.get("groupId") == "com.example" and d.get("artifactId") == "lib"]
        self.assertEqual(len(matching), 1, "duplicate must be collapsed to one entry")

    def test_deny_wins_over_ask_on_multiple_problems(self):
        """One absent+hallucinated coord + one CRITICAL CVE → deny (deny > ask)."""
        absent = _verify_entry("absent", "com.bad", "hallu",
                               hallucination=True, suggestions=[])
        exists = _verify_entry("exists", "org.vuln", "lib")
        _make_fixture(self.tmp, {
            1: {"results": [absent, exists]},
            2: {"results": [_vuln_entry("org.vuln", "lib", "2.0", [
                {"id": "CVE-2024-0001", "severity": "CRITICAL", "fixedVersion": "3.0"},
            ])]},
        })
        proc = _run_hook(
            self.tmp,
            _edit_stdin("build.gradle",
                        'implementation "com.bad:hallu:1.0"\n'
                        'implementation "org.vuln:lib:2.0"\n'),
        )
        self.assertEqual(proc.returncode, 0)
        decision = _parse_decision(proc.stdout)
        self.assertIsNotNone(decision)
        self.assertEqual(
            decision["hookSpecificOutput"]["permissionDecision"],
            "deny",
            "deny must win over ask when both findings are present",
        )


@_require_jq()
class ContractDriftGuardTest(unittest.TestCase):
    """Feed the hook's JSON-RPC contract into the REAL dispatch to detect drift."""

    # Minimal metadata XML for exists-response mocks
    _META_XML = (
        b"<metadata>"
        b"<versioning><versions><version>1.0</version></versions></versioning>"
        b"</metadata>"
    )
    _OSV_EMPTY = json.dumps({"results": [{"vulns": []}]}).encode()

    def _urlopen_always(self, body, status=200):
        """Return a side_effect that always yields (status, body)."""
        def _effect(*_args, **_kwargs):
            return _MockResp(status, body)
        return _effect

    def _dispatch_capture(self, request, urlopen_body):
        """Call server.dispatch and capture the JSON-RPC response written to stdout."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=self._urlopen_always(urlopen_body),
            ):
                server.dispatch(request)
        output = buf.getvalue().strip()
        # dispatch prints JSON to stdout; parse it
        return json.loads(output)

    def test_verify_coordinates_request_accepted_by_real_dispatch(self):
        """verify_coordinates JSON-RPC as emitted by the hook → accepted by real server."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "verify_coordinates",
                "arguments": {
                    "dependencies": [
                        {"groupId": "com.example", "artifactId": "lib", "version": "1.0"}
                    ]
                },
            },
        }
        result = self._dispatch_capture(request, self._META_XML)
        self.assertIn("result", result, "real dispatch must produce a result")
        text = result["result"]["content"][0]["text"]
        parsed = json.loads(text)
        self.assertIn("results", parsed)
        self.assertGreaterEqual(len(parsed["results"]), 1)
        self.assertIn("existenceStatus", parsed["results"][0])

    def test_get_dependency_vulnerabilities_request_accepted_by_real_dispatch(self):
        """get_dependency_vulnerabilities JSON-RPC as emitted by hook → accepted."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_dependency_vulnerabilities",
                "arguments": {
                    "dependencies": [
                        {"groupId": "com.example", "artifactId": "lib", "version": "1.0"}
                    ]
                },
            },
        }
        result = self._dispatch_capture(request, self._OSV_EMPTY)
        self.assertIn("result", result)
        text = result["result"]["content"][0]["text"]
        parsed = json.loads(text)
        self.assertIn("results", parsed)


if __name__ == "__main__":
    unittest.main()
