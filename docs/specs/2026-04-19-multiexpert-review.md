---
name: multiexpert-review
description: Generalize plan-review into multiexpert-review with declarative artifact profiles
type: spec
slug: multiexpert-review
status: approved
---

# Spec: multiexpert-review — generalize plan-review into universal multi-expert review skill

Date: 2026-04-19
Status: approved (plan-review: PASS after cycle 3; awaiting user sign-off)
Slug: multiexpert-review

---

## Context and Motivation

Skill `plan-review` реализует PoLL (Panel of LLM Evaluators) — параллельный независимый ревью артефакта несколькими экспертами и синтез вердикта. Скилл уже не про planы: его зовут из `write-spec` для ревью спеки, из `generate-test-plan` для ревью test-plan, из `feature-flow` на обоих этапах. Имя `plan-review` misleading, а test-plan ветка внутри SKILL.md (строки 375-456) — это де-факто «профиль» артефакта, зашитый в код.

Research (`./swarm-report/generalize-review-skill-research.md`) показал: PoLL-ядро универсально, специфика артефакта должна жить как декларативный профиль. Решения залочены пользователем: rename `plan-review` → `multiexpert-review` без backwards compat, профили `implementation-plan.md` / `test-plan.md` / `spec.md` в Phase 1-2, остальные — YAGNI.

## Acceptance Criteria

Все AC **falsifiable** — либо grep/diff-check, либо structural-equivalence над baseline. Пункты про стохастичность PoLL выражены через структурные инварианты, а не через content-level identity.

### Rename + callsites (AC-R) — **authoritative audit 18 git-tracked union files**

Authoritative grep (`git ls-files | xargs grep -l "plan-review\|plan review"`): **18 файлов**. Из них:
- **15 файлов** содержат skill-id `plan-review` (51 line-ref)
- **10 файлов** содержат prose «plan review» (10 line-refs)
- Пересечение: 7 файлов содержат оба варианта

- [ ] **AC-R1** Директория `plugins/developer-workflow/skills/plan-review/` переименована в `plugins/developer-workflow/skills/multiexpert-review/` (проверка: `git log --follow --name-only` показывает rename; старый путь не существует)
- [ ] **AC-R2** `multiexpert-review/SKILL.md` frontmatter: `name: multiexpert-review` и description дословно: «Review documentation artifacts (plan, spec, test-plan) with a panel of independent expert agents before commit. Use when asked to review a plan, spec, test-plan, or similar documentation artifact.»
- [ ] **AC-R3 (invoke callsites — exactly 2 files)** Строка `developer-workflow:plan-review` отсутствует в **feature-flow/SKILL.md** и **bugfix-flow/SKILL.md**. Replaced с `developer-workflow:multiexpert-review`. Grep: `git ls-files | xargs grep -l "developer-workflow:plan-review"` возвращает 0 файлов. (Prose references в остальных файлах покрываются AC-R4; invoke — только эти два.)
- [ ] **AC-R4 (skill-id references — 15 files, 51 line-refs total)** Skill-id `plan-review` (с дефисом) не встречается ни в одном git-tracked файле **кроме whitelisted в AC-R6**. Список 15 файлов с их pre-refactor line-count'ом (для трассировки scope миграции):
  - `README.md` (1), `docs/PLUGINS-GUIDE.md` (4), `plugins/developer-workflow/CLAUDE.md` (1), `plugins/developer-workflow/README.md` (2), `docs/ORCHESTRATION.md` (3), `docs/ORCHESTRATORS.md` (3), `docs/WORKFLOW.md` (5), `acceptance/SKILL.md` (3), `bugfix-flow/SKILL.md` (1), `decompose-feature/SKILL.md` (2), `feature-flow/SKILL.md` (7), `generate-test-plan/SKILL.md` (7), `plan-review/SKILL.md` (4, файл будет renamed), `research/SKILL.md` (3), `write-spec/SKILL.md` (5)
  - Gate subsumed by AC-R6 — strict «0 files» проверка неисполнима, поскольку этот spec + engine SKILL.md + WORKFLOW.md намеренно содержат whitelisted references (legacy state filename, stage label `[test-plan-review]`, historical context). Whitelist-based check — в AC-R6.
- [ ] **AC-R5 (prose «plan review» — 10 files)** Prose «plan review» (с пробелом) не встречается ни в одном git-tracked файле **кроме whitelisted в AC-R6**. Список 10 pre-refactor файлов: `CLAUDE.md` (root), `README.md` (root), `.claude-plugin/marketplace.json`, `plugins/developer-workflow/.claude-plugin/plugin.json`, `plugins/developer-workflow/docs/ORCHESTRATION.md`, `plugins/developer-workflow/docs/WORKFLOW.md`, `plugins/developer-workflow/skills/bugfix-flow/SKILL.md`, `plugins/developer-workflow/skills/feature-flow/SKILL.md`, `plugins/developer-workflow/skills/plan-review/SKILL.md`, `plugins/developer-workflow/skills/research/SKILL.md`
  - Gate subsumed by AC-R6 — union-check включает оба варианта написания.
