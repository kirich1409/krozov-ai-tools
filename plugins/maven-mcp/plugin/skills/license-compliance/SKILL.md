---
name: license-compliance
description: >-
  Use when the user asks "check license compliance across my dependency tree", "are any of
  my transitive dependencies GPL", "scan for copyleft licenses", "flag license violations
  against our policy", or wants the FULL transitive closure of one or more root
  dependencies checked against a project license posture — not just the direct
  dependency's own license (see /dependency-license for that).
---

# License Compliance

Aggregate SPDX licenses across the full transitive closure of one or more root Maven GAVs
and flag risky/incompatible licenses against a project license posture or an explicit
disallow list.

## Steps

1. Parse root dependencies the user wants scanned — `groupId`, `artifactId`, `version`
   (version required per entry; capped at 20 roots).

2. Ask (if not already stated) which policy applies:
   - `projectLicense` — an SPDX id or license name; a **permissive** posture (or omitted
     `projectLicense`) defaults to disallowing `strong-copyleft`, `network-copyleft`, and
     `proprietary`.
   - `disallow` — explicit SPDX ids and/or category names; when set, this **replaces** the
     default disallow set entirely rather than adding to it.

3. Call **`check_license_compliance`** with `dependencies`, optional `projectLicense`,
   optional `disallow`.

4. Present per-node verdicts: `ok` / `review` / `violation`, with
   `groupId:artifactId:version`, `spdxId`/`license`, `category`, `viaTransitive` (direct vs
   transitive), and `reason`. Group by verdict, `violation` first. Missing/unrecognized
   license metadata is `review`, never a silent `ok` — present it as needing a human look,
   not as clean.

## Known limitations

This is a heuristic policy signal, not legal advice — say so when a violation is reported.
Deps.dev package-metadata SPDX only; per-root graphs are resolved in isolation (same
caveats as `/transitive-graph` and `/dependency-conflicts`); a compound SPDX expression
(`A OR B`) or an operator beyond a single known id degrades to `review`.

## Constraints and non-goals

- Not for a single dependency's own license with no transitive scan needed — use
  `/dependency-license`.

## Fallback (MCP unavailable only)

No practical manual fallback — walking a full transitive graph and fetching per-node
license metadata by hand does not scale. Tell the user this check is unavailable rather
than approximating it from the direct dependency's license alone.
