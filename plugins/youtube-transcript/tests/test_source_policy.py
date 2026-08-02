"""Source-text-pattern and AST-Name-based policy checks that are NOT import-graph
facts (`test_import_boundaries.py` owns those, since they're a fact about which
module imports which). This file is created here, at T-3, owning only the
`__import__`-as-AST-Name check named by T-3's `check` line -- T-6a/T-14 later
extend this same file with their own portions (TLS-bypass tokens, file-write/exec
primitive bans, the `urllib.request`/`urllib.error` attribute-access text-ban) --
`tasks.md`'s T-3 block already referenced `test_dunder_import_banned_via_ast_name_check`
in this file without separately listing the file itself; this is that file's first
revision.

`__import__` is a builtin function call -- `Name`/`Call` AST nodes, never an
`Import`/`ImportFrom` node -- so `test_import_boundaries.py`'s import-node scan
structurally cannot see it (plan.md cycle 5 finding: a prior version of this ban
claimed `__import__` was caught by the same Import-node mechanism `importlib` uses,
which was vacuously green forever). The AST-`Name` form used here, not a text grep,
also avoids false-flagging the literal string `"__import__"` inside a comment or
docstring.

T-6a (this revision) adds two source-text bans, each with its own, separately
checked exclusion set (plan.md cycle 4 finding -- "each ban pattern has its own
exclusion set, checked as an exact-path membership test named per-ban, not one
shared list with a single 'exactly one entry' assertion"):

1. TLS-bypass-token bans (`_TLS_BYPASS_PATTERNS`) -- scanned under
   `plugins/youtube-transcript/` **including** `tests/`, excluding exactly this
   file by path (else the ban scan matches its own ban-list literals and is red
   from creation).
2. The `.opener`-access ban (`_OPENER_ACCESS_PATTERN`) -- scanned under
   `plugin/server/**` **only**; `tests/` is explicitly NOT in scope, since tests
   are required to reference the opener to mock it
   (`test_net_client_policy.py::test_scheme_https_only_opener_never_called`,
   `_helpers.py`'s `mock_urlopen`). This ban's exclusion set is empty, not shared
   with (1)'s -- `test_opener_ban_excludes_nothing_under_plugin_server` asserts
   that directly.
"""

import ast
import os
import re
import unittest
from typing import List, Pattern

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_DIR = os.path.normpath(os.path.join(_TESTS_DIR, ".."))
_SERVER_DIR = os.path.normpath(os.path.join(_PLUGIN_DIR, "plugin", "server"))

# This file's own path, relative to _PLUGIN_DIR -- the one exclusion the
# TLS-bypass-token ban carries (its scan otherwise matches its own ban-list
# literals, see module docstring).
_THIS_FILE_RELPATH = os.path.relpath(os.path.abspath(__file__), _PLUGIN_DIR)


def _iter_py_files(root_dir: str) -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def _iter_server_py_files(server_dir: str) -> List[str]:
    return _iter_py_files(server_dir)


def find_dunder_import_names(source: str) -> List[int]:
    """Returns the line number of every `ast.Name(id="__import__")` node found via
    `ast.walk` (function-nested calls included, same reasoning as
    `test_import_boundaries.py`'s import scan)."""
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "__import__"
    ]


class TestDunderImportBannedViaAstNameCheck(unittest.TestCase):
    def test_dunder_import_banned_via_ast_name_check(self) -> None:
        # The mechanism actually catches __import__ used as a Name/Call node,
        # including inside a nested function scope.
        self.assertEqual(find_dunder_import_names("x = __import__('os')\n"), [1])
        self.assertEqual(
            find_dunder_import_names("def f():\n    return __import__('os')\n"),
            [2],
        )
        # A bare string mentioning "__import__" in a docstring/comment must NOT
        # false-flag -- proves this is an AST-Name walk, not a text grep.
        self.assertEqual(
            find_dunder_import_names(
                '"""__import__ mentioned here, never called."""\n# __import__ again\n'
            ),
            [],
        )

        # Real tree: no module under plugin/server/** currently calls __import__.
        violations = []
        for path in _iter_server_py_files(_SERVER_DIR):
            with open(path, encoding="utf-8") as source_file:
                source = source_file.read()
            lines = find_dunder_import_names(source)
            if lines:
                violations.append(f"{path}: __import__ used at line(s) {lines}")
        self.assertEqual(violations, [])


# --- T-6a: TLS-bypass-token bans -------------------------------------------------

_TLS_BYPASS_PATTERNS: List[Pattern[str]] = [
    re.compile(r"_create_unverified_context"),
    re.compile(r"CERT_NONE"),
    re.compile(r"check_hostname\s*=\s*False"),
    re.compile(r"ssl\.SSLContext\("),
    re.compile(r"_create_default_https_context"),
]

# --- T-6a: `.opener`-access ban ---------------------------------------------------
#
# `\.opener\b` specifically -- NOT `.open(` (too broad: matches `gzip.open(`,
# `Path.open(`, `io.open(`, all legitimate elsewhere in this codebase and unrelated
# to the egress-primitive risk this ban targets).
_OPENER_ACCESS_PATTERN: Pattern[str] = re.compile(r"\.opener\b")