- [ ] **AC-R6 (audit final gate — union)** Финальный анти-регрессионный gate: `git ls-files | xargs grep -l "plan-review\|plan review"` возвращает только whitelisted файлы:
  - `docs/specs/2026-04-19-multiexpert-review.md` — эта спека (содержит historical context и AC-R6-правило со ссылками на legacy skill-id)
  - `plugins/developer-workflow/skills/multiexpert-review/SKILL.md` — load-bearing reference на legacy state filename `./swarm-report/plan-review-state.md` в секции «Persistence / Legacy read» (требуется для backward-compat graceful read старого state file в пользовательских worktree-ах)
  - `plugins/developer-workflow/docs/WORKFLOW.md` — pipeline stage label `[test-plan-review]` в ASCII-диаграмме содержит substring `plan-review`. Это имя стадии оркестратора (State Machine state `TestPlanReview`), а не skill-id; семантически корректно и согласовано с mermaid node-id `test_plan_review` в `ORCHESTRATORS.md`.
  - Все остальные файлы — 0 матчей

### Engine + profiles (AC-E)

- [ ] **AC-E1** Файл `multiexpert-review/profiles/README.md` существует и содержит:
  - Frontmatter schema (inventory of allowed fields)
  - **Explicit negative-list** полей, которые профиль НЕ может содержать: `output_schema`, `aggregation_strategy`, `state_transitions`, `revise_loop_cap`, `review_prompt_template`
  - Зарегистрированный **inventory** имён профилей: `[implementation-plan, test-plan, spec]`
- [ ] **AC-E2** Файл `multiexpert-review/profiles/implementation-plan.md` создан; при прогоне на одном из Phase-0 baseline плана (см. Phase 0) engine обходит Steps 2-5 идентично pre-refactor прогону: тот же **набор агентов**, тот же **verdict label** (PASS|CONDITIONAL|FAIL), те же **количество cycles**. (Content-level identity issues не проверяется — PoLL стохастичен.)
- [ ] **AC-E3** Файл `multiexpert-review/profiles/test-plan.md` создан; содержит checklist (a)–(e), severity mapping (a/b/c→critical, d/e→major), verdict alphabet PASS/WARN/FAIL, receipt integration. При прогоне на Phase-0 baseline test-plan артефакте: тот же verdict label, тот же `review_verdict/review_warnings/review_blockers` сет полей в receipt (check via YAML parse, not string-diff)
- [ ] **AC-E4** Файл `multiexpert-review/profiles/spec.md` создан с рубрикой (см. Technical Approach §6)
- [ ] **AC-E5 (engine fail-fast)** Engine при загрузке профиля с запрещённым полем из negative-list отказывает с exact-match error text `[multiexpert-review ERROR] FORBIDDEN_PROFILE_FIELD: profile <name> declares forbidden field <field>`.
  - **Runner:** верификация через code review engine SKILL.md §Error semantics + profiles/README.md §Negative-list contract (fixture-dir не создаётся — engine/README являются authoritative источником контракта). AC проходит, если обе секции декларируют идентичный prefix `[multiexpert-review ERROR] FORBIDDEN_PROFILE_FIELD:` и tail-формат `profile <name> declares forbidden field <field>`.

### Detector (AC-D)

- [ ] **AC-D1 (precedence)** Step 1 детектор реализует цепочку: (1) explicit caller hint → (2) frontmatter `type:` → (3) path-glob → (4) structural signature → (5) fallback = **prompt user**. Verified на 5 fixture-артефактах, каждый активирует свой уровень precedence
- [ ] **AC-D2 (hint typo fail-loud)** Если caller hint не из inventory (`implementation-plan | test-plan | spec`) — engine падает с `Unknown profile hint <value>`. Silent fallback к detection **запрещён**. Verified на fixture с `profile: sepc`
- [ ] **AC-D3 (no silent implementation-plan fallback)** Если артефакт без frontmatter, не матчит path-glob, не матчит signature — engine prompts user (AskUserQuestion с выбором из inventory), **не** запускает review на default профиле. Verified на fixture `test-fixtures/unknown-artifact.md` (пустой markdown с одним заголовком)
- [ ] **AC-D4 (cycle-locking)** Profile name фиксируется в state file при cycle 1 и **read-only** для cycles ≥2. Контракт engine: в cycle 2 и 3 engine читает профиль только из state file. Если args на ре-инвокации содержит hint:
  - hint **совпадает** с locked profile → no-op (нормальный revise-loop, callsite послал тот же hint)
  - hint **отличается** от locked → warning `Cycle <N> ignoring profile hint '<value>' — locked to '<locked>' since cycle 1` в Verdict History, engine продолжает на locked профиле (не fail-loud, audit trail)
  - **Fixture:** тестовый revise-loop с принудительной сменой hint во 2-м cycle; assertion — warning присутствует в state file Verdict History cycle 2

### Source routing + state (AC-S)

