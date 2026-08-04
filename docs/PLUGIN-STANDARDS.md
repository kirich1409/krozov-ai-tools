# Plugin Standards

Обязательные стандарты для всех плагинов в этом монорепо (`plugins/*`). Основаны на официальной документации Claude Code (Anthropic) и накопленном опыте.

Проверка — ручная по чек-листу ниже, автоматическая через `validate.sh` (см. корень репо), и отдельная проверка через `plugin-dev:plugin-validator` agent перед каждым релизом.

## Non-negotiables convention

Each plugin that has a `CLAUDE.md` should include a `## Non-negotiables` section as its first section. This section lists hard rules specific to that plugin — rules whose violation is always an error, not a judgment call. Format: one bullet per rule, rule + why-one-liner. No trade-off discussion.

Review and validation skills (`code-reviewer`, `finalize`, `multiexpert-review`) treat any violation of a `## Non-negotiables` rule as a blocker (critical severity, confidence 100).

Plugins with no plugin-specific invariants beyond the project root `CLAUDE.md` and global `~/.claude/CLAUDE.md` do not need a `CLAUDE.md` at all.

## References

- [Plugins reference](https://code.claude.com/docs/en/plugins-reference) — schema `plugin.json`, namespacing, caching
- [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) — `marketplace.json`, источники
- [Plugin dependencies](https://code.claude.com/docs/en/plugin-dependencies) — semver ranges, теги (v2.1.110+)
- [Sub-agents](https://code.claude.com/docs/en/sub-agents) — namespace `plugin:agent`, ограничения
- [Skills](https://code.claude.com/docs/en/skills) — SKILL.md, priorities, conflict resolution

## 1. Plugin manifest (`plugin.json`)

Обязательное:

- `name` — kebab-case, уникальный в пределах `marketplace.json`
- `version` — валидный semver (`0.9.0`, `1.0.0`). У каждого плагина своя версия: релиз одного плагина не двигает версии остальных.

Обязательно рекомендуется (для самодостаточности плагина без опоры на marketplace):

- `description` — краткая суть, что плагин делает
- `author` — `{ "name": "<owner>" }`. Должен совпадать с записью в `marketplace.json`.
- `homepage`, `repository`, `license`, `keywords` — по возможности
- `category` — если заявлена в marketplace entry, дублировать

Запрещено:

- `hooks`, `mcpServers`, `permissionMode` **внутри agent frontmatter** — эти поля запрещены в plugin-shipped агентах (security). Допускаются только в проектных агентах.
- **Любые пути с `../`** в `plugin.json` (`skills`, `agents`, `commands`, `hooks`, `mcpServers`, `outputStyles`, `monitors`, `lspServers`) — traversal наружу плагина запрещён схемой Claude Code. Плагин не загрузится: `Plugin has an invalid manifest file … Validation errors: <field>: Invalid input`.
- Пути, **не начинающиеся с `./`** — схема требует explicit relative paths.

## 2. Paths

- Пути к компонентам (`skills`, `agents`, `commands`, `hooks`, `mcpServers`, `outputStyles`, `monitors`, `lspServers`) в `plugin.json` **резолвятся от корня плагина**, не от `.claude-plugin/`. Корректно: `"./skills/"`, `"./agents/"`, `"./custom/tool.md"`.
- **Auto-discovery**: если директория лежит в корне плагина со стандартным именем (`skills/`, `agents/`, `commands/`, `hooks/`, `output-styles/`, `monitors/`) — поле **можно не указывать вообще**. Это дефолтный и предпочтительный путь, убирает лишний источник ошибок.
- **Никаких `../`**: путь не может выходить за корень плагина. Claude Code при установке копирует в cache только содержимое корня плагина (`~/.claude/plugins/cache/...`), `../` ссылается наружу и ломает плагин после установки. Частая ошибка — написать `"../skills"` из уверенности, что пути резолвятся относительно `.claude-plugin/`. Это не так, раньше так было, сейчас — нет.
- В скриптах хуков и в references используй `${CLAUDE_PLUGIN_ROOT}` вместо абсолютных или `dirname $0`. Это кросс-платформенно и стабильно при symlink-резолюции.
- В SKILL.md и агентах ссылайся на `references/` через `${CLAUDE_PLUGIN_ROOT}/agents/references/foo.md`.

## 3. Skills (`SKILL.md`)

Frontmatter:

- `name` — kebab-case, **совпадает с именем директории** (`skills/<name>/SKILL.md`)
- `description` — **≤ 1024 символа** (hard limit Anthropic). Должно описывать «когда использовать» + триггеры + `Do NOT use for:` (best practice), но ёмко. Длинные примеры и таксономии — в тело SKILL.md или в `references/`.
- `description` начинается с глагола или `Use when…`, не с self-reference «This skill should be used when…».

Размер:

- **SKILL.md ≤ 500 строк** (soft-рекомендация Anthropic). Всё, что больше — выноси в `skills/<name>/references/<topic>.md` и ссылайся из SKILL.md. `references/` не грузится в контекст до явного вызова.

Уникальность:

- Имя skill уникально в пределах плагина. Между плагинами может повторяться — namespace `<plugin>:<skill>` разрешает.

## 4. Agents

Frontmatter:

- `name` — kebab-case, совпадает с именем файла (`agents/<name>.md`)
- `description` — конкретные триггеры, примеры в виде `<example>Context: ... user: ... assistant: ...</example>` (best practice)
- `tools` / `disallowedTools` — если agent read-only (ревью, анализ), явно укажи `disallowedTools: Edit, Write, NotebookEdit`
- `model` — опционально (`opus`, `sonnet`, `haiku`). По умолчанию наследуется.
- `memory: project` — для агентов, которые должны иметь persistent memory между сессиями

Запрещено (см. п. 1):

- `hooks`, `mcpServers`, `permissionMode` — не поддерживается в plugin agents

Уникальность:

- Имя агента уникально в пределах плагина. Между плагинами namespace `<plugin>:<agent>` разрешает. Task tool использует namespace для вызова.

## 5. References (shared material)

- Размещай в `agents/references/` или `skills/<name>/references/`
- Путь к reference — через `${CLAUDE_PLUGIN_ROOT}/...`, не через `../`
- References не грузятся в контекст автоматически — загружаются только при явной ссылке из SKILL.md/agent body

## 6. Hooks

- Конфигурация — `hooks/hooks.json`
- Скрипты — `hooks/<name>.sh` (или `.py` / другое), shebang обязателен, executable bit обязателен
- Внутри скрипта используй `${CLAUDE_PLUGIN_ROOT}` для резолюции путей к ресурсам плагина
- Shell скрипты: `set -euo pipefail` в entrypoint, sourced-модули без `set` (наследуется)
- Все файлы `*.sh` в `src/`, `hooks/`, `tests/` должны иметь executable bit (`chmod +x`)

## 7. Cross-plugin dependencies (v2.1.110+)

Если plugin A использует агента или skill из plugin B:

```json
// plugin.json плагина A
{
  "dependencies": [
    { "name": "plugin-b", "version": "^0.9.0" }
  ]
}
```

- Semver ranges: `^`, `~`, exact (`=`), range (`>=1.4.0`)
- Для resolution нужны **git-теги формата `{plugin-name}--v{version}`** в release workflow
- Cross-marketplace deps требуют allowlist в корневом `marketplace.json`
- Версии плагинов независимы, поэтому range берётся от реальной версии плагина-зависимости, а не от версии репо; `^X.Y.0` — разумный дефолт

## 8. Marketplace (`marketplace.json`)

- Один `marketplace.json` на репо (в `.claude-plugin/`)
- Для каждого плагина entry: `name`, `source`, `description`, `version`, `author`, опционально `homepage`, `category`, `keywords`
- `version` в marketplace entry **должна совпадать** с `version` в `plugin.json` того же плагина
- `source: "./plugins/<name>"` — относительный path от корня репо

## 9. Versioning

- **Независимые версии**: у каждого плагина своя версия, релиз одного не бампает остальные
- Bump правила: MAJOR — breaking, MINOR — features/additions, PATCH — fixes
- Tag format: только per-plugin `{plugin-name}--vX.Y.Z`. Он же — триггер релиза, он же — то, через что Claude Code резолвит semver-диапазоны в `dependencies`
- Корневой `vX.Y.Z` больше не выпускает ничего: `release.yml` подписан на `*--v*`, а `legacy-tag-guard.yml` громко валит пуш `v*`. Исторические `v*`-теги остаются как история
- Тег, чьё имя не матчится `^[a-z0-9-]+--v[0-9]+\.[0-9]+\.[0-9]+$` или называет плагин вне `marketplace.json`, — ошибка джоба `gate`
- `CHANGELOG.md` на уровне репо (если нужно — per-plugin)

## 10. Pre-release checklist

Перед каждым релизом (см. `CLAUDE.md`):

- [ ] `bash validate.sh` — зелёный
- [ ] `plugin-dev:plugin-validator` agent на каждом плагине — PASS или только Minor
- [ ] У каждого плагина три его места версии (`plugin.json`, entry в `marketplace.json`, `SERVER_VERSION` в bundled server) — синхронизированы между собой; версии разных плагинов совпадать не обязаны
- [ ] Версия выпускаемого плагина равна версии в теге — `bash scripts/validate.sh --check-tag <plugin>--vX.Y.Z` зелёный. Другие плагины этим релизом не выпускаются и не проверяются
- [ ] Релизный коммит достижим из `main` (иначе `gate` откажет) и **есть в `main`**, а не только в ветке
- [ ] Для плагина с бандлом: джоб `youtube-transcript-mcpb` в `ci.yml` зелёный **на релизном коммите**, а не только на каком-то из коммитов ветки
- [ ] Если `release.yml` менялся с прошлого релиза: до пуша тега прогнан зелёный dry run — `workflow_dispatch` на `release.yml` для выпускаемого плагина (прогоняются `gate` и `pack`; `attest` и `publish` dry run недостижимы by design — см. §12)
- [ ] Нет `.DS_Store`, `*-workspace/` runtime-папок в коммитах
- [ ] Все shell-скрипты executable (`find plugins -name "*.sh" ! -executable`)
- [ ] Описания skills (`description` frontmatter) ≤ 1024 символа
- [ ] SKILL.md ≤ 500 строк или имеет `references/`
- [ ] Никаких `hooks`/`mcpServers`/`permissionMode` внутри agent frontmatter
- [ ] Пути в `plugin.json` начинаются с `./` и не содержат `../` (`skills`, `agents`, `commands`, `hooks`, `mcpServers`, `outputStyles`, `monitors`, `lspServers`). Для стандартных директорий в корне плагина — предпочтительно auto-discovery (поле не указывать)
- [ ] Все referenced файлы существуют

## 11. Что автоматизируется (`validate.sh`)

Автоматически проверяется:

- JSON validity всех `plugin.json` и `marketplace.json`
- Version consistency между `plugin.json` и `marketplace.json`
- Executable bits на `*.sh` в `plugins/*/src`, `plugins/*/hooks`, `plugins/*/tests`
- Frontmatter validity (YAML parses) для всех SKILL.md и agents/*.md
- `description` length ≤ 1024 для skills
- SKILL.md size warning при > 500 строк без `references/`
- Forbidden fields в agent frontmatter (`hooks`, `mcpServers`, `permissionMode`)
- Path traversal (`../`) и invalid prefixes (не `./`) в component-path полях `plugin.json`
- Существование файлов, на которые ссылаются manifests (относительно корня плагина)

## 12. MCPB bundle (`youtube-transcript`)

`.mcpb` — второй канал дистрибуции плагина `youtube-transcript`, устанавливаемый в
десктопное приложение Claude одним кликом, параллельно обычной установке через
marketplace. Шаблон манифеста — `plugins/youtube-transcript/mcpb/manifest.template.json`
(MCPB v0.4, без ключа `version`). Сборка — `scripts/pack-mcpb.sh`: собирает staging-дерево
из git-индекса, инжектирует версию в манифест и зовёт `mcpb pack`. Из индекса берётся не
только список файлов и режим, но и содержимое (`git cat-file blob <oid>`), поэтому
незакоммиченные правки рабочего дерева в бандл не попадают — сборщик печатает о таких
файлах предупреждение в stderr. Проверка собранного бандла — `scripts/smoke-mcpb.sh`
(восемь L3-ассерций); сам смоук-скрипт в свою очередь проверен
`scripts/tests/test-smoke-negatives.sh` (двенадцать кейсов, доказывающих, что каждая
ассерция краснеет на своём негативном примере).

**Разделение ответственности.** Сборщик отвечает за containment — что вообще попадает в
staging (режимы tracked-файлов, запрет не-`.py` под `server/`, symlink-guard шаблона,
финальная проверка staging-дерева); смоук — за контракт уже собранного артефакта. Гейты
сборщика не дублируют смоук и не подлежат выносу в него: кейс «staged symlink» в
`test-smoke-negatives.sh` проверяет именно гейт сборщика, остальные — ассерции смоука.

**Версия — не четвёртое место хранения.** Манифест-шаблон version не содержит;
`pack-mcpb.sh` читает версию из `plugin.json` и инжектирует её при сборке. Non-negotiable
из `CLAUDE.md` («все 3 места хранения версии синхронизированы») остаётся верным без правок
— бандл не добавляет четвёртое.

**npm-тулчейн — только build-time.** `tools/mcpb/package.json` закрепляет
`@anthropic-ai/mcpb@2.1.2` (~56 транзитивных пакетов), ставится через
`npm ci --ignore-scripts`. Ни один из этих пакетов не попадает в сам бандл: staging
перечисляет файлы из git-индекса плагина (`server/`, `LICENSE.md`) и принимает только
обычные файлы с ожидаемым режимом — npm-зависимости туда физически не входят. Рантайм
плагина остаётся stdlib-only, поэтому non-negotiable плагина «No pip dependencies» этим
не затрагивается: правило про Python-рантайм, а не про build-тулинг репозитория.

**Audit-гейт.** CI-джоб `youtube-transcript-mcpb` (`.github/workflows/ci.yml`) гоняет
`npm audit --json` по `tools/mcpb` и фильтрует high/critical находки через `jq`, а не
флагом `--audit-level` — тот меняет только код возврата, а не состав отчёта. Шаг обязан
иметь собственный `set -euo pipefail` и проверку формы отчёта (`has("vulnerabilities")`):
Actions по умолчанию исполняет `run:`-блок как `bash -e` **без** `pipefail`, и без этих
двух строк гейт молча зеленел при недоступном npm-реестре (проверено принудительным
отказом реестра). Принятые исключения живут построчно в `tools/mcpb/audit-allowlist.txt`
как ревьюируемые диффы; при бампе версии CLI allowlist регенерируется реальным прогоном
`npm audit`, а не правится руками.

Гейт **path-gated**: джоб запускается только когда PR трогает пути, перечисленные в шаге
`Detect changes` (`plugins/youtube-transcript/**`, `scripts/pack-mcpb.sh`,
`scripts/smoke-mcpb.sh`, `tools/mcpb/**` и т. д.). При замороженном lockfile это значит:
свежеопубликованное advisory против неизменившихся зависимостей ни один отслеживаемый
путь не трогает и гейт не разбудит. Обнаружение между PR зависит от включённых на уровне
репозитория **Dependabot security alerts** — `dependabot.yml` в этом репозитории настраивает
только version updates (канал регулярных обновлений для `/tools/mcpb`), а не security alerts,
и выразить их не может.

**Бандл воспроизводим побайтно — нормализацией архива, а не флагом сборщика.** Сам `mcpb pack`
детерминизма не даёт: он вшивает в архив mtimes файлов, поэтому две подряд сборки на неизменном
входе давали **разные** SHA-256. `SOURCE_DATE_EPOCH` — де-факто стандартный рычаг воспроизводимых
сборок — CLI **игнорирует**: две сборки под `SOURCE_DATE_EPOCH=1700000000` тоже разошлись
(измерено на `main@9ea164a`, `@anthropic-ai/mcpb@2.1.2`, версия плагина `0.1.0`). Документировать
его как средство нельзя, просить детерминизм у сборщика — тоже; поэтому он делается своими руками
после упаковки.

`scripts/pack-mcpb.sh` шагом 11a прогоняет свежий архив через `scripts/normalize-mcpb.py`
(stdlib-only Python, как и остальной тулинг репозитория) и только затем считает контрольную сумму —
так `.sha256` описывает именно отгружаемые байты. Нормализация переписывает **метаданные архива**,
содержимое файлов копируется как есть:

- записи отсортированы побайтно по имени;
- `date_time` каждой записи = ZIP-эпоха 1980-01-01 00:00:00;
- права: `0644` для файлов, `0755` для directory-записей (те же значения, что уже пишет `mcpb pack`,
  зафиксированы явно — чтобы будущая версия CLI не протащила в артефакт umask билд-машины);
- сжатие: DEFLATE с пинованным уровнем, `create_system` = 3 (Unix);
- запись, у которой выставлены биты типа файла, отличные от regular/directory (например симлинк),
  **отклоняется**, а не переписывается молча в обычный файл — иначе нормализация обошла бы
  containment-гейты `pack-mcpb.sh`.

Свойство держится проверкой, а не обещанием: `scripts/tests/test-mcpb-reproducible.sh` собирает
бандл дважды и требует совпадения и SHA-256, и байтов; в CI это шаг `Bundle is byte-reproducible`
джоба `youtube-transcript-mcpb`. Цена — две полные упаковки (~1 с каждая локально) плюс
обязательная пауза 3 с между ними: DOS-поле даты в zip имеет гранулярность 2 с, и две сборки
подряд попадают в одно и то же «ведро» — проверено, с откаченной нормализацией они совпадали, пока
паузы не было. Суммарно ~5 с против `npm ci`, который джоб платит и так. Отдельный скрипт, а не девятая ассерция `smoke-mcpb.sh`:
смоук проверяет **один переданный ему бандл** (в `release.yml` — ещё и скачанный), а
воспроизводимость доказывается только повторной сборкой, чего пер-бандловый верификатор делать не
должен.

Нормализованный бандл остаётся валидным и устанавливаемым:
`bash scripts/smoke-mcpb.sh --require-checksum <bundle>` печатает
`smoke-mcpb: all 8 assertions passed`, включая живой MCP-хендшейк.

Полный протокол исходного измерения — `swarm-report/mcpb-stage2-t8-reproducibility.md`.

Что гарантируется и что нет. Гарантируется: сборка из одного и того же дерева исходников тем же
тулчейном даёт один и тот же файл, поэтому SHA-256 релизного бандла можно воспроизвести локально и
сверить. Побайтное совпадение на **другой** машине дополнительно требует той же версии `mcpb` CLI
(состав и содержимое `manifest.json`) и совместимой реализации zlib — уровень сжатия пинован, сама
библиотека нет. Чексумма при этом по-прежнему **не** контроль подлинности: `.mcpb` и `.sha256`
публикует один и тот же джоб, и тот, кто может подменить один файл, подменит и второй. Подлинность
даёт build provenance (`actions/attest` в `release.yml`), воспроизводимость даёт возможность
независимо *пересобрать* и сравнить.

**Релизная проводка.** Публикация бандла привязана к `.github/workflows/release.yml`; триггер —
per-plugin тег `<plugin>--v<version>` (см. §9 и раздел Publishing в `CLAUDE.md`/`AGENTS.md`).
Воркфлоу — четыре джоба: `gate` (разбор тега, достижимость коммита из `origin/main`,
`validate.sh --check-tag <tag>` плюс обычный `validate.sh`, тесты всех плагинов на Python 3.9),
`pack` (тулчейн, audit-гейт, сборка бандла, смоук, SHA-256 в output джоба), `attest` (сверка
скачанных байтов с этим output, затем `actions/attest`), `publish` (та же сверка, затем GitHub
Release `<plugin> <version>` с прикреплёнными `.mcpb` и `.mcpb.sha256`).

Опорные свойства, каждое из которых было находкой ревью:

- **`pack`/`attest` условны по наличию `plugins/<plugin>/mcpb/manifest.template.json`.** Плагин без
  бандла получает релиз без ассетов, а не пропущенный релиз. Воркфлоу при этом обобщён, а
  `scripts/pack-mcpb.sh` — нет: он хардкодит пути `youtube-transcript`, и второй бандлящийся плагин
  потребует правки скрипта.
- **Аттестация выпускается до публикации.** Бесполезная аттестация безвредна, непроверяемая
  скачка — нет. Команда проверки для пользователя — в корневом `README.md`; она пиннит путь
  воркфлоу, но не его ref.
- **`workflow_dispatch` — всегда dry run.** Входа `dry_run` нет намеренно: значение `false`
  публиковало бы с произвольной непроверенной ветки, имея `id-token: write` и `contents: write`.
  `attest` и `publish` завязаны на `github.event_name == 'push'`.
- **Следствие, которое нельзя замалчивать:** dry run прогоняет только `gate` и `pack`. Джобы с
  опасными правами (`attest`, `publish`) первый раз исполняются на боевом теге — by design.
  Первый релиз после изменения воркфлоу ведётся под наблюдением.
- **Проверка достижимости коммита из `main` — не граница безопасности.** Для тега исполняется тот
  воркфлоу, который лежит в помеченном коммите. Она ловит ошибку мейнтейнера, а не участника с
  push-доступом.
- **`make_latest: legacy`, не `true`** (§9: версии независимы). «Latest» — один указатель на весь
  репозиторий, и принудительный `true` отдал бы релиз `maven-mcp` тому, кто пришёл за бандлом.

**Восстановление после частичного отказа релиза.** Тег `*--v*` защищён ruleset'ом от удаления и
non-fast-forward обновления и является тем, через что consumer резолвит `dependencies`, поэтому
переставлять его нельзя ни при каком исходе. Штатная починка — новая patch-версия и новый тег.

Что оставляет после себя отказ каждого джоба:

| Упал | Состояние |
|---|---|
| `gate` | ни релиза, ни аттестации, ни ассетов; тег уже опубликован |
| `pack` | `publish` пропущен по `needs.pack.result != 'failure'` — релиза нет |
| `attest` | `publish` пропущен так же — неаттестованный ассет не публикуется |
| `publish` | релиз мог быть создан частично; аттестация уже выпущена |

- **Транзиентный отказ** (сеть, реестр) — «Re-run failed jobs» в том же run; тег трогать не нужно.
  Ограничение: артефакт живёт `retention-days: 14`, после чего перезапускать `attest`/`publish` без
  `pack` нечем. Прогоном это не проверялось.
- **Повторный прогон `publish` поверх уже созданного релиза** — установлено **чтением исходников**
  закреплённой ревизии `softprops/action-gh-release` (`3bb1273`, `src/github.ts`), не прогоном:
  существующий релиз для тега находится и обновляется на месте (не дублируется и не ошибка), а
  одноимённый ассет удаляется и заливается заново, потому что `overwrite_files` в воркфлоу не задан,
  а умолчание — не `false`. На живом релизе этого репозитория поведение ещё не наблюдалось.
- **Плагин без бандла** не падает на `fail_on_unmatched_files: true`: тем же чтением исходников
  установлено, что `parseInputFiles('')` даёт `[]`, а загрузка ассетов идёт под guard'ом
  `length > 0`.

Открытым остаётся одно: что именно выдаёт `generate_release_notes: true`, когда в репозитории
переплетены два пространства тегов, — базис для diff'а не установлен. Смотреть на первом релизе и
заменять явным body, если результат неверен.
