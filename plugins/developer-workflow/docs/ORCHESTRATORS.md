# Orchestrator Flows

Two thin orchestrators manage the full development cycle. Each routes tasks through
modular skills — no implementation logic, only state transitions.

**Preconditions (caller's responsibility).** Both orchestrators assume the caller (main
agent, wrapping agent, or user) has already prepared a working branch/worktree and the
correct working directory. The orchestrators never inspect, create, switch, or clean up
branches or worktrees.

For stage contracts and artifact formats, see [WORKFLOW.md](WORKFLOW.md).

---

## Feature Flow (`/feature-flow`)

```mermaid
flowchart TD
    start([Task received]) --> setup[Setup: slug + intake]
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

    needs_plan -->|No| testplan_gate
    needs_plan -->|Yes| plan_review[/plan-review/]

    plan_review -->|PASS| testplan_gate
    plan_review -->|CONDITIONAL| testplan_gate
    plan_review -->|FAIL| research

    testplan_gate{Skip test plan?<br/>5 skip conditions<br/>or --skip-test-plan}
    testplan_gate -->|Skip| impl
    testplan_gate -->|Run| test_plan[/generate-test-plan/]

    test_plan --> test_plan_review[/plan-review<br/>test-plan branch/]
    test_plan_review -->|PASS| impl
    test_plan_review -->|WARN| impl
    test_plan_review -->|FAIL, cycles<3| test_plan
    test_plan_review -->|FAIL, cycles>=3| escalate_tp([Escalate: user decides])

    subgraph loop ["For each task"]
        impl[/implement/] --> acceptance[/acceptance/]
        acceptance -->|VERIFIED| pr_decision
        acceptance -->|"FAILED (obvious)"| impl
        acceptance -->|"FAILED (unclear)"| debug_mid[/debug/]
        debug_mid --> impl
        acceptance -->|"FAILED (new bugs, need Regression TC)"| test_plan
        acceptance -->|PARTIAL| user_decision{User: fix or ship?}
        user_decision -->|Fix| impl
        user_decision -->|Ship| pr_decision
    end

    pr_decision{PR granularity} -->|Per task| create_pr
    pr_decision -->|Bundled| next_task{More tasks?}
    next_task -->|Yes| impl
    next_task -->|No| create_pr

    create_pr[/create-pr/] --> handoff([Hand-off to user])
    handoff --> triage[/triage-feedback/]
    triage -->|FIXABLE items| impl
    triage -->|Nothing actionable| done([PR in user's hands])

    style research fill:#e1f5fe
    style decompose fill:#e1f5fe
    style plan_review fill:#e1f5fe
    style test_plan fill:#e1f5fe
    style test_plan_review fill:#e1f5fe
    style impl fill:#e8f5e9
    style acceptance fill:#fff3e0
    style create_pr fill:#f3e5f5
    style triage fill:#f3e5f5
    style handoff fill:#ffcdd2
    style done fill:#c8e6c9
    style redirect_bug fill:#ffcdd2
    style escalate_tp fill:#ffcdd2
```

### Stop points

| When | What happens |
|------|-------------|
| Profile confirmation | Ask user to confirm feature profile |
| PARTIAL acceptance | User decides: fix now or ship as-is |
| TestPlanReview FAIL after 3 revise cycles | User picks: accept WARN manually, revise spec, or rerun with `--skip-test-plan` |
| After `create-pr` | Orchestrator stops; user runs `triage-feedback` when review feedback arrives and decides whether to resume at `implement` |
| Escalation | Scope explosion, 3× same failure, architectural decision needed |

### Backward transition limits

| From → To | Max | After limit |
|-----------|-----|-------------|
| PlanReview → Research | 2 | Escalate |
| TestPlanReview → TestPlan | 3 | Escalate |
| Acceptance → Implement | 3 | Escalate |
| Acceptance → TestPlan | 3 | Escalate |
| Acceptance → Debug | 1 | Escalate |
| PR → Implement | 2 | Escalate |

---

## Bugfix Flow (`/bugfix-flow`)

```mermaid
flowchart TD
    start([Bug reported]) --> setup[Setup: slug + intake]
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

    create_pr[/create-pr/] --> handoff([Hand-off to user])
    handoff --> triage[/triage-feedback/]
    triage -->|FIXABLE items| impl
    triage -->|Nothing actionable| done([PR in user's hands])

    style debug fill:#e1f5fe
    style plan fill:#e1f5fe
    style impl fill:#e8f5e9
    style acceptance fill:#fff3e0
    style create_pr fill:#f3e5f5
    style triage fill:#f3e5f5
    style handoff fill:#ffcdd2
    style stop_nr fill:#ffcdd2
    style stop_esc fill:#ffcdd2
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
| After `create-pr` | Orchestrator stops; user runs `triage-feedback` when review feedback arrives and decides whether to resume at `implement` |

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
