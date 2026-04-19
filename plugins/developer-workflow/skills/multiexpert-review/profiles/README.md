# multiexpert-review — profile contract

Profiles parameterize `multiexpert-review` for specific artifact types (plan, test-plan, spec, etc.). The engine (`../SKILL.md`) is artifact-agnostic; all artifact-specific logic lives here.

## Canonical inventory

```
PROFILE_INVENTORY = [implementation-plan, test-plan, spec]
```

(All three profiles exist as of this writing: `implementation-plan.md`, `test-plan.md`, `spec.md`.)

This list is **authoritative**. The engine reads it on startup by parsing this file. Adding a profile requires: (1) create `profiles/<name>.md`, (2) add `<name>` to the list above in the same commit. Mismatch (file exists but not in list, or list entry with no file) → engine fails with `[multiexpert-review ERROR] PROFILE_INVENTORY_MISMATCH: <name> <direction>`.

**Parser format (engine contract):** the engine matches the first line in this file that satisfies the regex `^PROFILE_INVENTORY\s*=\s*\[([^\]]+)\]\s*$`. The capture group is split on `,` and each element is trimmed of whitespace. The line MUST live inside a fenced code block (``` ```) so prose edits above do not accidentally match it. Editors of this file must preserve the exact variable name `PROFILE_INVENTORY`, the `=` token, and the single-line `[...]` form — no multi-line arrays, no quoted strings, no trailing commas.

## Profile schema (frontmatter)

Each `profiles/<name>.md` starts with YAML frontmatter declaring:

```yaml
---
name: <implementation-plan | test-plan | spec | ...>     # must match inventory entry
description: <one-line human-readable summary>

detect:
  frontmatter_type: [...]              # artifact frontmatter `type:` values that trigger this profile
  path_globs: [...]                    # filesystem globs, e.g. "docs/specs/**"
  structural_signatures: [...]         # regex patterns; ALL must match for signature-based detection

reviewer_roster:
  primary: [agent-name, ...]           # mandatory roster; missing agents are skipped per AC-S5
  optional_if:                         # conditional additions
    - when: "<regex over artifact content>"
      agent: <agent-name>

allow_single_reviewer: true | false    # required; if false, engine fails when only 1 agent available

verdicts: [PASS, CONDITIONAL, FAIL] | [PASS, WARN, FAIL]
                                       # verdict alphabet — engine enforces one of these two sets

severity_mapping:                      # optional; used for rubric-checklist profiles (e.g. test-plan)
  - items: ["<id>", ...]
    severity: critical | major | minor

source_routing:
  plan_mode: <action>                  # e.g. EnterPlanMode, edit-in-place, inline-revise
  file: <action>
  conversation: <action>

receipt:                               # OPTIONAL section — absence means no receipt is written
  path_template: "<path with <slug> placeholder>"
  fields_to_update: [<field>, ...]
---

## Rubric
(artifact-specific review criteria in markdown; agents evaluate against these)

## Prompt augmentation
(optional: extra text added to the Step 3 review prompt for this profile)
```

## Negative-list — fields FORBIDDEN in profile frontmatter

The engine owns these concerns; profiles **must not** declare any of:

- `output_schema` — review output structure (Summary / Domain Relevance / Issues) is engine-fixed
- `aggregation_strategy` — synthesis rules (convergence, contradictions, confidence-weighting) are engine-fixed
- `state_transitions` — state machine transitions are engine-constant
- `revise_loop_cap` — max 3 cycles is engine-constant
- `review_prompt_template` — Step 3 prompt template skeleton is engine-fixed; profiles use `## Prompt augmentation` section for additive customization

Presence of any forbidden field → engine refuses to load the profile: `[multiexpert-review ERROR] FORBIDDEN_PROFILE_FIELD: profile <name> declares forbidden field <field>`.

## Detection precedence (Step 1 of engine)

