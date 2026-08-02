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
"""

import ast
import os
import unittest
from typing import List

_SERVER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "server")
)


def _iter_server_py_files(server_dir: str) -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(server_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


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


if __name__ == "__main__":
    unittest.main()
