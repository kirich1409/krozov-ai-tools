"""Validate TOOLS inputSchema declarations (#358).

Pins well-formedness of every shipped tool's inputSchema and agreement with
TOOL_HANDLERS — a missing/renamed handler or a malformed schema would otherwise
only surface at runtime when a client calls tools/list or tools/call.
"""

import unittest

from _helpers import server


class ToolsSchemaTest(unittest.TestCase):
    """TOOLS entries must be well-formed and match TOOL_HANDLERS 1:1."""

    def test_tools_and_handlers_agree(self):
        tool_names = [t["name"] for t in server.TOOLS]
        self.assertEqual(len(tool_names), len(set(tool_names)), "duplicate TOOLS name")
        self.assertEqual(set(tool_names), set(server.TOOL_HANDLERS.keys()))
        # Preserve declaration order: handlers dict follows TOOLS order.
        self.assertEqual(tool_names, list(server.TOOL_HANDLERS.keys()))

    def test_each_tool_has_well_formed_input_schema(self):
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]):
                self.assertIsInstance(tool.get("name"), str)
                self.assertTrue(tool["name"])
                self.assertIsInstance(tool.get("description"), str)
                self.assertTrue(tool["description"])

                schema = tool.get("inputSchema")
                self.assertIsInstance(schema, dict)
                self.assertEqual(schema.get("type"), "object")

                properties = schema.get("properties", {})
                self.assertIsInstance(properties, dict)
                for prop_name, prop_schema in properties.items():
                    self.assertIsInstance(prop_name, str)
                    self.assertIsInstance(prop_schema, dict)
                    self.assertIn(
                        "type",
                        prop_schema,
                        f"{tool['name']}.{prop_name} missing type",
                    )

                required = schema.get("required", [])
                self.assertIsInstance(required, list)
                for req in required:
                    self.assertIsInstance(req, str)
                    self.assertIn(
                        req,
                        properties,
                        f"{tool['name']} required {req!r} not in properties",
                    )

    def test_handlers_are_callable(self):
        for name, handler in server.TOOL_HANDLERS.items():
            with self.subTest(tool=name):
                self.assertTrue(callable(handler), f"{name} handler is not callable")

    def _assert_object_schemas_closed(self, schema, path):
        """Recursively assert every ``type: object`` node sets additionalProperties: False.

        The server does not itself run a JSON Schema validator against
        inputSchema (stdlib-only, no jsonschema dependency) — `maxItems` and
        friends are advisory client-side metadata (see server.py's own
        comments on this). additionalProperties: False is the one piece of
        schema tightening a spec-compliant MCP client (or a well-behaved LLM)
        DOES enforce client-side, so pinning it here is the correctness gate
        (#399), not runtime validation.
        """
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "object":
            self.assertIs(
                schema.get("additionalProperties"),
                False,
                f"{path}: object schema must set additionalProperties: False",
            )
            for prop_name, prop_schema in (schema.get("properties") or {}).items():
                self._assert_object_schemas_closed(prop_schema, f"{path}.{prop_name}")
        elif schema.get("type") == "array":
            items = schema.get("items")
            if items:
                self._assert_object_schemas_closed(items, f"{path}[]")

    def test_object_schemas_reject_additional_properties(self):
        # Every tool's top-level inputSchema, and every nested object schema
        # (array items, nested option bags), must be closed — an LLM client
        # should never be invited to guess at unsupported properties (#399).
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]):
                self._assert_object_schemas_closed(tool["inputSchema"], tool["name"])

    def test_no_tool_description_references_agents_md(self):
        # AGENTS.md is a repo file never seen by an MCP client — any guidance
        # a tool needs must be inline in description or in the response's
        # notes[] field, not a pointer to a file the model can't read (#399).
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]):
                self.assertNotIn("AGENTS.md", tool["description"])


if __name__ == "__main__":
    unittest.main()
