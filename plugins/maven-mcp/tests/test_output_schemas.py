"""Tool annotations + outputSchema/structuredContent tests (#398).

Covers three things the MCP protocol-revision bump added to every shipped
tool's ``tools/list`` entry and (for a 14/20 subset) to ``tools/call``
results:

1. Every tool carries ``annotations`` with the correct ``readOnlyHint`` /
   ``openWorldHint`` (see AnnotationsTest) — this server's tools are all
   read-only queries, so this is uniform except ``openWorldHint`` for the one
   purely-local tool (``catalog_entry``).
2. A tractable subset of tools declared an ``outputSchema`` describing their
   structured result shape (see OutputSchemaWellFormedTest for presence, and
   the omission list for which 6 tools deliberately did not, and why).
3. For every tool that DID declare an outputSchema, a representative
   ``structuredContent`` result — round-tripped through the real dispatcher,
   not just checked in isolation — validates against that schema (see
   StructuredContentRoundTripTest). This is the correctness gate a wrong
   schema would fail even though the code "looks right": a schema that
   rejects the shape its own handler actually returns is worse than no
   schema at all (a strict client would treat every call as protocol-invalid).

The validator below is a minimal, stdlib-only JSON Schema SUBSET (type /
properties / required / items / enum) — exactly what this project's
outputSchema declarations use, not a general-purpose implementation. Adding a
real `jsonschema` dependency for this would violate the project's zero-pip-
dependency ethos for a check this narrow in scope.
"""

import json
import unittest
import unittest.mock

from _helpers import server

# Tools deliberately shipped WITHOUT an outputSchema (#398) — each reason is
# echoed as an inline comment on the tool's own "annotations" line in
# server.py's TOOLS list; kept here too so a future accidental addition/removal
# is caught by test_every_tool_is_accounted_for below.
_TOOLS_WITHOUT_OUTPUT_SCHEMA = frozenset({
    "get_dependency_changes",
    "scan_project_dependencies",
    "get_dependency_health",
    "search_artifacts",
    "audit_project_dependencies",
    "catalog_entry",
})


def _type_matches(instance, expected_type):
    if expected_type == "object":
        return isinstance(instance, dict)
    if expected_type == "array":
        return isinstance(instance, list)
    if expected_type == "string":
        return isinstance(instance, str)
    if expected_type == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected_type == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected_type == "boolean":
        return isinstance(instance, bool)
    if expected_type == "null":
        return instance is None
    raise AssertionError(f"validator does not know type {expected_type!r}")


def validate_against_schema(instance, schema, path="$"):
    """Minimal JSON Schema subset validator; raises AssertionError on mismatch.

    Supports exactly what this project's outputSchema dicts use: ``type``
    (single or a list for a union, e.g. ``["string", "null"]``), ``enum``,
    ``properties`` + ``required`` (object), and ``items`` (array). Unknown
    instance keys are always allowed — outputSchema is deliberately left open
    (no ``additionalProperties: False``), so this validator does not enforce
    closure either; see the comment on _GAV_SCHEMA in server.py for why.
    """
    if not isinstance(schema, dict):
        return
    schema_type = schema.get("type")
    if schema_type is not None:
        types = schema_type if isinstance(schema_type, list) else [schema_type]
        if not any(_type_matches(instance, t) for t in types):
            raise AssertionError(
                f"{path}: expected type {schema_type!r}, got {type(instance).__name__} ({instance!r})"
            )
    if "enum" in schema and instance not in schema["enum"]:
        raise AssertionError(f"{path}: value {instance!r} not in enum {schema['enum']!r}")
    if isinstance(instance, dict):
        for key in schema.get("required") or []:
            if key not in instance:
                raise AssertionError(f"{path}: missing required key {key!r} (instance={instance!r})")
        properties = schema.get("properties") or {}
        for key, sub_schema in properties.items():
            if key in instance:
                validate_against_schema(instance[key], sub_schema, f"{path}.{key}")
    elif isinstance(instance, list):
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(instance):
                validate_against_schema(item, items_schema, f"{path}[{i}]")


def _minimal_valid_arguments(tool_name):
    """Placeholder ``arguments`` satisfying ``tool_name``'s own top-level
    ``inputSchema.required`` -- just enough for _handle_tools_call's
    required-argument pre-check (against TOOL_SCHEMAS) to pass, so a
    round-trip test actually reaches the (fake) handler instead of getting a
    -32602 Invalid params first. Every required field across the 14
    outputSchema tools is either a plain string (groupId/artifactId/version)
    or "dependencies" (an array) -- this does not need to be exhaustive
    beyond that.
    """
    required = (server.TOOL_SCHEMAS.get(tool_name) or {}).get("required") or []
    return {name: ([] if name == "dependencies" else "placeholder") for name in required}


