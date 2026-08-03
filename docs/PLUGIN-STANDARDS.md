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
- `version` — валидный semver (`0.9.0`, `1.0.0`). В монорепо все плагины релизятся одной версией (unified versioning).

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
- При unified versioning в монорепо — рекомендуется `^X.Y.0` (совместимость в рамках одной major-minor серии)

## 8. Marketplace (`marketplace.json`)

- Один `marketplace.json` на репо (в `.claude-plugin/`)
- Для каждого плагина entry: `name`, `source`, `description`, `version`, `author`, опционально `homepage`, `category`, `keywords`
- `version` в marketplace entry **должна совпадать** с `version` в `plugin.json` (unified versioning)
- `source: "./plugins/<name>"` — относительный path от корня репо

## 9. Versioning

- **Unified versioning**: все плагины в репо релизятся одной версией при каждом релизе
- Bump правила: MAJOR — breaking, MINOR — features/additions, PATCH — fixes
- Tag format: корневой `vX.Y.Z` + per-plugin `{plugin-name}--vX.Y.Z` (для semver resolution в `dependencies`)
- `CHANGELOG.md` на уровне репо (если нужно — per-plugin)

## 10. Pre-release checklist

Перед каждым релизом (см. `CLAUDE.md`):

- [ ] `bash validate.sh` — зелёный
- [ ] `plugin-dev:plugin-validator` agent на каждом плагине — PASS или только Minor
- [ ] Версии в `plugin.json` каждого плагина и в `marketplace.json` — синхронизированы
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

## 12. MCPB bundle (`youtube-transcript`, Stage 1)

`.mcpb` — второй канал дистрибуции плагина `youtube-transcript`, устанавливаемый в
десктопное приложение Claude одним кликом, параллельно обычной установке через
marketplace. Шаблон манифеста — `plugins/youtube-transcript/mcpb/manifest.template.json`
(MCPB v0.4, без ключа `version`). Сборка — `scripts/pack-mcpb.sh`: собирает staging-дерево
из git-индекса, инжектирует версию в манифест и зовёт `mcpb pack`. Проверка собранного
бандла — `scripts/smoke-mcpb.sh` (восемь L3-ассерций); сам смоук-скрипт в свою очередь
проверен `scripts/tests/test-smoke-negatives.sh` (девять кейсов, доказывающих, что каждая
ассерция краснеет на своём негативном примере). Сборщик сам ничего не ассертит — вся
проверка живёт в смоуке, это осознанное разделение ответственности.

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

**Бандл не воспроизводим побайтно.** `mcpb pack` вшивает mtimes файлов в архив, поэтому две
сборки одного и того же входа дают разные SHA-256. Любая будущая схема, сверяющая CI-сборку
с релизной, обязана это учитывать (сравнивать содержимое, не хэш архива целиком).

**Границы этапа.** Этот раздел описывает Stage 1 — сборку и CI-проверку бандла. Релизная
проводка (публикация `.mcpb` вместе с релизом, привязка к `release.yml`) вынесена в Stage 2
отдельным планом и здесь не описана; раздел вырастет, когда она появится. Отсутствие пункта
про бандл в чеклисте раздела 10 — то же самое: пункт «bundle job green for the release
commit» гейтил бы путь релиза, которого пока не существует.
