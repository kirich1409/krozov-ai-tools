"""AST-based import-boundary + stdlib-egress-name enforcement for everything under
``plugin/server/**`` (T-3).

The literal source of truth for ``ALLOWED_EDGES`` below is
``docs/plans/youtube-transcript/plan.md``'s "Module layout and dependency direction"
section's table -- transcribed exactly, not reinterpreted. This file also enforces,
in the same walk: (b) only ``net/client.py`` may import the named egress/dynamic-code
-capable stdlib modules; ``importlib`` is banned everywhere, including
``net/client.py``; (c) the combined ``node.module`` **and** ``f"{node.module}.{alias.name}"``
form is checked per ``ImportFrom`` alias, so ``from urllib import request``/``from
http import client`` cannot slip through undetected; (d) any ``xml.*`` import is
restricted to ``net/client.py``.

**This mechanism is a regression guard, not a closed security boundary** (plan.md's
"The AST/text-ban mechanism is a regression guard, not a closed security boundary"
section) -- see ``test_attribute_access_bypass_documented_not_closed`` below for the
one bypass class this file deliberately does NOT claim to close, and why no purely
static, single-process-Python check can.

``__import__`` is checked separately, as an AST ``Name`` walk, in
``test_source_policy.py`` -- it is a builtin function call (``Name``/``Call`` nodes),
never an ``Import``/``ImportFrom`` node, so this file's import-node scan structurally
cannot see it (plan.md cycle 5 finding).
"""

import ast
import json
import os
import sys
import unittest
from typing import Dict, FrozenSet, List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SERVER_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "plugin", "server"))
_FIXTURES_DIR = os.path.join(_THIS_DIR, "fixtures")

# --- ALLOWED_EDGES: the literal table from plan.md -------------------------------
#
# Keyed by the module's dotted path relative to plugin/server/. A specific per-file
# key (e.g. "providers.base") takes precedence when present; otherwise the
# package-level fallback key (e.g. "providers") applies via `_resolve_permitted`
# below -- this is what lets a package's own (currently empty) __init__.py, and any
# future submodule not individually named in the table, resolve without ever
# needing a table edit, per plan.md's "all checks pass trivially on the tree built
# so far and stay green as later waves add code."
#
# Same-package imports are always allowed (general rule, plan.md) and are
# deliberately NOT restated as entries here -- this table lists only cross-package
# edges, exactly as plan.md's table does. The one same-package exception
# (`providers/base.py`/`providers/video_ref.py` may not import
# `providers/innertube.py`) is enforced separately, by `_PROVIDERS_BASE_SIDE` below,
# since a same-package *negative* case has no natural expression as a permitted-set
# entry.
ALLOWED_EDGES: Dict[str, FrozenSet[str]] = {
    "domain": frozenset(),
    "net": frozenset({"domain"}),
    "providers": frozenset({"domain"}),
    "providers.base": frozenset({"domain"}),
    "providers.video_ref": frozenset({"domain"}),
    "providers.innertube": frozenset({"domain", "net"}),
    "formats": frozenset({"domain"}),
    "protocol": frozenset({"domain"}),
    "protocol.envelope": frozenset({"domain"}),
    "protocol.schemas": frozenset({"domain"}),
    "protocol.registry": frozenset({"domain", "protocol.envelope", "protocol.schemas"}),
    "protocol.dispatch": frozenset({"domain", "protocol.envelope", "protocol.schemas"}),
    "tools": frozenset({"domain", "formats", "providers.base"}),
    # Root-level modules, T-13b -- not created yet at T-3, listed now so this table
    # never needs a future edit.
    "composition": frozenset({"domain", "providers.base", "providers.innertube"}),
    "server": frozenset({"composition", "protocol", "tools", "domain"}),
}

# Packages (directories with their own __init__.py) as opposed to single-file
# root-level modules (composition.py/server.py, T-13b) -- used to resolve `from .
# import x`-style relative imports to an absolute dotted name (see
# `_own_package_parts`).
_PACKAGE_MODULE_KEYS: FrozenSet[str] = frozenset(
    {"domain", "net", "providers", "formats", "protocol", "tools"}
)