class SelfTestValidator(unittest.TestCase):
    """The validator itself must actually reject wrong shapes, not just accept everything."""

    def test_rejects_wrong_type(self):
        with self.assertRaises(AssertionError):
            validate_against_schema("not an int", {"type": "integer"})

    def test_rejects_missing_required_key(self):
        with self.assertRaises(AssertionError):
            validate_against_schema({"a": 1}, {"type": "object", "required": ["b"]})

    def test_rejects_bad_enum_value(self):
        with self.assertRaises(AssertionError):
            validate_against_schema("maybe", {"type": "string", "enum": ["yes", "no"]})

    def test_accepts_union_type(self):
        validate_against_schema(None, {"type": ["string", "null"]})
        validate_against_schema("x", {"type": ["string", "null"]})

    def test_extra_instance_keys_are_allowed(self):
        # outputSchema is deliberately open (no additionalProperties: False).
        validate_against_schema(
            {"known": 1, "extraFutureField": "x"},
            {"type": "object", "properties": {"known": {"type": "integer"}}},
        )


class AnnotationsTest(unittest.TestCase):
    """Every tool must carry read-only-query annotations (#398)."""

    def test_every_tool_has_annotations(self):
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]):
                self.assertIn("annotations", tool)
                self.assertIsInstance(tool["annotations"], dict)

    def test_every_tool_is_read_only(self):
        # Every maven-mcp tool queries — none mutates the user's project or
        # any remote — so readOnlyHint is uniformly True.
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]):
                self.assertIs(tool["annotations"].get("readOnlyHint"), True)

    def test_catalog_entry_is_the_only_closed_world_tool(self):
        # catalog_entry does pure local TOML generation/validation — no
        # network call anywhere in generate_catalog_entry/validate_catalog.
        # Every other tool reaches an external repo/registry/API.
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]):
                expected_open_world = tool["name"] != "catalog_entry"
                self.assertIs(tool["annotations"].get("openWorldHint"), expected_open_world)

    def test_no_tool_sets_destructive_or_idempotent_hint(self):
        # Both are documented (ToolAnnotations, MCP schema) as "meaningful
        # only when readOnlyHint == false" — since every tool here is
        # readOnlyHint: true, setting either would be noise, not signal.
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]):
                self.assertNotIn("destructiveHint", tool["annotations"])
                self.assertNotIn("idempotentHint", tool["annotations"])


class OutputSchemaWellFormedTest(unittest.TestCase):
    """Presence/shape of outputSchema, and the TOOLS_WITH_OUTPUT_SCHEMA index."""

    def test_every_tool_is_accounted_for(self):
        # Every tool is EITHER in the with-schema set XOR the deliberate
        # omission list above -- catches an accidental silent addition or
        # removal on either side as this list evolves.
        all_names = {t["name"] for t in server.TOOLS}
        self.assertEqual(_TOOLS_WITHOUT_OUTPUT_SCHEMA | server.TOOLS_WITH_OUTPUT_SCHEMA, all_names)
        self.assertEqual(_TOOLS_WITHOUT_OUTPUT_SCHEMA & server.TOOLS_WITH_OUTPUT_SCHEMA, set())

    def test_tools_with_output_schema_matches_declared_set(self):
        declared = {t["name"] for t in server.TOOLS if "outputSchema" in t}
        self.assertEqual(declared, server.TOOLS_WITH_OUTPUT_SCHEMA)

    def test_each_output_schema_is_a_well_formed_object_schema(self):
        for tool in server.TOOLS:
            if tool["name"] not in server.TOOLS_WITH_OUTPUT_SCHEMA:
                continue
            with self.subTest(tool=tool["name"]):
                schema = tool["outputSchema"]
                self.assertIsInstance(schema, dict)
                self.assertEqual(schema.get("type"), "object")
                self.assertIsInstance(schema.get("properties"), dict)
                self.assertTrue(schema["properties"], "outputSchema.properties must not be empty")

    def test_no_schema_tools_have_no_output_schema_key(self):
        for tool in server.TOOLS:
            if tool["name"] in _TOOLS_WITHOUT_OUTPUT_SCHEMA:
                with self.subTest(tool=tool["name"]):
                    self.assertNotIn("outputSchema", tool)


