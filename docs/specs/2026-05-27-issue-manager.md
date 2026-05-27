---
type: spec
slug: issue-manager
date: 2026-05-27
status: approved
platform: [generic]
surfaces: [cli]
risk_areas: []
non_functional:
  sla:
  a11y:
acceptance_criteria_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10]
design:
  figma:
  design_system:
---

# Spec: issue-manager — менеджер бэклога GitHub issues

Date: 2026-05-27
Status: approved
Slug: issue-manager
Plugin owner: `developer-workflow` (рядом с оркестраторными skills и manual-tester)

---

## Context and Motivation

Сейчас работа над набором задач из трекера ведётся вручную: разработчик сам читает issues,
прикидывает зависимости и порядок, по одной прогоняет их через стандартный dev-workflow и руками
двигает статусы на доске. Нужен skill-оркестратор, которому даёшь scope (ссылку на issue, эпик,
список или «разбери всё открытое»), а он разбирает бэклог, строит порядок с учётом зависимостей,
предлагает план, после одобрения последовательно прогоняет каждую готовую задачу через полный
стандартный флоу (делегируя тяжёлую работу), ведёт статусы issue и доводит каждую до открытого PR.
Менеджер — это **supervisor**: он сам не пишет код и не запускает проверки, а оркеструет, читает
факты завершения и ведёт доску.

Phase 1 (эта спека): общее ядро + единственный execution-backend **A (single-session)** на
**GitHub**. Backend B (Agent Teams), другие трекеры, эпики и параллелизм — в Future Phases.

Полное исследование с проверкой механизмов против Claude Code docs:
`swarm-report/research/research-issue-orchestrator.md`.

## Acceptance Criteria

Фича готова, когда ВСЕ пункты истинны.

- [ ] **AC-1** — Получив scope (URL issue / список номеров / «все открытые» / ссылку на эпик),
      skill возвращает JSON со списком открытых GitHub issues, их статусом и обнаруженными
      зависимостями, полученный **исключительно через `scripts/gh/`** (проверка: ни одного
      ad-hoc `gh`/GraphQL-вызова в теле прогона; см. AC-8).
- [ ] **AC-2** — Skill строит DAG из GitHub sub-issues и распарсенных «blocked by #N» в
      теле/комментариях и детектит циклы. **При обнаружении цикла** skill предъявляет участников
      цикла и блокирует одобрение Phase0 до ручного разрешения. Иначе предъявляет предлагаемый
      порядок; пользователь может вернуть переупорядоченный список номеров ДО одобрения (гейт Phase0).
- [ ] **AC-3** — После одобрения Phase0 skill обрабатывает готовые issues **последовательно**: для
      каждой переводит её в In-Progress на доске, прогоняет per-task флоу до **открытого PR**,
      связанного с issue, и НЕ мёржит. Обязательный минимум флоу: `implement` (делегируется) →
      `/check` → `/finalize` → `/acceptance` → `/create-pr`. `/research` и `/write-spec`
      запускаются опционально — только когда issue не содержит достаточной информации для прямой
      реализации (адаптивная глубина).
- [ ] **AC-4** — Skill сам НЕ редактирует исходный код проекта и НЕ запускает проверки/тесты — вся
      работа с кодом делегируется субагентам/скиллам; менеджер читает только **completion signal**
      (см. AC-10) и факты трекера (PR открыт/смержен) для продвижения доски.
- [ ] **AC-5** — Переходы статусов идемпотентны: повторный запуск skill на том же бэклоге читает
      текущее состояние GitHub и не применяет переход дважды (не переоткрывает/не перезакрывает
      уже корректную issue; `transition_status` пишет только при `current != target`). Все
      write-операции `scripts/gh/` идемпотентны (read-before-write или upsert-by-marker), не только
      переход статуса — `add_comment`/`link_pr` на resume не дублируют коммент/связь.
