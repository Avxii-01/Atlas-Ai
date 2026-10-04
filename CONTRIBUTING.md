# 🚀 Team Development Workflow & Git Conventions

Welcome to the team! To maintain a clean, readable, and trackable project history on GitHub, everyone must follow this structured development lifecycle and branch naming architecture.

---

## 🗺️ Step-by-Step Development Lifecycle

Below is the required sequence of steps for picking up, developing, and completing any task within the project workspace.

```mermaid
graph TD
    Step1[1. GitHub Issue<br><i>Understand scope</i>] --> Step2[2. Create Branch<br><i>feature/P0-XX-*</i>]
    Step2 --> Step3[3. Develop<br><i>Follow architecture</i>]
    Step3 --> Step4[4. Test<br><i>Unit + integration</i>]
    Step4 --> Step5[5. Push Branch]
    Step5 --> Step6[6. Pull Request<br><i>Link GitHub issue</i>]
    Step6 --> Step7[7. CI Automation<br><i>Tests / lint / build</i>]
    Step7 --> Step8[8. Code Review<br><i>Peer approval required</i>]
    
    Step8 -- Changes Requested --> Step3
    Step8 -- Approved --> Step9[9. Merge to main<br><i>Linear merge</i>]
    Step9 --> Step10[10. Close Issue]

    style Step1 fill:#1f2937,stroke:#3b82f6,stroke-width:2px,color:#fff
    style Step8 fill:#1f2937,stroke:#eab308,stroke-width:2px,color:#fff
    style Step9 fill:#1f2937,stroke:#22c55e,stroke-width:2px,color:#fff
```

---

## 🌿 Branch Naming Architecture

Branches must strictly match their corresponding task types and ticket IDs using the `type/ID-description` format. Always use lowercase letters and hyphens instead of spaces.

*   ✨ **`feature/P0-XX-description`** — Used when implementing a brand new capability, endpoint, or architecture core block.
*   🐛 **`fix/P0-XX-description`** — Used for debugging active issues, fixing broken schemas, or repairing code logic errors.
*   🧪 **`test/P0-XX-description`** — Reserved strictly for setting up testing suites, mock environments, or automated QA tools.
*   📝 **`docs/P0-XX-description`** — Used when updating technical definitions, user architecture readmes, or inline documentation files.

---

## 🔤 Pull Request Title Conventions

To easily trace back features from our production branch history, all Pull Request titles must begin with their bracketed project target identifier code `[P0-XX]` followed by a concise description.

### 💡 Rule Format
```text
[P0-XX] Short description
```

### 🔍 Production History Examples
*   `[P0-06] Integrate Tree-sitter Python parsing`
*   `[P0-09] Implement relationship resolver`
*   `[P0-16] Implement dependency traversal`
*   `[P0-22] Implement graph visualization`
