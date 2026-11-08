# Phase 1/2 navigation repair — pending validation

## Requirements preserved

- LIST first; model chooses search targets and read candidates.
- Repository boundary, read-size limits, evidence IDs and snapshot hashes remain.
- Diagnosis output retains issue_summary, evidence, root_cause, relevant_files, confidence.
- No patch, execution or arbitrary shell capability added to the repository agent.
- No model change, timeout increase or full-repository prompt.
- Acceptance still requires 4/5 correct easy diagnoses, not merely passing mocked tests.

## Responsibilities

- `navigation.py`: short ROUTE/ASSESS instructions, language-independent target validation,
  repeated-search feedback and conservative symbol similarity ranking.
- `tools.py`: filesystem access and actual source matches; similar names are explicitly
  candidates, never assumed equivalent to the requested identifier.
- `protocol.py`: structured decisions and bounded format/action repair.
- `agent.py`: stage transitions and budgets. `interpret` means draft from existing evidence,
  not successful diagnosis; grounding and VERIFY still run.
- `evidence.py`: read source registry and locations. Unchanged by this repair.

## Failure handling

| Failure | Handling |
| --- | --- |
| Filename passed to symbol tool | Reject in protocol; request corrected tool/target |
| Turkish/English literal | Both permitted; no language-word blacklist |
| Symbol casing/near typo | Exact matches first; up to five Python definition suggestions if none |
| Repeated model search | Feedback within bounded gateway retry before tool execution |
| Read code needs interpretation | Model may choose interpret; no forced extra search |
| Required source genuinely missing | Search/read remains available |
| Invalid/unsupported final answer | Existing grounding/VERIFY/recovery remain |

## Limits and honest status

Tests added but not run by the assistant at user request. Run:

`./venv/bin/python -B -m unittest discover -p 'test_*.py'`

Fuzzy matching currently applies to Python definitions, not arbitrary language semantics.
It does not correct every typo or resolve ambiguous names automatically. A model can still
misclassify intent or interpret code incorrectly. In particular, correct Python condition
interpretation must be measured with real-model examples; structured IDs are not a proof
of semantic correctness. Do not mark Phase 2 complete before live evaluation.

## References and design rationale

- Assignment: small decisions, bounded observations, 7B baseline, 4/5 easy diagnosis acceptance.
- ReAct (https://arxiv.org/abs/2210.03629): alternate source actions and reasoning; do not
  confuse an interpretation step with a compulsory new retrieval step.
- RepoCoder (https://arxiv.org/abs/2303.12570): iterative retrieval/generation for repository
  code completion. This is supporting research, not evidence this diagnosis implementation works.
