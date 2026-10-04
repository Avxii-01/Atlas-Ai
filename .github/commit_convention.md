Recommended Conventional Commits Keep It Simple

Your format:
type(scope): description

For Atlas AI:
feat(P0-06): integrate Tree-sitter Python parser
fix(P0-16): correct transitive dependency traversal
test(P0-10): add ambiguous call resolution tests
docs(P0-07): document unified code model
refactor(P0-13): simplify graph persistence
chore(repo): update development configuration

Types

Type	Meaning
feat	New functionality
fix	Bug fix
test	Tests
docs	Documentation
refactor	Code restructuring without behavior change
chore	Maintenance/configuration


Rules
Keep commit messages:
- short
- imperative
- specific
- related to the current work

Avoid:
updated code
changes
final changes
fixed stuff
working now

Prefer:
feat: add Python Tree-sitter parser
test: add malformed source parsing test
fix: avoid ambiguous call relationships