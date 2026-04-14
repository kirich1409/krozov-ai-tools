# Orchestrator Flows

Two thin orchestrators manage the full development cycle. Each routes tasks through
modular skills — no implementation logic, only state transitions.

For stage contracts and artifact formats, see [WORKFLOW.md](WORKFLOW.md).

---

## Feature Flow (`/feature-flow`)

```mermaid
flowchart TD
    start([Task received]) --> setup[Setup: worktree + slug]
    setup --> confirm{Profile confirmation}
    confirm -->|Bug| redirect_bug[→ /bugfix-flow]
    confirm -->|Trivial| impl
    confirm -->|Feature| needs_research{Needs research?}

    needs_research -->|No| impl
    needs_research -->|Yes| research[/research/]
    research --> needs_decompose{Multi-task?}

    needs_decompose -->|No, simple| needs_plan{Complex single task?}
    needs_decompose -->|Yes| decompose[/decompose-feature/]
    decompose --> plan_review

    needs_plan -->|No| impl
    needs_plan -->|Yes| plan_review[/plan-review/]

    plan_review -->|PASS| impl
    plan_review -->|CONDITIONAL| impl
    plan_review -->|FAIL| research

    subgraph loop ["For each task"]
        impl[/implement/] --> acceptance[/acceptance/]
        acceptance -->|VERIFIED| pr_decision
        acceptance -->|"FAILED (obvious)"| impl
        acceptance -->|"FAILED (unclear)"| debug_mid[/debug/]
        debug_mid --> impl
        acceptance -->|PARTIAL| user_decision{User: fix or ship?}
        user_decision -->|Fix| impl
        user_decision -->|Ship| pr_decision
    end

    pr_decision{PR granularity} -->|Per task| create_pr
    pr_decision -->|Bundled| next_task{More tasks?}
    next_task -->|Yes| impl
    next_task -->|No| create_pr

    create_pr[/create-pr/] --> drive[/pr-drive-to-merge/]
    drive -->|Bot checks| drive
    drive -->|"Human review (STOP)"| wait_review([Wait for user])
    wait_review --> drive
    drive -->|Review needs code changes| impl
    drive -->|Approved| merge([Merged ✓])

    style research fill:#e1f5fe
    style decompose fill:#e1f5fe
    style plan_review fill:#e1f5fe
    style impl fill:#e8f5e9
    style acceptance fill:#fff3e0
    style create_pr fill:#f3e5f5
    style drive fill:#f3e5f5
    style wait_review fill:#ffcdd2
    style merge fill:#c8e6c9
    style redirect_bug fill:#ffcdd2
```

### Stop points

| When | What happens |
|------|-------------|
| Profile confirmation | Ask user to confirm feature profile |
| PARTIAL acceptance | User decides: fix now or ship as-is |
| Human PR review | Stop, report status, resume on user command |
| Escalation | Scope explosion, 3× same failure, architectural decision needed |
| Merge confirmation | Ask before merging |

### Backward transition limits

| From → To | Max | After limit |
|-----------|-----|-------------|
| PlanReview → Research | 2 | Escalate |
| Acceptance → Implement | 3 | Escalate |
| Acceptance → Debug | 1 | Escalate |
| PR → Implement | 2 | Escalate |

---

## Bugfix Flow (`/bugfix-flow`)

```mermaid
flowchart TD
    start([Bug reported]) --> setup[Setup: worktree + slug]
    setup --> confirm{Profile confirmation}
    confirm -->|Feature| redirect_feat[→ /feature-flow]
    confirm -->|Trivial fix| impl
    confirm -->|Bug| debug

    debug[/debug/] --> debug_result{Status?}
    debug_result -->|Diagnosed, simple| impl
    debug_result -->|Diagnosed, complex| plan[Plan + /plan-review/]
    debug_result -->|Not reproducible| stop_nr([Stop: need more info])
    debug_result -->|Escalated| stop_esc([Stop: user decision])

    plan -->|PASS| impl
    plan -->|FAIL| debug

    impl[/implement/] --> acceptance[/acceptance/]

    acceptance -->|"VERIFIED (bug gone)"| create_pr
    acceptance -->|"FAILED — same bug"| impl
    acceptance -->|"FAILED — same bug ×2"| debug
    acceptance -->|"FAILED — new bug"| route_new{New bug type?}
    acceptance -->|PARTIAL| user_decision{User: fix or ship?}

    route_new -->|Trivial| impl
    route_new -->|Complex| debug

    user_decision -->|Fix| impl
    user_decision -->|Ship| create_pr

    create_pr[/create-pr/] --> drive[/pr-drive-to-merge/]
    drive -->|Bot checks| drive
    drive -->|"Human review (STOP)"| wait_review([Wait for user])
    wait_review --> drive
    drive -->|Review needs code changes| impl
    drive -->|Approved| merge([Merged ✓])

    report[Report] --> done([Done])
    merge --> report

    style debug fill:#e1f5fe
    style plan fill:#e1f5fe
    style impl fill:#e8f5e9
    style acceptance fill:#fff3e0
    style create_pr fill:#f3e5f5
    style drive fill:#f3e5f5
    style wait_review fill:#ffcdd2
    style stop_nr fill:#ffcdd2
    style stop_esc fill:#ffcdd2
    style merge fill:#c8e6c9
    style done fill:#c8e6c9
    style redirect_feat fill:#ffcdd2
```

### Stop points

| When | What happens |
|------|-------------|
| Profile confirmation | Ask user to confirm bug profile |
| Bug not reproducible | Stop, ask for more info |
| Debug escalation | Architectural issue or needs user decision |
| PARTIAL acceptance | User decides: fix now or ship as-is |
| Human PR review | Stop, report status, resume on user command |
| Merge confirmation | Ask before merging |

### Backward transition limits

| From → To | Max | After limit |
|-----------|-----|-------------|
| Acceptance → Implement | 3 | Escalate |
| Acceptance → Debug | 1 | Escalate |
| PR → Implement | 2 | Escalate |

---

## Stage legend

| Color | Meaning |
|-------|---------|
| 🔵 Blue | Research / diagnosis |
| 🟢 Green | Implementation |
| 🟠 Orange | Verification |
| 🟣 Purple | PR lifecycle |
| 🔴 Red | Stop / wait for user |
| ✅ Green border | Done |
