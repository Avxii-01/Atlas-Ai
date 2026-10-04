┌─────────────────────┐
│  1. GitHub Issue    │
│  Understand scope   │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  2. Create Branch   │
│  feature/P0-XX-*    │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  3. Develop         │
│  Follow architecture │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  4. Test            │
│  Unit + integration │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  5. Push Branch     │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  6. Pull Request    │
│  Link GitHub issue  │
└──────────┬──────────┘
           ↓
┌─────────────────────────────┐
│  7. CI                      │
│  (once CI is configured)    │
│  Tests / lint/build         │
└──────────┬──────────────────┘
           ↓
┌─────────────────────┐
│  8. Code Review     │
│  Another member     |
└──────────┬──────────┘
           ↓
      ┌────┴─────┐
      │          │
   Changes     Approved
      │          │
      └──→───────┘
                 ↓
┌─────────────────────┐
│  9. Merge to main   │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ 10. Close Issue     │
└─────────────────────┘


Document branch naming:
feature/P0-XX-description
fix/P0-XX-description
test/P0-XX-description
docs/P0-XX-description


PR title convention

[P0-XX] Short description

Examples:

[P0-06] Integrate Tree-sitter Python parsing
[P0-09] Implement relationship resolver
[P0-16] Implement dependency traversal
[P0-22] Implement graph visualization

To Make Our GitHub History Readable