# One realistic success-path fixture per outputSchema tool -- each is checked
# both directly against the schema (below) and round-tripped through the real
# tools/call dispatcher (StructuredContentRoundTripTest) so the wiring itself
# (structuredContent === content[0].text JSON) is exercised too, not just the
# schema shape in isolation.
_FIXTURES = {
    "get_latest_version": {
        "groupId": "com.squareup.okhttp3",
        "artifactId": "okhttp",
        "latestVersion": "4.12.0",
        "stability": "STABLE",
        "allVersionsCount": 42,
        "resolvedFrom": {"url": "https://repo1.maven.org/maven2/", "scope": "dependency", "viaPublicFallback": False},
    },
    "check_version_exists": {
        "groupId": "com.squareup.okhttp3",
        "artifactId": "okhttp",
        "version": "4.12.0",
        "exists": True,
        "stability": "STABLE",
        "repository": "central",
        "resolvedFrom": {"url": "https://repo1.maven.org/maven2/", "scope": "dependency", "viaPublicFallback": False},
    },
    "check_multiple_dependencies": {
        "results": [
            {
                "groupId": "com.squareup.okhttp3", "artifactId": "okhttp",
                "latestVersion": "4.12.0", "stability": "STABLE",
                "resolvedFrom": {"url": "https://repo1.maven.org/maven2/", "scope": "dependency", "viaPublicFallback": False},
            },
            {"groupId": "com.example", "artifactId": "nope", "latestVersion": "", "stability": "", "error": "No version found"},
        ],
    },
    "compare_dependency_versions": {
        "results": [
            {
                "groupId": "com.squareup.okhttp3", "artifactId": "okhttp",
                "currentVersion": "3.0.0", "latestVersion": "4.12.0", "latestStability": "STABLE",
                "upgradeType": "major", "upgradeAvailable": True,
                "resolvedFrom": {"url": "https://repo1.maven.org/maven2/", "scope": "dependency", "viaPublicFallback": False},
            },
        ],
        "summary": {"total": 1, "upgradeable": 1, "major": 1, "minor": 0, "patch": 0},
    },
    "expand_bom": {
        "groupId": "org.springframework.boot", "artifactId": "spring-boot-dependencies", "version": "3.2.0",
        "managed": [{"groupId": "com.fasterxml.jackson.core", "artifactId": "jackson-databind", "version": "2.15.3"}],
    },
    "get_transitive_graph": {
        "groupId": "com.example", "artifactId": "app", "version": "1.0",
        "nodes": [{"groupId": "com.example", "artifactId": "app", "version": "1.0"}],
        "edges": [{"from": 0, "to": 0}],
        "partial": False, "truncated": False,
    },
    "get_vulnerability_paths": {
        "groupId": "com.example", "artifactId": "app", "version": "1.0",
        "vulnerabilityPaths": [
            {
                "vulnerableNode": "com.example:vulnerable-lib:1.0",
                "path": [
                    {"groupId": "com.example", "artifactId": "app", "version": "1.0"},
                    {"groupId": "com.example", "artifactId": "vulnerable-lib", "version": "1.0"},
                ],
                "vulnerabilities": [
                    {"id": "GHSA-xxxx-yyyy-zzzz", "summary": "desc", "url": "https://example.com", "malicious": False, "severity": "HIGH", "fixedVersion": "1.1"},
                ],
            },
        ],
        "partial": False, "truncated": False,
    },
    "detect_dependency_conflicts": {
        "buildSystem": "gradle", "strategy": "highest-wins",
        "conflicts": [
            {
                "groupId": "com.example", "artifactId": "shared-lib", "versions": ["1.0", "1.1"],
                "resolvedTo": "1.1", "strategy": "highest-wins", "risk": "low",
                "sources": [{"version": "1.0", "via": ["root"], "minDepth": 1}],
            },
        ],
        "scannedRoots": 1, "graphsFetched": 1, "graphsFailed": 0, "partial": False, "errors": [], "notes": [],
    },
    "check_version_compatibility": {
        "compatible": False,
        "conflicts": [
            {
                "kind": "agp_gradle",
                "requested": {"agp": "8.0", "gradle": "7.0"},
                "expected": {"minGradle": "8.0"},
                "suggestion": {"agp": "8.0", "gradle": "8.0", "jdk": 17},
                "reference": "https://developer.android.com/build/releases/about-agp",
            },
        ],
        "notes": [],
    },
    "get_dependency_vulnerabilities": {
        "results": [
            {
                "groupId": "com.example", "artifactId": "vulnerable-lib", "version": "1.0",
                "vulnerabilities": [
                    {"id": "GHSA-xxxx-yyyy-zzzz", "summary": "desc", "url": None, "malicious": False},
                ],
                "vulnerabilityCount": 1,
                "safeUpgrade": {"version": "1.1", "fixesAllKnown": True},
            },
        ],
    },
    "get_dependency_license": {
        "results": [
            {
                "groupId": "com.squareup.okhttp3", "artifactId": "okhttp", "version": "4.12.0",
                "spdxId": "Apache-2.0", "name": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0",
                "category": "permissive", "notes": "Permissive license.", "source": "pom",
            },
        ],
    },
    "check_license_compliance": {
        "policy": {"disallow": ["strong-copyleft", "network-copyleft", "proprietary"]},
        "summary": {
            "total": 1,
            "byVerdict": {"ok": 1, "review": 0, "violation": 0},
            "byCategory": {"permissive": 1},
            "violationCount": 0,
            "reviewCount": 0,
        },
        "results": [
            {
                "groupId": "com.example", "artifactId": "app", "version": "1.0",
                "license": "Apache-2.0", "licenses": ["Apache-2.0"], "category": "permissive",
                "viaTransitive": False, "relation": "SELF", "verdict": "ok", "reason": "permissive license",
                "root": {"groupId": "com.example", "artifactId": "app", "version": "1.0"}, "source": "deps.dev",
            },
        ],
        "partial": False, "notes": [],
    },
    "verify_coordinates": {
        "results": [
            {
                "groupId": "com.squareup.okhttp3", "artifactId": "okhttp", "version": "4.12.0",
                "existenceStatus": "exists", "gaExists": True, "gavExists": True, "stability": "STABLE",
                "repository": "central", "likelyHallucination": False,
                "typosquatRisk": {"signal": False, "reasons": [], "versionCount": 60},
            },
            {
                "groupId": "com.example", "artifactId": "totally-made-up-lib",
                "existenceStatus": "absent", "gaExists": False, "likelyHallucination": True,
                "suggestions": [{"groupId": "com.example", "artifactId": "real-lib", "score": 0.9, "versionCount": 10}],
            },
        ],
    },
    "get_eol_status": {
        "results": [
            {
                "product": "gradle", "requestedVersion": "8.5", "cycle": "8",
                "isEol": False, "eolDate": None, "isMaintained": True, "isLts": False, "latestInCycle": "8.10",
            },
            {"product": "kotlin", "requestedVersion": "9.9.9", "error": "no matching release cycle found for version '9.9.9'"},
        ],
    },
}


