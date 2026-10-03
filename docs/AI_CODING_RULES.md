Rule 1 — AI never decides architecture
The team decides:
- schema
- API design
- module boundaries
- database structure
- algorithms
- dependencies
AI can implement them.
Rule 2 — Every AI-generated feature needs documentation
For every significant feature:
What?
Why?
How?
Inputs?
Outputs?
Dependencies?
Trade-offs?
Known limitations?

Rule 3 — No giant prompts
Don't tell Antigravity:
"Build the entire Atlas backend."

Instead:
"Implement repository scanner that recursively identifies .py files and returns normalized file metadata. Do not modify other modules."

Then review.
Rule 4 — Small commits
Prefer:
feat(parser): add python file scanner

feat(parser): extract function definitions

feat(graph): add File nodes

feat(graph): add CONTAINS relationships

over:
feat: implement atlas

Rule 5 — Every important algorithm gets a human-readable explanation
Especially:
- graph construction
- CALLS extraction
- embeddings
- retrieval
- impact analysis
- risk score
If your professor asks:
"Why did you use BFS?"

you need to answer without asking Antigravity.
Rule 6 — Tests are mandatory
AI-generated code should actually be tested.
At minimum:
Unit tests
Integration tests
Parser fixtures
Graph tests
API tests

Rule 7 — No dependency without justification
If Antigravity says:
"Install this package."

Ask:
Why?

Don't accumulate 70 packages.