- [ ] **AC-6** — Задача, провалившая свой флоу (completion signal `failed`/`blocked`), НЕ доходит
      до PR: помечается на доске состоянием **blocked** (label `status:blocked`, и при наличии Project v2 —
      соответствующий status-option), не имеет связанного PR, и зависящие от неё issues НЕ
      переводятся в In-Progress и не диспетчатся. Блокировка распространяется на всю downstream-ветку
      DAG от заблокированного узла (транзитивно зависящие тоже не диспетчатся). Blocked-список
      всплывает в сводке батча.
- [ ] **AC-7** — Skill переживает компакцию контекста: при возобновлении перечитывает свой
      state-файл, re-fetch'ит ground-truth доски GitHub и продолжает с первой незавершённой задачи,
      не переделывая завершённые (derived-маркеры верифицируются против трекера; конфликт → трекер).
- [ ] **AC-8** — Все операции с GitHub идут исключительно через бандлированные скрипты в
      `scripts/gh/` (тело skill не выдаёт ad-hoc `gh`/GraphQL-команд); скрипты возвращают
      структурированный JSON. Перед ANALYZE skill прогоняет prerequisite-проверки (см. Prerequisites)
      и при провале останавливается с понятным сообщением (fail-fast), без частичных записей.
- [ ] **AC-9** — Merge и promotion PR остаются человеческими гейтами в части merge: skill
      останавливается на открытом PR и **не мёржит** без явного действия пользователя. PR
      открывается сразу как **ready-for-review** (см. Decisions).
- [ ] **AC-10** — `references/exec-contract.md` определяет **completion-signal** схему и интерфейс
      execution-backend; Backend A ему соответствует. Проверка: файл существует и содержит JSON-схему
      `{status: done|failed|blocked, pr_url?, failed_gate?, blocked_reason?}` + сигнатуру вызова
      backend'а (вход: task id + scope + допустимая глубина флоу; выход: completion signal); ядро
      вызывает backend только через эту форму, не зная конкретный backend.

**Authoritative definition of done.** Имплементирующий агент валидирует против этого списка перед
тем, как пометить любую задачу завершённой.

## Prerequisites

Каждое предусловие skill проверяет на старте ANALYZE (fail-fast, AC-8).

| Prerequisite | Status | Owner | Exit-criterion (как проверяется) |
|--------------|--------|-------|----------------------------------|
| `gh` CLI установлен и аутентифицирован (scope `repo`; при Projects — `project`) | ⬜ Todo | Human | `gh auth status` завершается с кодом 0 |
| Целевой GitHub-репозиторий с открытыми issues | ⬜ Todo | Human | `gh issue list -R <repo> --state open --json number` возвращает валидный JSON |
| (Опционально) GitHub Project v2 для статус-колонок | ⬜ Todo | Human | `gh project list --owner <owner>` содержит целевой проект; иначе fallback на open/closed + labels |

## Affected Modules and Files