class StructuredContentRoundTripTest(unittest.TestCase):
    """Fixtures both validate directly AND round-trip through the real dispatcher."""

    def test_fixtures_cover_every_output_schema_tool(self):
        self.assertEqual(set(_FIXTURES.keys()), server.TOOLS_WITH_OUTPUT_SCHEMA)

    def test_fixture_validates_directly_against_its_schema(self):
        tools_by_name = {t["name"]: t for t in server.TOOLS}
        for tool_name, fixture in _FIXTURES.items():
            with self.subTest(tool=tool_name):
                schema = tools_by_name[tool_name]["outputSchema"]
                validate_against_schema(fixture, schema)

    def test_structured_content_round_trips_through_dispatch(self):
        for tool_name, fixture in _FIXTURES.items():
            with self.subTest(tool=tool_name):

                def _fake_handler(_arguments, _fixture=fixture):
                    return dict(_fixture)

                with unittest.mock.patch.dict(server.TOOL_HANDLERS, {tool_name: _fake_handler}):
                    msg = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        # Real dispatch runs a required-argument PRE-CHECK against
                        # the tool's own inputSchema before the (fake) handler is
                        # ever invoked -- placeholder args must satisfy it, or
                        # this only tests the -32602 path, not the real one.
                        "params": {"name": tool_name, "arguments": _minimal_valid_arguments(tool_name)},
                    }
                    response = server._dispatch_message(msg)
                result = response["result"]
                self.assertNotIn("isError", result)
                self.assertEqual(result["structuredContent"], fixture)
                # The text content must be exactly the same object, serialized —
                # never a second, independently-built representation.
                self.assertEqual(json.loads(result["content"][0]["text"]), fixture)
                # And it must independently validate against the declared schema
                # too, not just equal the fixture (guards against a schema that
                # would have rejected its own tool's real output).
                tool = next(t for t in server.TOOLS if t["name"] == tool_name)
                validate_against_schema(result["structuredContent"], tool["outputSchema"])

    def test_check_version_exists_false_branch_validates_too(self):
        # The minimal "not found" shape (most fields simply absent, not null)
        # must ALSO satisfy the schema -- required only lists the 4 fields
        # that are unconditionally present on every branch.
        fixture = {"groupId": "com.example", "artifactId": "nope", "version": "9.9.9", "exists": False}
        tool = next(t for t in server.TOOLS if t["name"] == "check_version_exists")
        validate_against_schema(fixture, tool["outputSchema"])


if __name__ == "__main__":
    unittest.main()
