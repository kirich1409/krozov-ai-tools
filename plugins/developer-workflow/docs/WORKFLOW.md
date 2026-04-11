# Полный цикл разработки: от идеи до merge

## 1. Обзор

developer-workflow реализует полностью автономный цикл разработки, управляемый конечным
автоматом с явными переходами между стадиями. Каждая задача при поступлении классифицируется
по одному из пяти профилей (Feature, Bug Fix, Migration, Research, Trivial), и профиль
определяет, какие стадии пайплайна будут выполнены. Это не жёсткий waterfall -- профиль
может пропускать стадии (Trivial не требует Research и Plan) или заменять их
(Migration делегирует в `code-migration`).

Исследование выполняется Research Consortium -- до пяти параллельных экспертных агентов,
каждый из которых работает независимо в своём домене (кодовая база, веб, документация,
зависимости, архитектура). Результаты синтезируются и проходят автоматическое ревью
через `business-analyst`. Это гарантирует, что решения принимаются на основе данных,
а не только на обучающих данных модели.

Качество обеспечивается Quality Loop -- шесть последовательных гейтов от компиляции до
проверки соответствия исходному замыслу. Ключевой принцип: автор кода никогда не проверяет
свой код сам -- gate 4 запускает отдельного `code-reviewer` агента, который получает
только описание задачи, план и git diff, без контекста реализации. Receipt-based gating
гарантирует, что ни одна стадия не начнётся без артефакта предыдущей. Re-anchoring
при каждом переходе между стадиями предотвращает дрейф от исходного замысла.


## 2. Обзор пайплайна

```
ИДЕЯ / ЗАПРОС НА ФИЧУ
  |
  v
[Профилирование задачи] ---- Классификация: Feature / Bug Fix / Migration / Research / Trivial
  |
  v
[research] ---- Research Consortium (до 5 параллельных экспертов)
  |                Артефакт: swarm-report/<slug>-research.md
  v
[Plan Mode + plan-review] ---- Имплементационный план + PoLL-ревью
  |                              Артефакт: swarm-report/<slug>-plan.md
  v
[implement-task] ---- Полный автономный цикл
  |  |-- kotlin-engineer / compose-developer / code-migration
  |  |-- Quality Loop (6 гейтов + code-reviewer)
  |  |     Артефакт: swarm-report/<slug>-quality.md
  |  '-- Verification (Phase 2.5)
  |        Артефакт: swarm-report/<slug>-verify.md
  v
[create-pr] ---- Draft PR -> Ready for Review
  |                Артефакт: swarm-report/<slug>-pr.md
  v
[pr-drive-to-merge] ---- CI мониторинг -> Обработка ревью -> Merge
  |  '-- address-review-feedback (подчинённый скилл)
  v
MERGED
```


## 3. Профили задач и маршрутизация

| Профиль | Пайплайн | Сигналы | Пропускает |
|---------|----------|---------|------------|
| **Feature** | Research -> Plan -> Implement -> Quality -> Verify -> PR -> Merge | "add", "implement", "build", "create" | -- |
| **Bug Fix** | Reproduce -> Diagnose -> Fix -> Quality -> PR -> Merge | "fix", "broken", "crash", "regression" | Research, Plan, Verify |
| **Migration** | Research -> Snapshot -> Migrate -> Verify -> PR -> Merge | "migrate", "replace", "switch to" | Plan (делегирует в `code-migration`) |
| **Research** | Research -> Report | "investigate", "compare", "evaluate" | Implement, Quality, Verify, PR, Merge |
| **Trivial** | Implement -> Quality -> PR -> Merge | Однофайловое изменение, config tweak | Research, Plan, Verify |

Автоопределение по ключевым словам и контексту. При неоднозначности -- запрос
подтверждения у пользователя перед началом работы.


## 4. Quality Loop

```
                              Iteration cap: max 5 полных циклов
                              Per gate: max 3 попытки исправления
     ___________________________________________________________________
    |                                                                   |
    v                                                                   |
+--------+    +---------+    +-------+    +-------------+    +--------+ |
| Gate 1 |--->| Gate 2  |--->| Gate 3|--->|   Gate 4    |--->| Gate 5 | |
| Build  |    | Static  |    | Tests |    | code-       |    | Expert | |
|        |    | Analysis|    |       |    | reviewer    |    | Reviews| |
+--------+    +---------+    +-------+    +-------------+    +--------+ |
    |fail         |fail          |fail         |                  |     |
    v             v              v             v                  v     |
 [fix]         [fix]          [fix]     PASS: gate 5        +--------+ |
    |             |              |      WARN: gate 5 +      | Gate 6 | |
    '-----.-------'-------.------'       acknowledged risks | Intent  | |
          |               |             FAIL: --> Implement | Check   | |
          '--------.------'                                 +--------+ |
                   |                                           |       |
                   '------- (fix cycle) -----------------------'-------'
```