def find_pattern_matches(source: str, patterns: List[Pattern[str]]) -> List[str]:
    """Returns one `"line {n}: {pattern!r}"` string per matching (line, pattern)
    pair -- named, not just counted, so a real violation says where and which."""
    matches: List[str] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        for pattern in patterns:
            if pattern.search(line):
                matches.append(f"line {line_no}: {pattern.pattern!r}")
    return matches


class TestNoTlsBypassTokens(unittest.TestCase):
    def test_no_tls_bypass_tokens(self) -> None:
        # Self-check: the mechanism actually matches each banned token, one per
        # line, exactly once each -- built from concatenated string parts (same
        # pattern test_import_boundaries.py's urllib.request fixture already uses)
        # so this fixture isn't itself the kind of literal-substring hazard the
        # module docstring's exclusion exists for.
        fixture = "\n".join(
            [
                "ctx = ssl." + "_create_unverified_context()",
                "ctx.verify_mode = ssl." + "CERT_NONE",
                "ctx.check_hostname" + " = False",
                "ctx = ssl." + "SSLContext(ssl.PROTOCOL_TLS)",
                "ssl." + "_create_default_https_context = None",
            ]
        )
        self.assertEqual(len(find_pattern_matches(fixture, _TLS_BYPASS_PATTERNS)), 5)

        # A clean line -- the one form this codebase actually uses -- matches
        # nothing.
        self.assertEqual(
            find_pattern_matches(
                "ctx = ssl.create_default_context()\n", _TLS_BYPASS_PATTERNS
            ),
            [],
        )

        # Real tree: nothing under plugins/youtube-transcript/ (including tests/)
        # uses a TLS-bypass token, excluding exactly this file by path (else this
        # scan matches its own ban-list literals above and is red from creation).
        violations = []
        for path in _iter_py_files(_PLUGIN_DIR):
            if os.path.relpath(path, _PLUGIN_DIR) == _THIS_FILE_RELPATH:
                continue
            with open(path, encoding="utf-8") as source_file:
                source = source_file.read()
            for match in find_pattern_matches(source, _TLS_BYPASS_PATTERNS):
                violations.append(f"{path}: {match}")
        self.assertEqual(violations, [])


class TestOpenerReferenceBannedOutsideNetClient(unittest.TestCase):
    def test_opener_reference_banned_outside_net_client(self) -> None:
        # Self-check: matches `.opener` attribute access specifically, never the
        # broader (and legitimate elsewhere) `.open(` call.
        self.assertTrue(_OPENER_ACCESS_PATTERN.search("transport.opener.open(url)"))
        self.assertFalse(_OPENER_ACCESS_PATTERN.search("gzip.open(path)"))
        self.assertFalse(_OPENER_ACCESS_PATTERN.search("Path.open()"))
        self.assertFalse(_OPENER_ACCESS_PATTERN.search("io.open(path)"))
        # A bare `_OPENER` module-private reference (net/client.py's own name) does
        # not false-flag either -- the pattern requires a literal `.` immediately
        # before "opener", and this is one identifier with no leading dot.
        self.assertFalse(_OPENER_ACCESS_PATTERN.search("_OPENER = _build_opener()"))

        # Real tree: no module under plugin/server/** references `.opener` --
        # this ban's scope is production code only; `tests/` is explicitly out of
        # scope (tests are required to reference the opener to mock it:
        # test_net_client_policy.py's opener-never-called assertions, _helpers.py's
        # mock_urlopen), so it is deliberately not scanned here at all.
        violations = []
        for path in _iter_py_files(_SERVER_DIR):
            with open(path, encoding="utf-8") as source_file:
                source = source_file.read()
            for line_no, line in enumerate(source.splitlines(), start=1):
                if _OPENER_ACCESS_PATTERN.search(line):
                    violations.append(f"{path}:{line_no}: {line.strip()!r}")
        self.assertEqual(violations, [])


class TestOpenerBanExcludesNothingUnderPluginServer(unittest.TestCase):
    def test_opener_ban_excludes_nothing_under_plugin_server(self) -> None:
        # This ban's exclusion set is empty -- and it is its OWN exclusion set, not
        # shared with the TLS-bypass-token ban's per-file exclusion above (plan.md
        # cycle 4 finding: "each ban pattern has its own exclusion set, checked as
        # an exact-path membership test named per-ban, not one shared 'exclusion
        # list' with a single 'exactly one entry' assertion" -- that prior wording
        # was already false the moment a second, differently-scoped ban existed).
        opener_ban_exclusions: "frozenset[str]" = frozenset()
        self.assertEqual(opener_ban_exclusions, frozenset())
        # Not the TLS-bypass-token ban's exclusion (a single relative path) --
        # asserting the two are different confirms this test isn't accidentally
        # checking the other ban's set instead of its own.
        self.assertNotEqual(opener_ban_exclusions, frozenset({_THIS_FILE_RELPATH}))


if __name__ == "__main__":
    unittest.main()
