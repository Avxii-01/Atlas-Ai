# 📝 Git Commit Conventions Guide

To keep the project history readable, searchable, and clean, our team uses a simplified version of the **Conventional Commits** standard. All commits must follow this structure.

---

## 📐 Commit Message Format

Every commit message must follow this exact pattern:

```text
type(scope): description
```

*   **`type`**: The category of the change (e.g., `feat`, `fix`).
*   **`scope`**: The specific project issue number (e.g., `P0-06`) or system component (e.g., `repo`).
*   **`description`**: A concise explanation of the change in lowercase, starting with an imperative verb (e.g., "add", "fix", "update").

---

## 🗂️ Allowed Types

| Type | Meaning |
| :--- | :--- |
| **`feat`** | New application functionality |
| **`fix`** | Bug correction or hotfix |
| **`test`** | Adding or modifying test blocks |
| **`docs`** | Documentation files or inline comment changes |
| **`refactor`** | Code restructuring that changes no external behavior |
| **`chore`** | Build tasks, configuration tweaks, or maintenance |

---

## 🔍 Examples for Atlas AI

Here is how your commit messages should look in production:

*   `feat(P0-06): integrate Tree-sitter Python parser`
*   `fix(P0-16): correct transitive dependency traversal`
*   `test(P0-10): add ambiguous call resolution tests`
*   `docs(P0-07): document unified code model`
*   `refactor(P0-13): simplify graph persistence`
*   `chore(repo): update development configuration`

---

## 🛑 Rules & Best Practices

### ✅ Always Keep Commit Messages:
*   **Short & Punchy:** Limit the first line to 50–60 characters.
*   **Imperative:** Write them like commands (e.g., use "add" instead of "added", "fix" instead of "fixed").
*   **Specific:** Explicitly state what changed.
*   **Contextual:** Ensure the message relates directly to the current issue or file target.

### ❌ Never Use Vague Phrases:
Avoid lazy commits that make it impossible to track down bugs in the history:
*   ⚠️ `updated code`
*   ⚠️ `changes`
*   ⚠️ `final changes`
*   ⚠️ `fixed stuff`
*   ⚠️ `working now`

### 💡 Preferred Approaches:
*   ✔ `feat: add Python Tree-sitter parser`
*   ✔ `test: add malformed source parsing test`
*   ✔ `fix: avoid ambiguous call relationships`