| Module / File | Change type | Notes |
|---------------|-------------|-------|
| `plugins/developer-workflow/skills/issue-manager/SKILL.md` | New | Стабильный контракт оркестрации: ANALYZE → Phase0 → EXECUTE(A) → RECONCILE |
| `plugins/developer-workflow/skills/issue-manager/scripts/gh/fetch_issue.sh` | New | Один issue по ref → JSON |
| `plugins/developer-workflow/skills/issue-manager/scripts/gh/list_issues.sh` | New | Список по фильтру → JSON |
| `plugins/developer-workflow/skills/issue-manager/scripts/gh/get_dependencies.sh` | New | sub-issues + parse «blocked by #N» → JSON-рёбра |
| `plugins/developer-workflow/skills/issue-manager/scripts/gh/transition_status.sh` | New | Идемпотентный переход (read-before-write); open/closed + Project v2 GraphQL field/option id |
| `plugins/developer-workflow/skills/issue-manager/scripts/gh/link_pr.sh` | New | Связать PR с issue |
| `plugins/developer-workflow/skills/issue-manager/scripts/gh/add_comment.sh` | New | Коммент к issue |
| `plugins/developer-workflow/skills/issue-manager/scripts/gh/get_completion_signal.sh` | New | Факт завершения: смержен ли связанный PR / открыт ли → JSON |
| `plugins/developer-workflow/skills/issue-manager/references/adapter-contract.md` | New | Контракт tracker-adapter (abstract actions, JSON-схемы) + **adapter-resolver** (action → скрипт) |
| `plugins/developer-workflow/skills/issue-manager/references/exec-contract.md` | New | Интерфейс execution-backend + **completion-signal** схема (см. AC-10) |
| `plugins/developer-workflow/skills/issue-manager/references/exec-single.md` | New | Backend A: per-task флоу, offload в субагентов, реализация exec-contract |
| `plugins/developer-workflow/skills/issue-manager/references/phase0.md` | New | DAG, детект циклов, формат правки порядка, scope-cap, гейт одобрения |
| `plugins/developer-workflow/skills/issue-manager/references/reconcile.md` | New | Reconcile-проход, idempotent transition, схема state-файла, compaction-resume |
| `plugins/developer-workflow/CLAUDE.md` | Modified | Добавить issue-manager в roster скиллов (счётчик +1) и в раздел планирования |
| `plugins/developer-workflow/.claude-plugin/plugin.json` | Modified (опц.) | Обновить `description`, если он перечисляет roster skills (skills auto-discovery — регистрация не требуется) |

Key integration points:
- Reuse существующих скиллов того же plugin-семейства per task: `/research`, `/write-spec` (по
  необходимости), `/finalize`, `/acceptance`, `/create-pr` — вызываются из main-session.
- Engineer-субагенты (`kotlin-engineer`/`compose-developer`/…) и Explore — куда уходит тяжёлая
  skill-free работа.
- Структурный прецедент: `skills/drive-to-merge/` (state-machine loop, references-pattern,
  ScheduleWakeup, always-ask merge gate).

## Technical Approach

**Структура.** Один skill = стабильное ядро (SKILL.md) + волатильные процедуры в `references/`.
Ядро: ANALYZE (разбор бэклога, DAG, readiness) → Phase0 (предъявить порядок, одобрение) →
EXECUTE (Backend A) → RECONCILE (продвижение доски). Главное ядро держит **только** оркестрацию и
state; каждый per-task флоу offload-ится в субагентов/скиллы (снимает кажущееся напряжение с
правилом оркестрации «main-session не держит длинные процессы» — тяжёлое уходит за границу контекста).

**Execution-backend контракт (AC-10).** `references/exec-contract.md` определяет интерфейс между
ядром и исполнителем, чтобы Phase 2 (Backend B) реализовал тот же контракт без правок ядра:
- **Вход:** `task_id`, `scope` (issue ref + контекст), `allowed_depth` (адаптивная глубина флоу).
- **Выход (completion signal, JSON):** `{ "status": "done|failed|blocked", "pr_url": "<url|null>",
  "failed_gate": "<string|null>", "blocked_reason": "<string|null>" }`. `failed_gate` —
  **backend-определяемая свободная строка**; набор значений задаёт конкретный backend
  (для Backend A рекомендованный словарь — `check|finalize|acceptance|create-pr`). Ядро не
  интерпретирует это значение как enum — иначе Backend B пришлось бы расширять «контракт» (= правка
  ядра), что нарушило бы инвариант AC-10.
- **Инвариант:** ядро вызывает backend только через эту форму, не зная, какой backend исполняет.
`exec-single.md` — реализация Backend A; `exec-team.md` (Future) — Backend B.

**Backend A (single-session).** Менеджер в main-session последовательно, по одной готовой задаче:
переводит issue в In-Progress → прогоняет per-task флоу (AC-3) до открытого PR, максимально сгружая
контекстно-тяжёлую работу в субагентов → формирует completion signal → продвигает доску → берёт
следующую. Останов на открытом PR (merge исключён).

