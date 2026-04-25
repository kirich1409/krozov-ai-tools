# reverse-spec evals

Eval prompts use placeholders of the form `<TARGET_*>` that must be filled in from a
concrete target repository before the eval set runs. Leaving placeholders unresolved
produces meaningless runs.

## Placeholders

| Placeholder | Meaning |
| --- | --- |
| `<TARGET_REPO>` | Absolute path or clone URL of the repo with the feature |
| `<TARGET_SCREEN_NAME>` | Human-readable name of the feature ("Onboarding welcome") |
| `<TARGET_PATH>` | Explicit code path (file / directory / class) |
| `<TARGET_FEATURE_DESCRIPTION>` | Prose description for discovery-input tests |
| `<TARGET_BEHAVIORAL_HINT>` | Behavioral hint that narrows the feature ("the one that shows a map") |
| `<TARGET_TECH_HEAVY_FEATURE>` | Feature that genuinely relies on a load-bearing SDK |
| `<TARGET_LOAD_BEARING_TECH>` | The specific SDK name (e.g., "Google ML Kit", "Stripe SDK") |

## Resolving placeholders

Before iteration 1:

1. Pick the target repo provided by the user.
2. Copy `evals.json` to a per-run scratch file (e.g., `evals.filled.json`) and substitute
   each `<TARGET_*>` with a concrete value.
3. Run the skill-creator's workflow against the filled file. Do not commit the filled
   version — prompts with a specific repo path are ephemeral; the templated version is
   the durable artifact.

## Assertions

Assertions are drafted after iteration 1 outputs are reviewed, not up-front. The reason:
for a skill whose output is a long narrative document, it is hard to write meaningful
assertions until we see where the skill over- or under-delivers on a real target.

After iteration 1, each eval gets 3-6 assertions grounded in observed failure modes.
