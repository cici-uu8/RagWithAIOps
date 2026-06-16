# Synthetic Memory Fixtures

These fixtures validate memory schema and store behavior only.

They are not production oncall evidence, not Gate A.1 pain evidence, and not proof that durable memory is required. They are allowed under Gate A.2 as pre-launch controlled design fixtures.

Every fixture record uses:

- `source = "design-fixture, NOT real session evidence"`
- evidence field `evidence_type = "synthetic_design_fixture"`

Fixture index:

- `p1_memory_records.json`: validates the P1 typed schema and SQLite store.
- `p2_lexical_recall_cases.json`: validates P2 lexical retrieval and synonym handling.