**Tracker-adapter = бандлированные скрипты + resolver.** Ядро ссылается на **abstract actions**
(`list_issues`, `transition_status`, …); `adapter-contract.md` задаёт **adapter-resolver** — маппинг
action → конкретный скрипт (через переменную пути / dispatch-таблицу). Resolver-lookup живёт в
`adapter-contract.md` (или env/конфиге), **не в SKILL.md**: ядро ссылается только на abstract
action и не знает имён конкретных скриптов, так что Phase 3 добавит `scripts/gitlab/` без правок
SKILL.md. Каждый скрипт детерминирован, отдаёт JSON, и инкапсулирует
квирки GitHub: глобальный issue id для sub-issues, GraphQL `field_id`/`option_id` для статусов
Projects v2, парсинг «blocked by #N». Тело skill не строит `gh`/GraphQL на лету и не содержит
`if tracker == github`.

**Состояние и идемпотентность.** Трекер (GitHub) — единственный source of truth для lifecycle-статуса:
`transition_status` читает текущий статус и пишет только при `current != target`. Orchestration-state
— в `swarm-report/issue-manager-<batch>-state.md`, где `<batch>` = слаг из scope (имя эпика / хэш
списка номеров / `all-open-<YYYYMMDD-HHMM>`). **Схема state-файла** (в `reconcile.md`): на issue —
`number`, derived-`phase` (analyzed/in-progress/pr-open/done/blocked), `pr_url`, `last_verified_at`.
Никаких полей, которые нельзя пересчитать из трекера+gh. Phase-маркеры derived: на resume
верифицируются против ground-truth (PR по URL существует? статус issue совпал?), конфликт → доверять
трекеру и переписывать файл.

**Phase0-протокол.** Skill предъявляет: список готовых issue, DAG, предлагаемый порядок. Пользователь
правит, возвращая переупорядоченный список номеров (или подтверждает). Для scope «все открытые» —
**cap** на размер батча (дефолтное значение фиксируется и настраивается в `phase0.md`; сверх cap —
предупреждение и запрос сузить scope), т.к. большой бэклог упирается в потолок контекста Backend A.

**Compaction-resilience.** На возобновлении первым действием — re-read state-файла + re-fetch доски;
продолжение с первой незавершённой задачи. Это governing-ограничение Backend A (потолок контекста
main-session при N задачах).

**Обработка ошибок.** Сбой per-task флоу → completion signal `failed`/`blocked` → issue получает
состояние blocked (label + опц. Project v2 option), остаётся не-Done, зависящие issues не диспетчатся,
батч продолжает остальные независимые ветки и поднимает blocked-список пользователю. Сбой
adapter-скрипта (gh недоступен/нет прав) → стоп с понятным сообщением, без частичных записей.

## Technical Constraints

- Весь контент skill — на **английском** (PLUGIN-STANDARDS: shipped extension content). Эта спека в
  `docs/` — исключение (maintainer-facing).
- Менеджер **НЕ** делает Edit/Write по project-source и не запускает проверки — всё делегируется
  (несущий инвариант, зафиксировать в SKILL.md как Non-negotiable).