- [ ] **AC-S1 (profile_hint contract)** `write-spec/SKILL.md` Phase 4.3 при вызове `multiexpert-review` prepend-ит к args строку `profile: spec\n---\n`, а skill Step 1 parser распознаёт этот префикс. Format зафиксирован в Decisions (см. ниже)
- [ ] **AC-S2** State file: `./swarm-report/multiexpert-review-<slug>-state.md`. Если `<slug>` неизвестен — timestamp slug `multiexpert-review-<YYYYMMDD-HHMM>-state.md`. Engine graceful-reads legacy `plan-review-state.md` если присутствует; always writes новое имя
- [ ] **AC-S3 (receipt contract preserved)** После прогона test-plan профиля YAML-parse receipt содержит все три поля: `review_verdict`, `review_warnings`, `review_blockers`. Acceptance skill (consumer) прочитывает receipt без parse-error. Verified на `docs/testplans/<any-existing>-test-plan.md` fixture
- [ ] **AC-S4 (single-reviewer visibility)** Если профиль имеет `allow_single_reviewer: true` и эффективно призван один агент — final verdict содержит маркер `## Review Mode: single-perspective` в выводе. Marker живёт **только** в verdict-text: receipt-contract profile-declared (см. `profiles/README.md` §Receipt), и ни один из shipped профилей не декларирует `review_mode` в `fields_to_update` — receipt-write для single-reviewer **не производится**.
- [ ] **AC-S5 (missing agents policy)** Если в `reviewer_roster.primary` агент не установлен — engine пропускает его, continuing если остался ≥1. Если 0 — fail loud с `No reviewers available for profile <name>`

### Write-spec drift closure (AC-W)

- [ ] **AC-W1 (structural dogfooding)** Сама эта спека прогнанная через Phase-2 spec-профиль (post-refactor) отличается от прогона через implementation-plan профиль (baseline) по **структурным признакам**, а не контенту:
  - **reviewer_roster совпадает с декларируемым в spec-профиле** (`[business-analyst, architecture-expert]`) — implementation-plan-baseline использует tech-match selection который может выбрать других агентов
  - **severity-mapping вердикта содержит severity-классы из spec-профиля** — spec-профиль помечает «AC не observable/verifiable» как critical; implementation-plan такой категории не имеет
  - Оба признака measurable через parsing `state-file` и `verdict-output`, не через stochastic content diff
- [ ] **AC-W2 (baseline capture, advisory)** Phase 0 baseline для spec-drift записан: прогон этой спеки через текущий `plan-review` сохранён в `swarm-report/baseline-drift-spec-<timestamp>.md` с полями: chosen agents, verdict label, severity counts (critical/major/minor). Post-refactor spec-профиль сравнивается по этим полям. **Advisory, не blocking:** если после refactor reviewer_roster и severity-mapping совпадают со spec-профилем — refactor закрыл drift. Если не совпадают — требуется user-level review. Сценарий «идентичный output» возможен только если spec-профиль случайно повторил implementation-plan defaults, что проверяется визуально по содержимому профиля — не требует content-level identity over stochastic runs
- [ ] **AC-E6 (inventory mismatch fail-loud)** Engine при startup с `profiles/README.md` объявляющим, скажем, `[implementation-plan, test-plan, spec, ghost]` но отсутствующим `profiles/ghost.md` — или наоборот (`profiles/foo.md` существует но нет в README) — отказывает с `[multiexpert-review ERROR] PROFILE_INVENTORY_MISMATCH: <name> <direction>`. Verified на двух fixture-configurations: (a) README объявляет лишний профиль; (b) файл профиля существует но не в README

### Engine error semantics (AC-CT)

- [ ] **AC-CT1** Skill-frontmatter `plugins/developer-workflow/skills/multiexpert-review/SKILL.md` **не содержит** `disable-model-invocation: true` — skill должен быть auto-discoverable. Grep-check: `grep "disable-model-invocation" plugins/developer-workflow/skills/multiexpert-review/SKILL.md` = 0 матчей
- [ ] **AC-CT2 (fail-loud semantics)** Все «fail loud» в спеке (AC-E5, AC-D2, AC-S5, profile inventory mismatch, N/A routing, ambiguous reviewer collision) имеют единую семантику: engine **отказывается запускать review**, первым выводом в conversation является error text с exact prefix `[multiexpert-review ERROR] <category>: <details>`. Consumer (feature-flow/write-spec) различает ENGINE_ERROR от обычного verdict FAIL по этому префиксу. Categories: `UNKNOWN_PROFILE_HINT`, `FORBIDDEN_PROFILE_FIELD`, `NO_REVIEWERS_AVAILABLE`, `AMBIGUOUS_REVIEWER`, `PROFILE_INVENTORY_MISMATCH`, `ROUTING_NOT_SUPPORTED`.

### Housekeeping (AC-H, non-git)

- [ ] **AC-H1** `.claude/agent-memory/developer-workflow-experts-architecture-expert/project_existing_contracts_plan_review.md` → rename к `project_existing_contracts_multiexpert_review.md`, content updated. `project_plan_review_generalization.md` → rename к `project_multiexpert_review_generalization.md`. `MEMORY.md` index обновлён.
  - **Grep-assertion:** `grep -rE "plan-review|plan review" .claude/agent-memory/developer-workflow-experts-architecture-expert/` возвращает 0 матчей
- [ ] **AC-H2** `.claude/agent-memory/developer-workflow-experts-business-analyst/project_poll_generalization.md` content updated. `MEMORY.md` index обновлён.
  - **Grep-assertion:** `grep -rE "plan-review|plan review" .claude/agent-memory/developer-workflow-experts-business-analyst/` возвращает 0 матчей

**Явно: AC-H1/H2 — filesystem housekeeping, не входят в git commits. Проверяются grep-ом над локальным filesystem, не git-diff.**

### PR structure (AC-PR)

