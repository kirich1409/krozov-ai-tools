# create-pr — Visual Change Detection Patterns

Referenced from: `plugins/developer-workflow/skills/create-pr/SKILL.md` (§7.3).

Look at changed file paths for:
- Android/Compose: `*Screen.kt`, `*Composable.kt`, `res/layout/`, `res/drawable/`
- Compose Multiplatform: Kotlin UI patterns + `commonMain` UI dirs
- Web: `*.tsx`, `*.jsx`, `*.css`, `*.scss`, `*.html`
- iOS: `*View.swift`, `*Screen.swift`, `Views/`, `Screens/`, `*.xib`, `*.storyboard`
  (plain `*.swift` is too broad — most Swift files are non-UI; match by suffix/dir)

If visual changes detected — include "Screenshots / demo" section and prompt the user (in `--draft` and `--promote` modes) for attachments. `--refresh` preserves existing Screenshots content.