### Гейты

| # | Гейт | Действие | Исполнитель |
|---|-------|----------|-------------|
| 1 | Build | Компиляция проекта, устранение ошибок | Implementation agent |
| 2 | Static Analysis | Lint, форматирование, неиспользуемые импорты | Implementation agent |
| 3 | Tests | Unit + integration тесты, исправление падений | Implementation agent |
| 4 | Semantic Self-Review | Сравнение intent vs. `git diff` | `code-reviewer` agent |
| 5 | Expert Reviews | Параллельные доменные ревью (по триггерам) | Specialist agents |
| 6 | Intent Check | Перечитать задачу + план, проверить соответствие | Orchestrator |

### Триггеры экспертных ревью (gate 5)

| Эксперт | Триггер -- изменённые файлы затрагивают: |
|---------|------------------------------------------|
| `security-expert` | Auth, encryption, token storage, network, permissions, PII |
| `performance-expert` | RecyclerView/LazyColumn, DB queries, image loading, hot loops |
| `architecture-expert` | Новые модули, изменение direction зависимостей, public API |

Если ни один триггер не сработал -- gate 5 пропускается.

### Обработка вердиктов (gate 4)

| Вердикт | Действие оркестратора |
|---------|----------------------|
| **PASS** | Переход к gate 5 (expert reviews) |
| **WARN** | Переход к gate 5; major issues записываются в `<slug>-quality.md` как "Acknowledged risks" |
| **FAIL** | Backward transition -> Implement; исправить critical issues, повторить gate 4 (max 3 цикла) |

### Определение build-системы

| Приоритет | Файл | Build | Lint | Test |
|-----------|-------|-------|------|------|
| 1 | `Makefile` | `make build` | `make lint` | `make test` |
| 2 | `package.json` | `npm run build` | `npm run lint` | `npm test` |
| 3 | `Cargo.toml` | `cargo build` | `cargo clippy` | `cargo test` |
| 4 | `build.gradle(.kts)` | `./gradlew build` | `./gradlew lint` | `./gradlew test` |
| 5 | `pom.xml` | `mvn package -q` | `mvn checkstyle:check` | `mvn test` |
| 6 | `go.mod` | `go build ./...` | `golangci-lint run` | `go test ./...` |
| 7 | `pyproject.toml` | `pip install -e .` | `ruff check .` | `pytest` |


## 5. Research Consortium

```
                    [Scope the Research]
                           |
              Topic + Context + Constraints
                           |
         .-----------------+------------------.
         |         |         |        |        |
         v         v         v        v        v
    +--------+ +------+ +------+ +------+ +-----------+
    |Codebase| | Web  | | Docs | | Deps | |Architecture|
    |Expert  | |Expert| |Expert| |Expert| |  Expert    |
    +--------+ +------+ +------+ +------+ +-----------+
    |ast-index| |Perplex| |Deep- | |maven-| |arch.-     |
    |Read     | |ity    | |Wiki  | |mcp   | |expert     |
    |Grep     | |Web-   | |Cont- | |tools | |agent      |
    |         | |Search | |ext7  | |      | |           |
    +----+----+ +--+---+ +--+---+ +--+---+ +-----+-----+
         |         |         |        |           |
         '-----.---'----.----'----.---'-----.-----'
               |                            |
               v                            v
        +-------------+             +--------------+
        |  Synthesis  |             | State file   |
        | (cross-ref, |             | (compaction- |
        |  converge,  |             |  resilient)  |
        |  contradict)|             +--------------+
        +------+------+
               |
               v
      +----------------+
      |business-analyst|
      | auto-review    |
      +------+---------+
             |
             v
    swarm-report/<slug>-research.md
```

### Экспертные треки

| Эксперт | Когда включать | Инструменты |
|---------|---------------|-------------|
| **Codebase** | Тема затрагивает существующий код, паттерны, модули | `ast-index`, Read, Grep |
| **Web** | Всегда (обязательно -- Web-Lookup Mandate) | Perplexity (`perplexity_search`, `perplexity_research`), WebSearch |
| **Docs** | Тема связана с конкретными библиотеками/фреймворками | DeepWiki, Context7 |
| **Dependencies** | Добавление, замена или оценка JVM/KMP зависимостей | maven-mcp tools |
| **Architecture** | Влияние на модульные границы, direction зависимостей, API | `architecture-expert` agent |

**Web-Lookup Mandate:** интернет-исследование обязательно. Каждый research должен дать
хотя бы один web-sourced insight. Полагаться только на кодовую базу и training data запрещено.

### Поток данных

