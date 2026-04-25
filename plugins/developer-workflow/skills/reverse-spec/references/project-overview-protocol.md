# Project Overview Protocol

Many feature specs end up duplicating the same project-level information — what the
app is, who it's for, what languages it supports, what core domain entities it
operates on, what authentication / payment / API providers it uses, what the
architectural style is. Without a single shared document, every feature spec must
restate this context, and the redundancy bloats every spec while still failing to
guarantee consistency.

The reverse-spec skill resolves this by **consulting a project-overview document
before drafting any feature spec**. If the overview exists, the feature spec
references it instead of duplicating. If it does not exist, the skill offers to
draft one and waits for user review before proceeding.

This file describes when, where, and how that mechanism runs.

## Where the document lives

Default path: `docs/project-overview.md`.

Alternative paths checked in order if the default does not exist:

- `docs/PROJECT.md`
- `docs/overview.md`
- `PROJECT.md` (repo root)

The first existing file wins. If a project uses a different convention, ask the user
to point at it once; record the path in the spec's state file so subsequent runs find
it without re-asking.

## What the document contains

The project overview is **business-level**, not architectural. It complements (not
replaces) `CLAUDE.md` and similar engineering docs. Recommended sections:

```markdown
# <Project name>

## What this app is
1-2 paragraphs. Purpose. Primary user. Why it exists. What it lets users do that
they could not do otherwise.

## Primary user segments
Who the users are, in business terms. Roles if multi-role.

## Supported languages and regions
Languages the UI is translated into. Regions where the app is distributed. Any
region-specific behavior worth flagging at app level.

## Core domain entities
The 3-7 main entities the app reasons about (e.g., for Frame.io: Asset, Comment,
Review, Workspace, User). One-line definitions. Detailed contracts live in
feature specs that own each entity.

## Identity & authentication provider
The IdP the app uses (Adobe IMS, Auth0, custom). Link to provider docs.

## External services and integrations
The app's standing dependencies on external systems (payment, storage, analytics,
push, etc.). One line per service + link to provider docs.

## Architecture posture
1-2 sentences. Native vs cross-platform. Single-codebase or per-platform.
Online-first, offline-first, hybrid.

## Cross-cutting conventions
Project-wide patterns: error display style, analytics taxonomy doc location,
logging level conventions, accessibility floor, theming approach. One line per
convention.

## Known project-wide constraints
Compliance, regulatory, contractual constraints that bind every feature
(GDPR, PCI, HIPAA, contracted SLA, etc.).

## External documentation references
Authoritative provider docs, standards, RFCs the app collectively depends on.
```

This is a starting structure — adapt to what the project actually has. Aim for
~200-400 lines, not 50 and not 1000.

## When the skill consults the document

In Phase 0.6 (between output-path resolution and static analysis), the skill:

1. Looks for the overview at the default and alternative paths.
2. If found:
   a. Reads it.
   b. Captures relevant excerpts in the state file.
   c. Notes the path so the feature spec can cross-reference instead of duplicate.
3. If not found:
   a. Tells the user — *"Не нашёл project-overview в `docs/project-overview.md` или
      аналогах. Хотел бы предложить набросок (минут на 5 чтения), чтобы фича-спека
      могла на него ссылаться вместо дублирования. Создать?"*
   b. If the user agrees, the skill drafts a project-overview from what it can
      observe in the repo (README, package metadata, top-level config files, source
      layout). The draft is **explicit about confidence** — every claim is sourced
      or marked `[unknown — please fill in]`.
   c. The user reviews and edits.
   d. Once approved, save to `docs/project-overview.md` and proceed.
   e. If the user declines, proceed without overview — the feature spec will
      include some duplicated context. Note the missing overview as `[OQ-N]` in §8.

## What changes in the feature spec when the overview exists

The feature spec gets shorter and more focused. Specifically:

- **§1 Overview** — refers to project-overview's "What this app is" instead of
  restating it. "This feature is the sign-in screen for the Frame.io app (see
  `docs/project-overview.md` §What this app is). Its purpose is..."
- **§4 States, §5 Navigation** — language-agnostic where the project has a stated
  language stance. "Strings follow the project's standard localization
  pattern (see project-overview §Supported languages)."
- **§6 Localization & accessibility** — refers to project conventions; lists only
  feature-specific deviations.
- **§7 Analytics & logging** — refers to project taxonomy doc.
- **§10.5 External services** — links provider docs once at project level; feature
  spec mentions only feature-specific behavior.
- **§10.7 Collaborators** — names project-standard services ("the project's
  standard authenticated HTTP client") and links to overview rather than
  enumerating types.
- **§12.5 External references** — only feature-specific links; project-wide ones
  live in the overview.

## Update discipline

A project-overview is a living document. When this skill runs and sees outdated
content (e.g., the overview says "supported languages: en, ru" but the app added
de), the skill:

1. Flags the discrepancy in the state file.
2. Mentions it once in the handoff: *"Замечено в project-overview.md: <field> может
   быть устаревшим — наблюдаемое в коде <X>, в документе <Y>. Обновлять не стал —
   это вне scope текущей фичи."*

The skill never silently edits the project overview. Updates are user-driven, like
the document's initial creation.

## When to skip Phase 0.6

- The user explicitly says "пропусти project-overview" or "у меня одиночный спек".
- The repo is a single-feature library (no cross-feature context to share).
- The skill is being run for retrospective documentation of a feature in a repo
  that has no plans for additional features.

In all other cases, run Phase 0.6. The overhead is a 30-second file lookup; the
upside is dramatic when 5+ feature specs eventually exist and would have repeated
the same boilerplate five times.