- [ ] **AC-PR1 (single PR, three commits)** Весь refactor — один PR в `main`. Внутри PR — **три коммита в порядке**:
  1. `Rename plan-review → multiexpert-review (AC-R1..R6)` — механический rename + все prose/invoke refs; structural equivalence pre/post (AC-E2 definition)
  2. `Extract engine and profiles (AC-E1..E5, AC-D1..D4, AC-S1..S5)` — engine extraction, profile files, detector refactor; baseline re-run и AC-E2/E3 structural-equivalence check
  3. `Add spec profile and close write-spec drift (AC-E4, AC-W1..W2)` — spec-профиль + write-spec Phase 4.3 hint + dogfooding check
- [ ] **AC-PR2 (no squash — manual enforcement)** PR merged с явным выбором «Create a merge commit» или «Rebase and merge» в GitHub UI, **не «Squash and merge»**. Enforcement — ручной; в PR-description явно указать: «DO NOT SQUASH — three commits preserve bisectability of rename / engine extract / spec profile». Если репо имеет branch protection требующий squash — перенастроить для этого PR либо явно указать в Decisions что squash принят с compromise of bisectability

## Prerequisites

| Prerequisite | Status | Owner | Notes |
|--------------|--------|-------|-------|
| PR #93 (acceptance refactor) merged | ✅ Done (commit 723c1e1) | Human | Merged 2026-04; не блокирует. |
| PR #88 (test-plan integration, v0.10.0) merged | ✅ Done | Human | Merged в v0.10.0; не блокирует. |
| **v0.11.0 released (stabilization gate)** | ⬜ Todo (blocking Commit 2) | Human | Exit criterion: tag `v0.11.0` опубликован на `origin`, GitHub release создан, CI workflow `release.yml` завершён зелёным, per-plugin tags `developer-workflow--v0.11.0` и `developer-workflow-experts--v0.11.0` существуют на `origin`. Spec можно утверждать до v0.11.0; старт Commit 2 (engine extraction) ждёт релиз. Commit 1 (чистый rename) может быть смёрджен в v0.11.0 или позже — rename ≠ contract change. |
| Phase-0 baseline fixtures подготовлены (3 runs per fixture) | ⬜ Todo | Agent | См. Technical Approach §9; сохраняются в `swarm-report/baseline-verdicts-<timestamp>.md` и `baseline-drift-spec-<timestamp>.md`. **Три прогона на fixture** (не один) — structural equivalence check принимает 3/3 match по verdict label и participating agents, 0 прогонов допустимо отклонение. |
| Callsite audit перепрогнан (authoritative) | ✅ Done | Agent | **15 файлов** со skill-id `plan-review` (51 line-refs); **10 файлов** с prose «plan review» (10 line-refs); **18 union git-tracked файлов**. Команда: `git ls-files \| xargs grep -l "plan-review\|plan review"` |
| spec sign-off | ⬜ Todo (этот документ) | Human | Утверждение до старта Phase 1 |

## Affected Modules and Files

**Summary (authoritative grep):** 18 уникальных git-tracked файлов. Of those: 15 со skill-id `plan-review` (51 line-refs), 10 с prose «plan review» (10 line-refs), пересечение 7. Плюс 4 новых файла в Commit 2-3.

### Existing files — modified (18 git-tracked)

| File | skill-id refs | prose refs | Change type | Commit |
|------|:-:|:-:|-------------|:-:|
| `plugins/developer-workflow/skills/plan-review/` | — | — | **Rename** → `multiexpert-review/` | 1 |
| `plugins/developer-workflow/skills/plan-review/SKILL.md` | 4 | 1 | Rename + replace both forms; then engine extraction | 1 (rename) + 2 (engine) |
| `plugins/developer-workflow/skills/feature-flow/SKILL.md` | 7 | 1 | Invoke + prose; Phase 1.4/1.6 references | 1 |
| `plugins/developer-workflow/skills/bugfix-flow/SKILL.md` | 1 | 1 | Invoke + prose | 1 |
| `plugins/developer-workflow/skills/write-spec/SKILL.md` | 5 | 0 | Prose refs + Phase 4.3 prepend `profile: spec\n---\n` | 1 (prose) + 3 (hint) |
| `plugins/developer-workflow/skills/generate-test-plan/SKILL.md` | 7 | 0 | Prose refs; no semantic change — receipt format preserved | 1 |
| `plugins/developer-workflow/skills/acceptance/SKILL.md` | 3 | 0 | Prose refs; reads `review_verdict` field — field name unchanged | 1 |
| `plugins/developer-workflow/skills/research/SKILL.md` | 3 | 1 | Prose refs | 1 |
| `plugins/developer-workflow/skills/decompose-feature/SKILL.md` | 2 | 0 | Prose refs | 1 |
| `plugins/developer-workflow/docs/ORCHESTRATION.md` | 3 | 1 | Tables + prose | 1 |
| `plugins/developer-workflow/docs/ORCHESTRATORS.md` | 3 | 0 | Mermaid diagrams | 1 |
| `plugins/developer-workflow/docs/WORKFLOW.md` | 5 | 1 | Skill list + tables | 1 |
| `plugins/developer-workflow/README.md` | 2 | 0 | Skill description | 1 |
| `plugins/developer-workflow/CLAUDE.md` | 1 | 0 | Skill roster | 1 |
| `README.md` (root) | 1 | 1 | Skill list | 1 |
| `CLAUDE.md` (root) | 0 | 1 | Plugin description prose | 1 |
| `docs/PLUGINS-GUIDE.md` (root) | 4 | 0 | Mermaid + tables | 1 |
| `.claude-plugin/marketplace.json` | 0 | 1 | Plugin description | 1 |
| `plugins/developer-workflow/.claude-plugin/plugin.json` | 0 | 1 | Plugin description | 1 |

