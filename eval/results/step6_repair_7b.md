# Evaluation: step6_repair_7b

Model: `qwen2.5-coder:7b` | compact_history: True

| issue | retrieval | diagnosis | valid_patch | tests_pass | autonomous | steps | prompt_tokens | seconds | unsafe_or_invalid |
|---|---|---|---|---|---|---|---|---|---|
| easy_01 | ✅ | ❌ | ✅ | ❌ | ❌ | 7 | 13521 | 83.9 | 0 |
| easy_02 | ✅ | ❌ | ✅ | ❌ | ❌ | 5 | 9672 | 178.5 | 0 |
| easy_03 | ✅ | ✅ | ✅ | ✅ | ✅ | 9 | 16514 | 130.1 | 0 |
| easy_04 | ✅ | ✅ | ❌ | ❌ | ❌ | 5 | 8900 | 95.1 | 2 |
| easy_05 | ✅ | ✅ | ✅ | ✅ | ✅ | 5 | 7427 | 81.1 | 0 |
| **total** | 5/5 | 3/5 | 4/5 | 2/5 | 2/5 | avg 6 | avg 11207 | avg 114 | avg 0 |