1. **Explicit caller hint** — args prefix `profile: <name>\n---\n`. Both lines MUST start at **column 0** (no leading whitespace / indentation — the engine matches `^profile:\s+(\S+)\s*$` on line 1 and `^---\s*$` on line 2). Callsites embedding this block inside markdown lists or docs must unindent the example so contributors copy it verbatim without stray indentation. Unknown `<name>` → fail loud `UNKNOWN_PROFILE_HINT`.
2. **Frontmatter type** — artifact's YAML frontmatter `type:` value; first profile whose `detect.frontmatter_type` list contains that value wins.
3. **Path glob** — artifact file path; first profile with matching `detect.path_globs` wins.
4. **Structural signatures** — all regexes in `detect.structural_signatures` must match artifact content. First profile whose signatures all match wins.
5. **Fallback — ask user** — engine presents `AskUserQuestion` with `PROFILE_INVENTORY` options. Never silent default.

## Cycle-locking

The selected profile is recorded in the state file at cycle 1. For cycles ≥2, the engine reads the profile **only** from the state file. Any profile hint in re-invocation args is ignored with a warning entry in Verdict History: `Cycle <N> ignoring profile hint '<value>' — locked to '<locked>' since cycle 1`. This is not fail-loud — the engine continues on the locked profile.

## Source routing — `N/A` semantics

When a profile declares a source as `N/A` (e.g., `source_routing.plan_mode: N/A` on the test-plan profile), the profile asserts that source is not applicable for this artifact type. If the engine nevertheless encounters that source at Step 5 (e.g., a test-plan somehow arrives as a Plan Mode artifact), the engine fails loud with `[multiexpert-review ERROR] ROUTING_NOT_SUPPORTED: profile <name> does not support source <source>`. This category sits under the unified error prefix — consumers may detect it like any other engine error.

## Severity mapping — item identifier convention

Profiles whose rubric is a **labeled checklist** with short IDs (e.g. test-plan items `(a)`–`(e)`) SHOULD use the matching single-letter or short-ID strings in `severity_mapping.items` — `["a", "b", "c"]`. Profiles whose rubric is a **section-based** list of named concerns (e.g. spec's `acceptance_criteria`, `prerequisites`, `out_of_scope`, …) SHOULD use those named identifiers. Engine treats `items` values as opaque strings — both conventions are accepted. The convention is a matter of trace-readability: each agent's Issues output should include the ID in the title stem (`issue: (a) AC coverage violated …` or `issue: acceptance_criteria partial …`) so synthesizer aggregation and receipts stay greppable.

## Receipt section semantics

- **Present** — after Step 4 synthesis, engine updates the file matching `receipt.path_template` (with `<slug>` substituted) by setting each field in `fields_to_update` to the appropriate value from the verdict.
- **Absent** — engine skips receipt writing entirely. Use for profiles whose artifact doesn't have a receipt contract (e.g., spec, implementation-plan).

## Error semantics (unified across engine)

All engine errors produce the exact prefix `[multiexpert-review ERROR] <CATEGORY>: <details>` as the first line of conversation output. Consumers (`feature-flow`, `write-spec`, etc.) detect this prefix to distinguish engine errors from ordinary review FAIL verdicts. Categories:

- `UNKNOWN_PROFILE_HINT` — caller passed hint not in inventory
- `FORBIDDEN_PROFILE_FIELD` — profile frontmatter violates negative-list
- `NO_REVIEWERS_AVAILABLE` — all roster agents missing; `allow_single_reviewer: false` and only 1 left; or empty roster with no tech-match
- `AMBIGUOUS_REVIEWER` — short-name resolves to multiple agent files after the family tie-break (see engine SKILL.md Step 2)
- `PROFILE_INVENTORY_MISMATCH` — README inventory vs. `profiles/` file presence disagree
- `ROUTING_NOT_SUPPORTED` — engine reached Step 5 with a source the profile declared `N/A`
