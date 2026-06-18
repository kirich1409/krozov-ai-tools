# developer-workflow evals

Eval-harness for skills in this plugin. Iterations are gitignored — only this README is tracked.

## Layout

```
evals/
  README.md                       # this file
  .gitignore                      # iteration-*/ ignored
  <skill-or-task>/
    iteration-1/
      with_skill/                 # transcripts produced with the skill loaded
      without_skill/              # transcripts produced without the skill
      input.md                    # the prompt or task fixture
      notes.md                    # observations from this iteration
    iteration-2/
    ...
```

Each subdirectory groups iterations against the same skill or workflow. Iterations are immutable once recorded; later iterations land in new `iteration-N/` directories.

## Active eval targets

- `implement-task/` — historical eval for the (now removed) `implement` orchestrator. Kept as reference.

## How to run

1. Pick a skill and create or pick an `iteration-N/` directory.
2. Save the input fixture as `input.md`.
3. Run two transcripts: one with the skill loaded, one without. Store each as a markdown file under `with_skill/` and `without_skill/` respectively.
4. Compare side-by-side and write your findings into `notes.md`.

These iterations were previously stored under `skills/<name>-workspace/` — that pattern was retired because the eval harness is not itself a skill and the location confused the skill-discovery mechanism.