- GitHub-операции — только через бандлированные скрипты; никаких ad-hoc `gh`/GraphQL в теле skill;
  никаких `if tracker == github` в ядре (ветвление — забота adapter-resolver'а).
- `disable-model-invocation: true` — запуск только явной командой (операция тяжёлая, побочные
  эффекты в трекере).
- Реюз существующих скиллов семейства, без дублирования их логики; если нужен форк поведения —
  extension-point в ядре, не копия.
- Новые внешние зависимости не добавлять (только `gh`, уже используемый в create-pr/drive-to-merge).

## Decisions Made

Выбор зафиксирован; имплементирующий агент его не пересматривает.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Роль менеджера | Supervisor (не executor) | Не дублирует pipeline; единственная безопасная топология (flat-сети агентов амплифицируют ошибки ~17×) |
| Форм-фактор | Skill в main-session | Только main-session вызывает skills; subagent скиллы не вызывает и не спавнит (verified, issue #38719) |
| Execution-механизм | Backend A: всё в одной сессии, offload в субагентов | Пользовательское требование; `claude -p`/SDK отклонены (отдельные лимиты, отдельный процесс) |
| Source of truth | Трекер (GitHub) | Идемпотентность через read-before-write; тяжёлый resumable state-файл не нужен |
| GitHub-операции | Бандлированные скрипты с JSON + adapter-resolver | Дешевле по токенам, детерминированнее, инкапсулируют квирки API; resolver не пускает GitHub-специфику в ядро |
| Граница прогона | До открытого PR | Внутри автономного прогона нет места человеческим гейтам; merge — необратим, оставлен человеку |
| Точка останова PR | Ready-for-review (не draft) | Память `feedback_pr_ready_immediately`: в batch-обработке issues PR открывается сразу ready; более специфичное правило, чем generic draft→promote; merge всё равно остаётся человеческим гейтом (AC-9) |
| Гейт менеджера | Один — Phase0 (план+DAG→одобрение) | Порядок решается раз; повторное одобрение на каждой задаче = confirmation-spam; внутреннее качество гарантируют finalize/acceptance |
| Модель статуса доски | detect Project v2 status field → fallback open/closed + label-конвенция (`status:in-progress`, `status:blocked`) | Не у всех репо есть Project v2; нужен носитель для In-Progress/blocked (AC-3/AC-6) |
| DAG на GitHub | Эвристический (sub-issues + parse «blocked by») + ручное подтверждение в Phase0 | У GitHub нет типизированных blocks/blocked-by; эвристика ненадёжна → человек подтверждает |
| Per-task флоу | Адаптивная глубина: implement→check→finalize→acceptance→create-pr обязательны; research/spec по необходимости | Пользователь кладёт исчерпывающую инфу в issue → research/spec нужны не всем; finalize/acceptance — обязательные quality/acceptance гейты |
| Трекеры | Только GitHub | Явный фокус, не распыляться; другие — Future за тем же контрактом |

## Out of Scope

- **Backend B (Agent Teams)** и любой мультиагентный режим — Future Phase 2.
- **Другие трекеры** (GitLab, Linear) — Future.
- **Синхронизация эпиков** (epic-transition по завершении детей) — Future.
- **Параллельный dispatch** задач и file-overlap-guard — Future; Phase 1 строго sequential.
- **Real-time мониторинг** исполнения — менеджер читает факты по чекпоинтам, не следит непрерывно.
- **Автоматический merge** PR — человеческий гейт.
- **`claude -p` / Agent SDK** как механизм исполнения — отклонены.

## Open Questions

None — открытые вопросы закрыты в Decisions Made (точка останова PR, модель статуса доски,
адаптивность глубины per-task флоу).

## Future Phases

**Phase 2 — Backend B (Agent Teams):** второй execution-backend, реализующий тот же
`exec-contract.md` — teammate'ы со своим контекстом и доступом к skills (флаг
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), shared task list = backlog-DAG, detect-and-degrade на A.
Снимает потолок контекста Backend A. Известные риски: no session resumption с in-process
teammate'ами, отставание task-status.

**Phase 3 — Мульти-трекер:** реализации adapter'а для GitLab (`glab` + GraphQL Work Items) и Linear
(soft-ref MCP) за тем же контрактом и через adapter-resolver.

**Phase 4 — Эпики и параллелизм:** синхронизация статуса эпиков по завершении детей; контролируемый
параллельный dispatch с file-overlap-guard.

Специфицируются отдельно после реализации и валидации Phase 1.