# Every top-level name this project's own layout can produce -- anything else is
# either stdlib or a forbidden third-party import (AC-14).
_PROJECT_TOP_PACKAGES: FrozenSet[str] = frozenset(
    {"domain", "net", "providers", "formats", "protocol", "tools", "composition", "server"}
)

# The one same-package negative-direction exception (plan.md cycle 4 finding): the
# abstraction (`providers/base.py`'s ABCs, `providers/video_ref.py`) may not import
# its own concrete implementation -- the one dependency direction `composition.py`
# exists as a separate wiring layer specifically to avoid (AC-23/AC-24).
_PROVIDERS_BASE_SIDE: FrozenSet[str] = frozenset({"providers.base", "providers.video_ref"})
_INNERTUBE_KEY = "providers.innertube"

NET_CLIENT_KEY = "net.client"

# Egress- or dynamic-code-capable stdlib modules restricted to net/client.py only
# (plan.md cycle 5's expanded list -- the original six omitted several others with
# equivalent capability). `importlib` and `xml.*` are handled by their own,
# unconditional/near-unconditional rules below, not this set.
RESTRICTED_TO_NET_CLIENT: FrozenSet[str] = frozenset(
    {
        "urllib.request",
        "urllib.error",
        "http.client",
        "socket",
        "ssl",
        "ftplib",
        "asyncio",
        "ctypes",
        "xmlrpc.client",
        "smtplib",
        "webbrowser",
        "http.server",
    }
)


# --- stdlib name lists: two static, committed, per-CI-matrix-leg lists ----------
#
# Cycle 5 fix: each list is generated once, on that exact interpreter version, and
# committed -- never computed at test time, no `sysconfig.get_paths()` fallback
# (empirically confirmed wrong on both counts by plan.md's cycle 3/cycle 4 -- see
# that section for the full derivation). Selected here purely by `sys.version_info`.
def _load_stdlib_names(filename: str) -> FrozenSet[str]:
    with open(os.path.join(_FIXTURES_DIR, filename), encoding="utf-8") as fixture_file:
        return frozenset(json.load(fixture_file))


_STDLIB_NAMES_3_9 = _load_stdlib_names("stdlib_names_3_9.json")
_STDLIB_NAMES_3_13 = _load_stdlib_names("stdlib_names_3_13.json")


def _stdlib_names_for_version(version_info: Tuple[int, int]) -> FrozenSet[str]:
    """No `skipUnless`: every leg's list is checked against every leg's interpreter
    at test-collection time, this function just picks which committed list to
    compare against, by version alone."""
    if version_info < (3, 10):
        return _STDLIB_NAMES_3_9
    return _STDLIB_NAMES_3_13


# --- Module-key <-> filesystem-path resolution -----------------------------------


