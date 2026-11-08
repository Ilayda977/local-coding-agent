# Evaluation: step5_patch_7b

Model: `qwen2.5-coder:7b` | compact_history: True

| issue | retrieval | diagnosis | valid_patch | tests_pass | autonomous | steps | prompt_tokens | seconds | unsafe_or_invalid |
|---|---|---|---|---|---|---|---|---|---|
| easy_01 | ✅ | ❌ | ✅ | ❌ | ❌ | 7 | 11828 | 91.4 | 0 |
| easy_02 | ✅ | ❌ | ✅ | ❌ | ❌ | 5 | 8054 | 99.4 | 0 |
| easy_03 | ✅ | ✅ | ✅ | ✅ | ✅ | 9 | 16514 | 119.3 | 0 |
| easy_04 | ✅ | ✅ | ✅ | ❌ | ❌ | 5 | 8166 | 88.4 | 0 |
| easy_05 | ✅ | ✅ | ✅ | ✅ | ✅ | 5 | 7427 | 82.7 | 0 |
| **total** | 5/5 | 3/5 | 5/5 | 2/5 | 2/5 | avg 6 | avg 10398 | avg 96 | avg 0 |