1. Эксперты работают **параллельно и независимо** -- результаты одного не передаются другому
2. **Synthesis** -- оркестратор объединяет: ищет convergence, contradictions, gaps
3. **Auto-review** -- `business-analyst` проверяет полноту, продуктовый смысл, практичность
4. Если auto-review находит gaps -- targeted re-run отдельных экспертов


## 6. Конечный автомат (State Machine)

```
Research ------> Plan ------> Implement ------> Quality ------> Verify ------> PR ------> Merge
    ^               |              |                |               |              |
    |               |              |                |               |              |
    '---- gaps -----'              |                |               |              |
    ^                              |                |               |              |
    |                              |                |               |              |
    '---- scope too large ---------'                |               |              |
                                   ^                |               |              |
                                   |                |               |              |
                                   '---- issues ----'               |              |
                                   ^                                |              |
                                   |                                |              |
                                   '---- verify fails --------------'              |
                                   ^                                               |
                                   |                                               |
                                   '---- review feedback --------------------------'
```

### Прямые переходы (по умолчанию)

| Из | В | Условие |
|----|---|---------|
| Research | Plan | Исследование завершено |
| Plan | Implement | План прошёл ревью |
| Implement | Quality | Реализация завершена |
| Quality | Verify | Все гейты пройдены |
| Verify | PR | Верификация PASS |
| PR | Merge | CI зелёный, ревью одобрено |

### Обратные переходы (recovery paths)

| Из | В | Триггер |
|----|---|---------|
| Plan | Research | Plan review выявил пробелы в знаниях |
| Implement | Research | Scope оказался значительно больше ожидаемого |
| Quality | Implement | Quality loop нашёл issues, требующие code changes |
| Verify | Implement | Верификация провалилась -- fix и re-verify |
| PR | Implement | Review feedback требует code changes |

**Правила обратных переходов:**
1. Причина перехода логируется в артефакте текущей стадии
2. Re-anchoring к исходному intent перед входом в предыдущую стадию
3. Carry forward -- не повторять завершённую работу
4. Если 3-й возврат к той же стадии -- эскалация к пользователю


## 7. Receipt-Based Gating

Каждая стадия производит артефакт в `swarm-report/`. Следующая стадия **обязана** прочитать
его перед началом работы. Ни одна стадия не начинается без receipt предыдущей.

| Стадия | Артефакт | Требуется перед следующей |
|--------|----------|-------------------------|
| Research | `<slug>-research.md` | Plan (Feature / Migration) |
| Plan | `<slug>-plan.md` | Implement |
| Implement | `<slug>-implement.md` | Quality |
| Quality | `<slug>-quality.md` | Verify |
| Verify | `<slug>-verify.md` | PR |
| PR | `<slug>-pr.md` | Merge |

**Slug:** kebab-case из описания задачи, 2-4 слова.
Пример: задача "Add user avatar upload" -> slug `user-avatar-upload`.

**Профиль-зависимый gating:** артефакты требуются только для стадий, включённых в профиль.
Trivial: первый артефакт -- `<slug>-implement.md`. Bug Fix: `<slug>-research.md` не требуется.

**Если артефакт отсутствует** -> предыдущая стадия не завершена -> не продолжать.

### Содержание артефакта

Каждый артефакт включает:
- Название стадии и timestamp
- Резюме выполненного / найденного
- Ключевые решения (с обоснованием)
- Затронутые файлы (для implementation)
- PASS/FAIL вердикт (для Quality и Verify)
- Лог обратных переходов (если были)


## 8. Карта скиллов и агентов

### Скиллы

| Скилл | Стадия пайплайна | Описание |
|-------|-----------------|----------|
| `research` | Research | Research Consortium -- до 5 параллельных экспертов, синтез, auto-review |
| `plan-review` | Plan | PoLL-ревью плана несколькими агентами |
| `implement-task` | Implement -> Quality -> PR -> Merge | Полный автономный цикл (explicit-only) |
| `code-migration` | Implement (Migration) | Discover -> snapshot -> migrate -> verify -> cleanup |
| `kmp-migration` | Implement (Migration) | Миграция модуля в Kotlin Multiplatform |
| `migrate-to-compose` | Implement (Migration) | View -> Compose миграция с visual baseline |
| `create-pr` | PR | Создание PR/MR: title, description, labels, reviewers |
| `pr-drive-to-merge`* | Merge | CI мониторинг, обработка ревью, drive to merge |
| `address-review-feedback` | Merge (sub-skill) | Анализ и обработка комментариев ревьюера |
| `generate-test-plan` | Plan / Verify | Structured test plan из спецификации |
| `test-feature` | Verify | Верификация фичи на живом приложении vs. спецификация |
| `exploratory-test` | Verify | Ненаправленный поиск багов без спецификации |
| `prepare-for-pr`* | Quality | Запуск Quality Loop перед PR |
| `decompose-feature`* | Research / Plan | Декомпозиция фичи на задачи |
| `write-tests`* | Implement | Ретроактивное написание тестов |
| `simplify`** | Quality | Ревью кода на reuse, качество, эффективность |

