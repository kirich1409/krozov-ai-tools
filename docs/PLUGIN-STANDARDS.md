# Plugin Standards

Обязательные стандарты для всех плагинов в этом монорепо (`plugins/*`). Основаны на официальной документации Claude Code (Anthropic) и накопленном опыте.

Проверка — ручная по чек-листу ниже, автоматическая через `validate.sh` (см. корень репо), и отдельная проверка через `plugin-dev:plugin-validator` agent перед каждым релизом.

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
- Пути с `../` outside plugin root — не работают после установки (cache не копирует внешние файлы). Валидный путь может использовать `..` внутри плагина, если он не выходит за корень, но лучше избегать — см. п. 2.

## 2. Paths

- Пути к компонентам (`skills`, `agents`, `commands`, `hooks` и т.д.) в `plugin.json` **резолвятся относительно `.claude-plugin/` директории**, не от корня плагина. Чтобы указать на `<plugin-root>/skills`, нужно писать `"../skills"`.
- Если директория лежит в корне плагина со стандартным именем (`skills/`, `agents/`, `commands/`, `hooks/`) — поле **можно не указывать вообще**, автодискавер работает. Это предпочтительнее явного `"../skills"`.
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
- [ ] Пути в `plugin.json` не выходят за корень плагина через `..`
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
- Path traversal (`../` outside plugin root) в `plugin.json`
- Существование файлов, на которые ссылаются manifests