Totals: 15 files with skill-id × 51 line-refs + 10 files with prose × 10 line-refs — совпадает с authoritative grep.

### New files (created in Commit 2-3)

| File | Change type | Commit |
|------|-------------|:-:|
| `multiexpert-review/profiles/README.md` | **New** — profile schema + negative-list + canonical PROFILE_INVENTORY | 2 |
| `multiexpert-review/profiles/implementation-plan.md` | **New** — default profile port | 2 |
| `multiexpert-review/profiles/test-plan.md` | **New** — port of current SKILL.md:375-456 | 2 |
| `multiexpert-review/profiles/spec.md` | **New** — new rubric for spec artifacts | 3 |

### Housekeeping (filesystem-only, not in git commits)

| Path | Change type |
|------|-------------|
| `.claude/agent-memory/developer-workflow-experts-architecture-expert/project_existing_contracts_plan_review.md` | Rename → `*_multiexpert_review.md` + content update |
| `.claude/agent-memory/developer-workflow-experts-architecture-expert/project_plan_review_generalization.md` | Rename → `project_multiexpert_review_generalization.md` + content update |
| `.claude/agent-memory/developer-workflow-experts-architecture-expert/MEMORY.md` | Content update (index entries) |
| `.claude/agent-memory/developer-workflow-experts-business-analyst/project_poll_generalization.md` | Content update only (filename doesn't contain `plan-review`) |
| `.claude/agent-memory/developer-workflow-experts-business-analyst/MEMORY.md` | Content update |

**OUT of scope** (не трогаем):
- `swarm-report/generalize-review-skill-research.md` и соседние state-файлы — гитигнорные historical records
- Все плагины вне `developer-workflow/`: `maven-mcp`, `sensitive-guard`, `developer-workflow-experts`, `-kotlin`, `-swift` — проверено: `plan-review` не встречается

## Technical Approach

### 1. Commit 1 — чистый rename

- `git mv plugins/developer-workflow/skills/plan-review plugins/developer-workflow/skills/multiexpert-review`
- SKILL.md frontmatter обновлён (name + description)
- Во всех 15 файлах с skill-id `plan-review` → `multiexpert-review`
- В marketplace.json + plugin.json: «plan review» → «multiexpert review» (description prose)
- Агент-memory файлы обновлены (filesystem, не в коммите)
- **Gate:** Phase-0 baseline prompt прогнан через new skill имя — structural-equivalence check проходит (AC-E2 criteria без engine extraction; ожидание — тот же verdict label, тот же список участвующих агентов, то же число cycles)

### 2. Commit 2 — engine + profiles (implementation-plan, test-plan)

`multiexpert-review/SKILL.md` превращается в engine. Структура:

```
# multiexpert-review
## Step 1 — Read artifact and detect profile
## Step 2 — Discover and select agents (per profile.reviewer_roster)
## Step 3 — Parallel independent review (engine prompt-template fixed)
## Step 4 — Synthesize verdict (engine aggregation rules)
## Step 5 — Post-review action (per profile.source_routing + profile.receipt_integration)
```

**Детектор в Step 1 (explicit decision tree):**

```
def detect_profile(args, artifact):
    # 1. Explicit caller hint
    hint = parse_hint_prefix(args)         # None if no "profile: <name>" prefix
    if hint:
        if hint not in PROFILE_INVENTORY:
            fail_loud(f"Unknown profile hint '{hint}'. Known: {PROFILE_INVENTORY}")
        return hint

    # 2. Frontmatter type
    fm_type = parse_frontmatter_type(artifact)
    if fm_type in FRONTMATTER_TYPE_MAP:
        return FRONTMATTER_TYPE_MAP[fm_type]

    # 3. Path glob
    for profile, globs in PATH_GLOBS.items():
        if any(match_glob(artifact.path, g) for g in globs):
            return profile

    # 4. Structural signature
    for profile, sigs in STRUCTURAL_SIGS.items():
        if all(re.search(s, artifact.content) for s in sigs):
            return profile

    # 5. Fallback — ask user, never silent
    return ask_user_profile_choice(PROFILE_INVENTORY)
```

**Cycle-locking:** profile фиксируется в state file при cycle 1 и read-only для cycles ≥2. Engine игнорирует любые hint в args на cycles ≥2; если hint отличается от locked profile, engine выводит warning `Cycle <N> ignoring profile hint '<value>' — locked to '<locked>' since cycle 1` в state file Verdict History и продолжает работу на locked profile (не fail-loud, audit trail для последующего review).

### 3. Profile contract (multiexpert-review/profiles/README.md)

```yaml
---
name: {implementation-plan | test-plan | spec}
description: {one-line}
detect:
  frontmatter_type: [...]                 # значения, которые триггерят профиль
  path_globs: [...]                       # e.g., docs/specs/**
  structural_signatures: [...]            # regex, ALL must match
reviewer_roster:
  primary: [agent-name, ...]              # обязательные (skip если не установлен)
  optional_if:
    - when: "regex over artifact content"
      agent: agent-name
allow_single_reviewer: true | false       # default: false
verdicts: [PASS, CONDITIONAL, FAIL]       # или [PASS, WARN, FAIL]
severity_mapping:
  - items: ["a", "b", "c"]
    severity: critical
  - items: ["d", "e"]
    severity: major
source_routing:
  plan_mode: EnterPlanMode
  file: edit-in-place
  conversation: inline-revise
receipt:                                  # ОПЦИОНАЛЬНАЯ секция, отсутствие = no receipt
  path_template: swarm-report/<slug>-<artifact-type>.md
  fields_to_update: [review_verdict, review_warnings, review_blockers]
---

## Rubric
(артефакт-специфичные критерии)

## Prompt augmentation
(опционально: доп. текст для Step 3)
```

**Engine invariants (negative-list) — поля ЗАПРЕЩЕНО объявлять в профиле:**
- `output_schema` — структура review output агента фиксирована engine-ом
- `aggregation_strategy` — aggregation rules (convergence/contradictions/confidence-weighting) — engine
- `state_transitions` — state machine transitions — engine
- `revise_loop_cap` — max 3 cycles — engine constant
- `review_prompt_template` — Step 3 prompt template — engine

При загрузке профиля engine валидирует frontmatter keys против whitelist (из schema) и negative-list. Встретил запрещённое поле → fail loud (AC-E5).

**Profile inventory** (canonical source of truth, в profiles/README.md):
```
PROFILE_INVENTORY = [implementation-plan, test-plan, spec]
```

Формат unquoted обязателен — parser контракт в `profiles/README.md` §Canonical inventory явно запрещает кавычки и multi-line arrays; quoted элементы не матчат `^PROFILE_INVENTORY\s*=\s*\[([^\]]+)\]\s*$` и разбиваются на лишние токены при split по `,`.
Правило: profiles/README.md — **canonical** source; engine **читает** список на startup парсингом этой константы в markdown. Engine не хардкодит PROFILE_INVENTORY в своём теле. Добавление профиля = (1) создать `profiles/<name>.md`, (2) обновить список в README.md одним и тем же commit-ом — иначе engine не узнает про новый профиль и/или fail-loud'нется на hint. Disconnect между README.md и presence файла в `profiles/` (файл есть, в README нет — или наоборот) engine детектирует и выводит `Profile inventory mismatch: <name> in README but no file` или `<name> file exists but not in inventory`.

**Profile snapshot policy:** engine НЕ сохраняет snapshot профиля в state file. Revise-loop читает профиль live на каждом cycle. Изменение профиля в процессе revise-loop — неподдерживаемый сценарий, engine этого не детектирует. (Если профиль меняется между циклами — это human mistake, не runtime guarantee.)

### 4. Profile: implementation-plan (Commit 2)

Дефолт. Порт Steps 2-5 (non-test-plan) текущего SKILL.md:
- `verdicts: [PASS, CONDITIONAL, FAIL]`
- `reviewer_roster.primary: []` — пустой; selection по tech-match из content артефакта (сохраняет текущее поведение; `optional_if` тоже не используется)
- `allow_single_reviewer: true` — явно; implementation-plan может завершиться с одним агентом если только один relevant по tech-match (сохраняет pre-refactor поведение)
- `source_routing`: как сейчас
- Нет секции `receipt` — профиль не пишет receipt
- Rubric: generic (агенты применяют экспертизу свободно)
- `detect.frontmatter_type: [implementation-plan, plan]`
- `detect.path_globs: []` — нет; catch by frontmatter или fallback
- `detect.structural_signatures: []` — нет; это default

### 5. Profile: test-plan (Commit 2)

Порт строк 375-456:
- `verdicts: [PASS, WARN, FAIL]`
- `reviewer_roster.primary: [business-analyst]`
- `reviewer_roster.optional_if`:
  - `{when: "auth|token|encryption|PII", agent: security-expert}`
  - `{when: "SLA|latency|throughput", agent: performance-expert}`
  - `{when: "a11y|accessibility", agent: ux-expert}`
- `severity_mapping: [{items:[a,b,c], severity:critical}, {items:[d,e], severity:major}]`
- `detect.frontmatter_type: [test-plan, test-plan-receipt]`
- `detect.path_globs: [docs/testplans/**, swarm-report/*-test-plan.md]`
- `detect.structural_signatures: ["^## Test Cases", "^#{1,6}\\s+TC-[\\w-]+", "P[0-3]"]` (все три)
- `receipt.path_template: swarm-report/<slug>-test-plan.md`
- `receipt.fields_to_update: [review_verdict, review_warnings, review_blockers]`
- `allow_single_reviewer: false` — test-plan требует panel (минимум business-analyst; если optional_if-триггеры сработали — больше)
- Rubric: checklist (a)-(e) дословный перенос

### 6. Profile: spec (Commit 3)

Закрывает drift. Рубрика:
- **AC observable/verifiable**: каждый пункт acceptance criteria должен быть grep/diff-check либо structural-equivalence, не «feels right»
- **Out of scope explicit**: существует раздел Out of Scope; не «sweeping under the rug»
- **Open questions разделены blocking/non-blocking**: каждый OQ тэгирован
- **Affected modules/files complete**: список с change type + rationale
- **Decisions с rationale**: каждое Decision в таблице с колонкой «Rationale»
- **Prerequisites реалистичны**: разделено Done/Todo с owner

Severity mapping: пропуск AC или acceptance criteria — `critical`; отсутствие out-of-scope или prerequisites — `major`; прочее — `minor`.

- `verdicts: [PASS, CONDITIONAL, FAIL]`
- `reviewer_roster.primary: [business-analyst, architecture-expert]`
- `detect.frontmatter_type: [spec]`
- `detect.path_globs: [docs/specs/**]`
- Нет секции `receipt` — spec profile не пишет receipt
- `allow_single_reviewer: false` — spec-review требует оба эксперта

### 7. Caller integration — profile_hint format

Спецификация args-prefix (зафиксирован как Decision):

```
profile: <name>
---
<rest of args>
```

- `profile:` строка должна быть **первой** строкой args
- `---` разделитель на отдельной строке
- `<name>` валидируется против PROFILE_INVENTORY; unknown → fail loud (AC-D2)
- Без hint args идёт целиком в detection-цепочку (frontmatter/path/signature/ask)

`write-spec/SKILL.md` Phase 4.3 обновление: когда вызывает multiexpert-review, prepends `profile: spec\n---\n` к args. Engine логирует применённый hint в state file:

```markdown
## Detected Profile (cycle 1)
source: caller_hint
value: spec
hint_raw: "profile: spec"
```

Это делает hint-application видимым в audit trail.

### 8. State file

- **New path:** `./swarm-report/multiexpert-review-<slug>-state.md`
- **Slug source:** (1) явно из args (`slug:` поле в frontmatter hint), (2) из artifact frontmatter `slug:`, (3) из filename без extension, (4) fallback timestamp `multiexpert-review-<YYYYMMDD-HHMM>-state.md`
- **Legacy read:** если `multiexpert-review-<slug>-state.md` не существует, попробовать `plan-review-state.md`; если нашли — скопировать content в new path, продолжить на new path (не удалять legacy)
- **Always write** на new path

### 9. Phase 0 — frozen baseline

Phase 0 setup:

1. **Baseline plan fixtures** — выбрать **3 реальных plan-артефакта** из `swarm-report/` worktree-а (или создать synthetic если нет) + **1 real test-plan** из `docs/testplans/` или `swarm-report/`
2. **Frozen parameters:** все baseline prompts фиксированы ДО первого прогона:
   - Same reviewer agents (enumerated in state file)
   - Same artifact text (file path + sha256)
   - Same `profile_hint` (если применим)
3. **Baseline capture:** pre-refactor прогон current `plan-review` на каждом fixture, сохранить в `swarm-report/baseline-verdicts-<timestamp>.md`:
   - Final verdict label (PASS|CONDITIONAL|FAIL|WARN)
   - List of agents that participated
   - Number of cycles run (1-3)
   - For test-plan: receipt fields as parsed YAML (structural, not string)
4. **Drift-spec baseline:** отдельно, прогон **этой самой спеки** через current `plan-review` (implementation-plan default), сохранить verdict в `baseline-drift-spec-<timestamp>.md`. Используется для AC-W2 comparison.

**Structural equivalence check (для AC-E2/E3):** baseline captured **3 runs per fixture** pre-refactor, post-refactor также прогоняется **3 runs per fixture**. Критерии:
- **Modal final verdict label** (самый частый из 3 прогонов, PASS/CONDITIONAL/FAIL/WARN) совпадает pre vs post — обязательно
- **Set of agents** participated — **совпадает во всех 3 прогонах** pre и **совпадает во всех 3 прогонах** post; post-set = pre-set (обязательно)
- **Cycle count**: modal (самый частый) совпадает pre vs post; ≥2 из 3 прогонов должны дать тот же cycle count для каждой стороны — обязательно (без tolerance ±1, требуется strict modal match)
- **Для test-plan receipt**: все три поля (`review_verdict`, `review_warnings`, `review_blockers`) **присутствуют** с корректным YAML shape во всех 3 прогонах — обязательно

Content-level identity (списки issues, их формулировки) **не сравнивается** — PoLL стохастичен. Structural equivalence с 3-run modal аппроксимирует стабильность поведения без false positives от single-run стохастики.

## Technical Constraints

- Все правки — в одном PR на ветке `chore/generalize-review-research`, три коммита в порядке Commit 1 → 2 → 3. **Без squash при merge** (bisectability).
- Нет новых сторонних зависимостей.
- **Engine invariants — неизменны профилем** (AC-E1 negative-list + AC-E5 fail-fast).
- Engine prompt-template в Step 3 — hardcoded в SKILL.md, неизменяем.
- State machine + aggregation rules — engine-константы.
- «Never share one agent's review with another» — инвариант, не нарушается.
- Receipt integration для test-plan профиля побитово сохраняет формат `generate-test-plan/SKILL.md:62-98`. YAML-parse-equivalence, не string-diff (AC-S3).
- `disable-model-invocation` в frontmatter SKILL.md **не устанавливается**.
- SKILL.md размер: engine ≤ 250 строк, profiles/README.md ≤ 100, каждый профиль ≤ 150.
- Commit 2 **ждёт v0.11.0 релиз** (Prerequisites).

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Skill name | `multiexpert-review` | слитно, отражает суть (panel of experts) |
| Backwards compat | нет (no alias, no deprecation) | atomic rename — callsites в том же PR |
| Description формулировка | см. AC-R2 | узкая, явно перечисляет типы |
| Profile directory | `multiexpert-review/profiles/` | self-contained skill |
| Phase 1 profiles | implementation-plan + test-plan (port existing) | non-breaking refactor |
| Phase 2 profile | spec (закрывает write-spec drift) | реальный существующий баг |
| Phase 3 profiles | YAGNI — только по запросу | adr/migration/research-report без consumer |
| State file name | `./swarm-report/multiexpert-review-<slug>-state.md` | slug source: hint/frontmatter/filename/timestamp; legacy read с `plan-review-state.md` |
| Detector fallback policy | ask user, **никогда silent** | silent fallback был источником write-spec drift |
| Profile override scope | verdicts, severity_mapping, roster, detect, receipt, source_routing, prompt augmentation | не output structure, не aggregation, не state machine, не revise cap, не review prompt template |
| Engine invariants enforcement | Negative-list в profiles/README.md + fail-fast при загрузке | technical enforcement, не социальный контракт |
| `allow_single_reviewer` visibility | verdict содержит маркер `## Review Mode: single-perspective` в тексте; **receipt не изменяется** (no profile declares `review_mode` in `fields_to_update`) | audit trail в verdict-text, без расширения receipt schema |
| profile_hint format | Первая строка args: `profile: <name>\n---\n` + inventory validation | простой текстовый контракт; fail-loud на unknown name (AC-D2) |
| Cycle-locking | Profile name в state file cycle 1; cycles ≥2 — только state file; если args hint совпадает с locked — no-op; если hint ≠ locked — warning в state file Verdict History, engine continues on locked profile (не fail-loud) | закрывает multi-cycle profile locking risk без false-positive warnings на нормальных повторных вызовах |
| Missing agent policy | Skip missing; if 0 remaining → fail loud | graceful degradation без silent review на неполном roster |
| Profile snapshot in state | Не сохраняется (live read each cycle) | simplicity; profile change mid-loop = human mistake |
| PR structure | 1 PR, 3 commits (rename / engine / spec+drift), no squash | bisectability vs атомарности — компромисс через PR-атомарность, не коммит-атомарность |
| Agent memory updates | Filesystem housekeeping, OUT of git commits | гитигнорные, проверяются по filesystem read |
| Historical research artifacts (swarm-report/*.md) | OUT of scope rewrite | гитигнорные historical records |
| Timing | Commit 1 (pure rename) может быть смёрджен до или после v0.11.0; Commit 2 ждёт v0.11.0 | test-plan receipt stabilization |
| Receipt section optionality | `receipt:` — optional; отсутствие = no receipt writing (NOT `path_template: none`) | clean contract, не sentinel value |
| Baseline stability | Frozen parameters; **3 runs per fixture**; structural equivalence via **modal match** (verdict label, agent set, modal cycle count, YAML shape) | Single-run stochastic noise ломает comparison; 3-run modal отсеивает разовые выпадения |
| PROFILE_INVENTORY source-of-truth | `multiexpert-review/profiles/README.md` — canonical; engine читает на startup, не хардкодит | single source, добавление профиля — one-file + one-line edit |
| profile_hint role | Defense-in-depth поверх path-glob detection (path/frontmatter — primary для spec artifacts) | Hint contract fragile к agent-rewrite, но path-glob для `docs/specs/**` уже покрывает spec case |
| Fail-loud semantics | Prefix `[multiexpert-review ERROR] <category>: <details>` в первой строке output | Consumer различает engine error от review FAIL verdict |
| allow_single_reviewer defaults | implementation-plan: true (сохраняет поведение); test-plan: false (panel обязательна); spec: false | Разные профили — разные политики; explicit per-profile |
| PR squash-policy | Manual enforcement: в PR-description явно указать «DO NOT SQUASH»; выбрать Rebase/Merge commit при merge | Нет автоматического branch protection для этого одного PR |

## Out of Scope

- **Новые профили вне Phase 1-2**: adr, migration-plan, research-report, decision — YAGNI.
- **Model diversity для PoLL**: литература требует разных model families; Claude Code — один family. Known limitation, фиксируется как principle-level debt.
- **Rewrite historical research artifacts** (`swarm-report/*.md`): гитигнорные; line-refs внутри устареют, но document — historical record.
- **Runtime skill registry / alias**: нет — rename прямой.
- **Breaking changes в receipt формате** `generate-test-plan`: формат фиксирован.
- **Изменения агентов** (developer-workflow-experts): агенты не меняются; инвокации через профили.
- **Переименование skill во внешних плагинах / CI**: проверено — нет внешних references.
- **Автоматическое удаление легаси state-file**: graceful read — да; delete — нет (user decides).
- **Profile versioning mechanism**: YAGNI; profile change mid-loop не поддерживается, пользователь не запускает revise на изменённом профиле.
- **Protection от model-prompt-rewrite** `profile_hint`: args-string контракт уязвим к agents-modifying-args; mitigation через state-file logging (см. §7) дает audit trail, но не prevention. Принято — low risk для текущих callsites (feature-flow / write-spec — закрытые инвокации).

## Open Questions

Нет блокирующих. Non-blocking:

- [ ] **Q1** Структурные signatures test-plan регекспы cross-check на реальных fixture-ах из `docs/testplans/` — *non-blocking, уточняется в Phase 0*. Текущие regex из плана `^## Test Cases`, `^#{1,6}\s+TC-[\w-]+`, `P[0-3]` — могут потребовать корректировки на реальных fixture-ах.

## Future Phases

N/A — одна спека, одна имплементация, три коммита в одном PR.