*Определены в routing table, но не имеют отдельного skill directory.
**Скилл из другого плагина / built-in.

### Агенты

| Агент | Стадия | Роль |
|-------|--------|------|
| `code-reviewer` | Quality (gate 4) | Независимое ревью: intent vs. diff |
| `kotlin-engineer` | Implement | Kotlin бизнес-логика, data/domain layer, ViewModel |
| `compose-developer` | Implement | Compose UI: экраны, компоненты, темы, навигация |
| `architecture-expert` | Research, Quality (gate 5) | Модульная структура, dependency direction, API design |
| `business-analyst` | Research (auto-review) | Полнота, продуктовый смысл, практичность |
| `security-expert` | Quality (gate 5) | Auth, encryption, token storage, OWASP |
| `performance-expert` | Quality (gate 5) | N+1, memory leaks, UI jank, hot loops |
| `build-engineer` | Quality (gate 5) | Gradle config, build performance, module structure |
| `manual-tester` | Verify | QA на живом приложении: test cases, bug reports |
| `ux-expert` | Quality (gate 5) | UX ревью, accessibility, platform conventions |
| `devops-expert` | PR / Merge | CI/CD, deployment, release automation |


## 9. Модели агентов

| Агент | Модель | Обоснование |
|-------|--------|-------------|
| `architecture-expert` | opus | Глубокий структурный анализ, multi-module reasoning |
| `business-analyst` | opus | Стратегическое мышление, product sense, trade-off analysis |
| `security-expert` | opus | Безопасность требует thoroughness и deep analysis |
| `code-reviewer` | sonnet | Быстрая итерация в quality loop, stateless invocations |
| `kotlin-engineer` | sonnet | Стандартная имплементация, code generation |
| `compose-developer` | sonnet | UI код, паттерны, preview generation |
| `build-engineer` | sonnet | Gradle config, build optimization |
| `performance-expert` | sonnet | Анализ производительности по коду |
| `manual-tester` | sonnet | QA execution, bug reporting |
| `ux-expert` | sonnet | UX patterns, accessibility checks |
| `devops-expert` | sonnet | CI/CD pipelines, deployment config |


## 10. Внешние интеграции

| Интеграция | Использование | Стадия |
|------------|---------------|--------|
| **maven-mcp** | Версии зависимостей, уязвимости, совместимость, changelog | Research (Dependencies Expert), Implementation |
| **sensitive-guard** | Сканирование файлов на секреты и PII перед отправкой | Pre-tool hook (все стадии) |
| **Perplexity** | Web research: подходы, best practices, pitfalls | Research (Web Expert) |
| **DeepWiki** | AI-сгенерированная документация GitHub-репозиториев | Research (Docs Expert) |
| **Context7** | Документация библиотек и фреймворков | Research (Docs Expert) |
| **mobile MCP** | Тестирование на реальных устройствах и эмуляторах | Verify (`manual-tester`, `test-feature`) |
| **playwright MCP** | Тестирование веб-приложений в браузере | Verify (`manual-tester`) |


## 11. Re-Anchoring Protocol

Перед каждым переходом между стадиями оркестратор выполняет re-anchoring:

1. Перечитать **оригинальное описание задачи** (verbatim из запроса пользователя)
2. Перечитать **research report** (`swarm-report/<slug>-research.md`) -- если существует
3. Перечитать **план** (`swarm-report/<slug>-plan.md`) -- если существует
4. Включить пути к артефактам в prompt следующего агента -- агент читает их сам

Это обязательно при каждом переходе, включая обратные. Агент, входящий в стадию,
должен иметь загруженный исходный intent -- а не пересказ, прошедший через цепочку агентов.


## 12. Эскалация

Автономная работа прекращается и задача возвращается пользователю когда:

- Scope **2x+** больше первоначальной оценки (план: 3 файла, реальность: 8+)
- **3-й возврат** к той же стадии (обнаружен loop)
- Нужна **новая зависимость**, не предусмотренная планом
- **Несколько архитектурных подходов** без явного winner
- **Конфликт с существующим кодом**, требующий design decision
- Верификация **стабильно проваливается** после 3 циклов Implement -> Quality
- Нужны **доступы или credentials**, которых нет

---

*Подробности каждого компонента -- в соответствующих файлах:*
- *Скиллы:* `plugins/developer-workflow/skills/<name>/SKILL.md`
- *Агенты:* `plugins/developer-workflow/agents/<name>.md`
- *Правила оркестрации:* `~/.claude/rules/dev-workflow-orchestration.md`