def _iter_server_py_files(server_dir: str) -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(server_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def _module_key_for_path(path: str, server_dir: str) -> str:
    rel = os.path.relpath(path, server_dir)
    if rel.endswith(".py"):
        rel = rel[: -len(".py")]
    parts = rel.split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _own_package_parts(module_key: str) -> List[str]:
    """The dotted parts of the package a single-dot relative import (`from . import
    x`, level=1) resolves against. A package's own __init__.py resolves against
    itself; a submodule resolves against its parent; a root-level, non-package
    module (composition.py/server.py) has none."""
    if module_key in _PACKAGE_MODULE_KEYS:
        return module_key.split(".")
    parts = module_key.split(".")
    if len(parts) > 1:
        return parts[:-1]
    return []


def _resolve_from_module(node: ast.ImportFrom, module_key: str) -> Optional[str]:
    """Resolves an `ImportFrom` node's base module to an absolute dotted name,
    handling relative imports (cycle 3/cycle 4 bypass #3): `from . import domain`
    yields `ImportFrom(module=None, level=1)` -- a naive `node.module.startswith(...)`
    raises `AttributeError` on this. Returns `None` when the base resolves to the
    project root itself (nothing left to join `node.module` onto) -- the caller then
    treats each alias name as itself the imported top-level target."""
    if node.level == 0:
        return node.module
    base_parts = _own_package_parts(module_key)
    climb = node.level - 1
    if climb > len(base_parts):
        return None  # climbs above anything this project's layout has
    if climb:
        base_parts = base_parts[: len(base_parts) - climb]
    if node.module:
        base_parts = base_parts + node.module.split(".")
    return ".".join(base_parts) if base_parts else None


def _resolve_permitted(module_key: str) -> Optional[FrozenSet[str]]:
    if module_key in ALLOWED_EDGES:
        return ALLOWED_EDGES[module_key]
    top = module_key.split(".", 1)[0]
    if top in ALLOWED_EDGES:
        return ALLOWED_EDGES[top]
    return None


# --- The checker itself -----------------------------------------------------------


def check_module(module_key: str, source: str, stdlib_names: FrozenSet[str]) -> List[str]:
    """Returns every violation found in one module's source text; an empty list
    means fully compliant. `module_key` is that module's own dotted path relative to
    plugin/server/ (e.g. "providers.base", "net.client", "composition")."""
    violations: List[str] = []
    own_top = module_key.split(".", 1)[0]
    permitted = _resolve_permitted(module_key)
    if permitted is None:
        violations.append(
            f"{module_key}: module is not listed in ALLOWED_EDGES -- "
            "unlisted modules fail outright, never a silent pass"
        )

    tree = ast.parse(source, filename=module_key)
    # ast.walk(tree), not tree.body -- a function-level or conditionally-nested
    # import is invisible to a tree.body-only scan (cycle 3/cycle 4 bypass #2).
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_target(alias.name, module_key, own_top, permitted, stdlib_names, violations, is_combined=False)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_module(node, module_key)
            for alias in node.names:
                if resolved is not None:
                    _check_target(
                        resolved, module_key, own_top, permitted, stdlib_names, violations, is_combined=False
                    )
                    combined = f"{resolved}.{alias.name}"
                else:
                    combined = alias.name
                # Both node.module alone AND module.alias per alias (cycle 4 finding)
                # -- checking node.module alone lets `from urllib import request`/
                # `from http import client` through undetected, since neither
                # string equals "urllib.request"/"http.client" as a bare module.
                _check_target(combined, module_key, own_top, permitted, stdlib_names, violations, is_combined=True)
    return violations


def _check_target(
    target: str,
    module_key: str,
    own_top: str,
    permitted: Optional[FrozenSet[str]],
    stdlib_names: FrozenSet[str],
    violations: List[str],
    *,
    is_combined: bool,
) -> None:
    # importlib is banned everywhere, including net/client.py (cycle 3 had granted
    # it there specifically; cycle 4 revoked that -- nothing in this plan ever
    # needs dynamic import, least of all in the one module where a dynamic-import
    # egress bypass would be most dangerous).
    if target == "importlib" or target.startswith("importlib."):
        violations.append(f"{module_key}: 'importlib' is banned everywhere (found '{target}')")
        return

    # xml.* is restricted to net/client.py (its parse_xml_guarded, T-6b).
    if (target == "xml" or target.startswith("xml.")) and module_key != NET_CLIENT_KEY:
        violations.append(f"{module_key}: 'xml' is restricted to {NET_CLIENT_KEY} (found '{target}')")
        return

    # The named egress/dynamic-code-capable stdlib modules, restricted to
    # net/client.py.
    if target in RESTRICTED_TO_NET_CLIENT and module_key != NET_CLIENT_KEY:
        violations.append(
            f"{module_key}: '{target}' is restricted to {NET_CLIENT_KEY} (found '{target}')"
        )
        return

    target_top = target.split(".", 1)[0]

    if target_top in _PROJECT_TOP_PACKAGES:
        if target_top == own_top:
            # Same-package: always allowed, except the one negative-direction rule.
            if module_key in _PROVIDERS_BASE_SIDE and (
                target == _INNERTUBE_KEY or target.startswith(_INNERTUBE_KEY + ".")
            ):
                violations.append(
                    f"{module_key}: may not import '{_INNERTUBE_KEY}' -- the one "
                    "same-package direction this project forbids (the abstraction "
                    "may not import its own concrete implementation)"
                )
            return
        if permitted is None:
            return  # already reported once as unlisted; avoid a flood of noise
        if not any(target == entry or target.startswith(entry + ".") for entry in permitted):
            violations.append(
                f"{module_key}: '{target}' is not a permitted cross-package import "
                f"(ALLOWED_EDGES[{module_key!r}] = {sorted(permitted)})"
            )
        return

    # Not a project package, not importlib/xml/the restricted-egress set above --
    # must be a genuine stdlib module (AC-14, zero pip dependencies). Skipped for
    # the combined module.alias form: it has the same top-level segment as the
    # already-checked bare-module form and would only duplicate that result.
    if is_combined:
        return
    if target_top not in stdlib_names:
        violations.append(
            f"{module_key}: '{target}' is not a stdlib module -- this project has "
            "zero pip dependencies (AC-14)"
        )


# --- The real tree: every current module must comply -----------------------------


class TestCurrentTreeCompliance(unittest.TestCase):
    def test_current_tree_satisfies_allowed_edges(self) -> None:
        stdlib_names = _stdlib_names_for_version(sys.version_info[:2])
        all_violations: List[str] = []
        files = _iter_server_py_files(_SERVER_DIR)
        self.assertGreater(len(files), 0, "expected at least one .py file under plugin/server/")
        for path in files:
            module_key = _module_key_for_path(path, _SERVER_DIR)
            with open(path, encoding="utf-8") as source_file:
                source = source_file.read()
            all_violations.extend(check_module(module_key, source, stdlib_names))
        self.assertEqual(all_violations, [], "\n".join(all_violations))


# --- Self-tests: one per confirmed-bypass class, named literally by T-3's check --


class TestUnlistedModuleFails(unittest.TestCase):
    def test_unlisted_module_fails(self) -> None:
        violations = check_module("scratch_module", "import os\n", _STDLIB_NAMES_3_13)
        self.assertTrue(
            any("not listed in ALLOWED_EDGES" in v for v in violations),
            violations,
        )


class TestFunctionNestedImportCaught(unittest.TestCase):
    def test_function_nested_import_caught(self) -> None:
        # tree.body-only scanning would miss this entirely -- it's nested inside a
        # FunctionDef, never a top-level statement.
        source = "def f():\n    import importlib\n"
        violations = check_module("domain", source, _STDLIB_NAMES_3_13)
        self.assertTrue(any("importlib" in v for v in violations), violations)


class TestRelativeImportResolved(unittest.TestCase):
    def test_relative_import_resolved(self) -> None:
        # `from .. import net` from within tools/cursor.py: ImportFrom(module=None,
        # level=2) -- a naive `node.module.startswith(...)` would raise
        # AttributeError here. Resolves to the top-level "net" package, which
        # tools/ has no permitted edge to -- proving both that resolution doesn't
        # crash on `module=None`, and that the resolved name is actually checked
        # (not silently skipped).
        source = "from .. import net\n"
        violations = check_module("tools.cursor", source, _STDLIB_NAMES_3_13)
        self.assertTrue(
            any("'net'" in v and "not a permitted cross-package import" in v for v in violations),
            violations,
        )


class TestImportlibBannedEverywhere(unittest.TestCase):
    def test_importlib_banned_everywhere(self) -> None:
        # net/client.py is otherwise the most-permitted module for egress-capable
        # stdlib names -- importlib is banned there too (cycle 4: revoked cycle 3's
        # net/client.py-specific grant).
        violations = check_module(NET_CLIENT_KEY, "import importlib\n", _STDLIB_NAMES_3_13)
        self.assertTrue(any("importlib" in v for v in violations), violations)


class TestFromUrllibImportRequestCaught(unittest.TestCase):
    def test_from_urllib_import_request_caught(self) -> None:
        # Checking node.module ("urllib") alone would miss this -- only the
        # combined "urllib.request" form (module + alias) matches the restricted
        # set.
        source = "from urllib import request\n"
        violations = check_module("providers.video_ref", source, _STDLIB_NAMES_3_13)
        self.assertTrue(
            any("urllib.request" in v and NET_CLIENT_KEY in v for v in violations), violations
        )


class TestFromHttpImportClientCaught(unittest.TestCase):
    def test_from_http_import_client_caught(self) -> None:
        source = "from http import client\n"
        violations = check_module("providers.base", source, _STDLIB_NAMES_3_13)
        self.assertTrue(
            any("http.client" in v and NET_CLIENT_KEY in v for v in violations), violations
        )


class TestAttributeAccessBypassDocumentedNotClosed(unittest.TestCase):
    def test_attribute_access_bypass_documented_not_closed(self) -> None:
        """Documents, as a passing test, exactly what this mechanism does NOT
        close (plan.md's "AST/text-ban mechanism is a regression guard, not a
        closed security boundary" section, bypass #1): a module that legitimately
        does `import urllib.parse` and later reaches `urllib.request` via plain
        attribute access on the shared `urllib` package object (once some other
        module -- net/client.py -- has imported `urllib.request` anywhere in the
        process) produces ZERO `ast.Import`/`ast.ImportFrom` node naming
        "urllib.request" in the bypassing module's own source. This check
        structurally cannot see it -- asserting that here, rather than silently
        discovering it later, is the honest way to record the mechanism's known
        limit: the load-bearing guarantee that egress stays inside net/client.py
        is code review of that one file, same as it always was. This test would
        need to start failing (a real regression) only if `urllib.request` were
        imported directly, which is a different, and closed, case."""
        source = (
            "import urllib.parse\n"
            "\n"
            "def use_it():\n"
            "    return urllib.request.urlopen('https://example.com')\n"
        )
        violations = check_module("providers.video_ref", source, _STDLIB_NAMES_3_13)
        self.assertEqual(violations, [])


class TestProvidersBaseCannotImportInnertube(unittest.TestCase):
    def test_providers_base_cannot_import_innertube(self) -> None:
        source = "from providers.innertube import InnertubeProvider\n"
        violations = check_module("providers.base", source, _STDLIB_NAMES_3_13)
        self.assertTrue(
            any(_INNERTUBE_KEY in v and "may not import" in v for v in violations), violations
        )
        # The reverse direction is fine -- providers/innertube.py already has a
        # permitted "net" edge and same-package access to providers/base.py.
        reverse_violations = check_module(
            _INNERTUBE_KEY, "from providers.base import ProviderError\n", _STDLIB_NAMES_3_13
        )
        self.assertEqual(reverse_violations, [])


# --- T-14: the real import graph, symbol-level, following re-exports -------------
#
# `TestCurrentTreeCompliance` above (T-3) already validates every module's own
# import statements against `ALLOWED_EDGES`, file by file -- but only ever checks
# the *immediately named* module of each import, via string-prefix matching
# (`"composition.TranscriptProvider".startswith("composition.")`). It cannot see
# past one hop: if some permitted module re-exports a name whose *true* origin is
# a module reached through an illegitimate hop somewhere upstream, nothing in that
# check resolves WHERE the symbol actually came from -- only that the directly-
# named module string is permitted.
#
# This section builds the real, symbol-level graph: for every `from X import
# NAME` anywhere under `plugin/server/**`, follow `NAME` through every re-export
# hop (a name that is itself bound via `from Y import NAME2` in X's own source,
# recursively) down to the module where it is genuinely, locally defined --
# then independently re-validates every hop in that chain against `ALLOWED_EDGES`
# right here, self-contained (not by relying on some other test having already
# checked the intermediate module's own file). This is the same property T-3's
# own check named only in `tasks.md` prose ("every imported symbol resolves to a
# module the importing module's ALLOWED_EDGES row actually permits") -- now
# actually falsifiable, against the real, fully-built graph.
#
# `composition.py`'s own module docstring is the concrete, sanctioned example this
# section must NOT flag: `server.py` does `from composition import
# TranscriptProvider`, whose true origin is `providers/base.py` -- `server`'s own
# `ALLOWED_EDGES` row has no direct `providers.base` entry, but the chain
# `server -> composition -> providers.base` is legitimate hop-by-hop
# (`server -> composition` and `composition -> providers.base` are each
# individually permitted), which is exactly what this check allows.


def _module_local_bindings(
    module_key: str, source: str
) -> Dict[str, Tuple[str, Optional[str], Optional[str]]]:
    """Every name `module_key` binds at module (top) scope, mapped to one of:

    - `("local", None, None)`: a genuine top-level `def`/`class`/assignment --
      the resolution terminus.
    - `("import_module", "<dotted module>", None)`: bound via a bare `import X`
      (or `import X as alias`) -- the whole module object, not a re-exportable
      symbol in the `from X import NAME` sense.
    - `("import", "<resolved source module>", "<source name>")`: bound via
      `from Y import NAME [as alias]` -- a re-export candidate, resolved further
      by the caller.

    Only `tree.body` (true top-level) bindings count -- a name bound inside a
    function/class body is not reachable via `from module_key import name` from
    another module at all, so it is correctly invisible here.
    """
    tree = ast.parse(source, filename=module_key)
    bindings: Dict[str, Tuple[str, Optional[str], Optional[str]]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[node.name] = ("local", None, None)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = ("local", None, None)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bindings[node.target.id] = ("local", None, None)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                bindings[bound_name] = ("import_module", alias.name, None)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_module(node, module_key)
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if resolved is None:
                    bindings[bound_name] = ("import_module", alias.name, None)
                else:
                    bindings[bound_name] = ("import", resolved, alias.name)
    return bindings


def _resolve_symbol_chain(
    module_key: str,
    name: str,
    file_sources: Dict[str, str],
    _visited: Tuple[str, ...] = (),
) -> List[str]:
    """Returns `[module_key, ..., origin_module]`, the full chain of modules this
    symbol's resolution passes through, ending at the module where `name` is
    genuinely defined (or a bare-`import`-module re-export terminus). Returns
    `[module_key]` alone if `module_key` isn't one of this project's own modules,
    if a cycle is detected (self-referential re-export -- pathological, but this
    must terminate rather than recurse forever), or if `name` isn't found bound
    at that module's top scope at all (a wildcard import or a genuinely broken
    import -- the caller treats an unresolvable chain as its own violation)."""
    if module_key in _visited or module_key not in file_sources:
        return [module_key]
    bindings = _module_local_bindings(module_key, file_sources[module_key])
    if name not in bindings:
        return [module_key]
    kind, target, source_name = bindings[name]
    if kind == "local" or target is None:
        return [module_key]
    if kind == "import_module" or source_name is None:
        return [module_key, target]
    return [module_key, *_resolve_symbol_chain(
        target, source_name, file_sources, (*_visited, module_key)
    )]


def _hop_is_permitted(earlier: str, later: str) -> bool:
    earlier_top = earlier.split(".", 1)[0]
    later_top = later.split(".", 1)[0]
    if earlier_top == later_top:
        return True  # same-package hop, always allowed (general rule)
    permitted = _resolve_permitted(earlier)
    if permitted is None:
        return False
    return any(later == entry or later.startswith(entry + ".") for entry in permitted)


class TestRealImportGraphMatchesAllowedEdges(unittest.TestCase):
    def test_real_import_graph_matches_allowed_edges(self) -> None:
        files = _iter_server_py_files(_SERVER_DIR)
        file_sources: Dict[str, str] = {}
        for path in files:
            module_key = _module_key_for_path(path, _SERVER_DIR)
            with open(path, encoding="utf-8") as source_file:
                file_sources[module_key] = source_file.read()

        violations: List[str] = []
        for module_key, source in file_sources.items():
            tree = ast.parse(source, filename=module_key)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                resolved = _resolve_from_module(node, module_key)
                if resolved is None:
                    continue
                resolved_top = resolved.split(".", 1)[0]
                # Only this project's own modules can "re-export" a symbol in the
                # sense this check resolves -- a stdlib/third-party import has no
                # further chain to follow, and is already fully covered by
                # TestCurrentTreeCompliance's own stdlib/restricted-egress checks.
                if resolved_top not in _PROJECT_TOP_PACKAGES:
                    continue
                for alias in node.names:
                    chain = [module_key, *_resolve_symbol_chain(resolved, alias.name, file_sources)]
                    for earlier, later in zip(chain, chain[1:]):
                        if not _hop_is_permitted(earlier, later):
                            violations.append(
                                f"{module_key}: symbol {alias.name!r} imported from "
                                f"{resolved!r} resolves via {chain!r}, and hop "
                                f"{earlier!r} -> {later!r} is not a permitted "
                                f"ALLOWED_EDGES edge"
                            )
        self.assertEqual(violations, [], "\n".join(violations))


class TestRealImportGraphCatchesForgedReexportChain(unittest.TestCase):
    def test_real_import_graph_catches_forged_reexport_chain(self) -> None:
        """Self-test proving the mechanism actually fires: `formats` has no
        permitted edge to `providers.innertube` (`ALLOWED_EDGES["formats"] ==
        {"domain"}`). A synthetic module that legitimately imports from
        `formats` (permitted for `tools`) re-exporting a name whose *true* origin
        is `providers.innertube` must be caught -- proving this check sees past
        the one hop `TestCurrentTreeCompliance`'s own per-file scan cannot."""
        file_sources = {
            "formats": "from providers.innertube import InnertubeProvider as smuggled\n",
            "providers.innertube": "class InnertubeProvider:\n    pass\n",
        }
        chain = ["tools", *_resolve_symbol_chain("formats", "smuggled", file_sources)]
        self.assertEqual(chain, ["tools", "formats", "providers.innertube"])
        violations = [
            (earlier, later)
            for earlier, later in zip(chain, chain[1:])
            if not _hop_is_permitted(earlier, later)
        ]
        self.assertEqual(violations, [("formats", "providers.innertube")])


class TestStdlibCheckAgainstCommittedPerLegLists(unittest.TestCase):
    def test_stdlib_check_against_committed_per_leg_lists(self) -> None:
        # The two lists must genuinely differ -- guards against cycle 5's own bug
        # (both generated from the same 3.10+ interpreter, making the check
        # vacuous on whichever leg it wasn't generated for).
        self.assertNotEqual(_STDLIB_NAMES_3_9, _STDLIB_NAMES_3_13)
        # distutils/smtpd/asynchat/asyncore/imp/parser/symbol/formatter/lib2to3 and
        # the PEP 594 dead-battery modules exist pre-3.10-ish removal waves, absent
        # from the 3.13 list (verified against this machine's real
        # /usr/local/bin/python3.13 interpreter's own sys.stdlib_module_names).
        for name in ("distutils", "smtpd", "asynchat", "crypt", "nntplib"):
            self.assertIn(name, _STDLIB_NAMES_3_9)
            self.assertNotIn(name, _STDLIB_NAMES_3_13)
        # tomllib is the reverse: added in 3.11, absent from 3.9.
        self.assertIn("tomllib", _STDLIB_NAMES_3_13)
        self.assertNotIn("tomllib", _STDLIB_NAMES_3_9)
        # The selector picks the right list purely from version_info, for both
        # legs and for versions newer than either committed list's own version
        # (e.g. this repo's own 3.14 interpreter selects the 3.13-leg list).
        self.assertEqual(_stdlib_names_for_version((3, 9)), _STDLIB_NAMES_3_9)
        self.assertEqual(_stdlib_names_for_version((3, 13)), _STDLIB_NAMES_3_13)
        self.assertEqual(_stdlib_names_for_version((3, 14)), _STDLIB_NAMES_3_13)


if __name__ == "__main__":
    unittest.main()
