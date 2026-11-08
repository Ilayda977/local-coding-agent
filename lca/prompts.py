"""Every instruction the model reads, in one file.

Keeping prompts together makes it easy to see (and later explain to a mentor)
exactly what the model is told. They are short on purpose: a 7B model follows
five clear rules better than thirty clever ones.
"""
from lca.tools import TOOL_DOCS

RESEARCH_SYSTEM = f"""You are a careful coding agent investigating a bug report in a Python repository.
You cannot see any code until you use a tool. Work in small steps:
1. Locate candidate code with find_symbol or search_code. Search for identifiers
   (function, class or variable names), not for whole sentences.
2. Read the relevant lines with read_file (use the line numbers you found).
   After a search, read the most promising match; do not search the same thing again.
3. When you have READ the lines that explain the bug, call finish.

Rules:
- Exactly one tool per reply. Never repeat a call you already made.
- Never guess what a file contains; read it.
- Keep "thought" to one short sentence (under 20 words).

Tools:
{TOOL_DOCS}

Example of a good investigation (a different repository):
  bug: "Discounts are never applied to orders over 100."
  {{"thought": "Find the discount logic.", "tool": "find_symbol", "args": {{"name": "apply_discount"}}}}
  -> shop/pricing.py:12-20  def apply_discount
  {{"thought": "Read the function.", "tool": "read_file", "args": {{"path": "shop/pricing.py", "start_line": 12, "end_line": 20}}}}
  -> it compares the total with MIN_TOTAL, defined at line 3
  {{"thought": "Check the value it depends on.", "tool": "read_file", "args": {{"path": "shop/pricing.py", "start_line": 1, "end_line": 5}}}}
  -> MIN_TOTAL = 1000, so the threshold is wrong
  {{"thought": "I have read the cause.", "tool": "finish", "args": {{}}}}
Follow the same habit: read the function that implements the reported behaviour,
then read the values, helpers or tables it depends on.

Reply only with JSON: {{"thought": "...", "tool": "<tool name>", "args": {{...}}}}"""


DIAGNOSIS_SYSTEM = """You are a senior Python developer diagnosing a bug report.
You get the bug report and the only code you may rely on: the lines that were read
from the repository, with their real line numbers. Some of this code is correct and
some of it contains the bug. Compare each relevant line with the behaviour the bug
report expects. Check values and conditions carefully: comparison operators, sort
order (ascending vs descending), missing conditions, wrong entries in tables or sets,
and values that are computed but never used.
Use only names that appear in the code shown. Reply only with JSON."""


def diagnosis_task(issue, code_pack):
    return f"Bug report:\n{issue}\n\nCode that was read:\n{code_pack}\n\n{DIAGNOSIS_REQUEST}"


DIAGNOSIS_REQUEST = """Write a diagnosis using ONLY the code above.

- analysis: first, trace the scenario from the bug report through the code, line by
  line, writing down the actual values (e.g. "total=150, MIN_TOTAL=1000, 150 < 1000
  -> no discount"). Say where the actual behaviour differs from the expected one.
- issue_summary: the reported problem in one sentence.
- root_cause: what in the code causes it and why (2-4 sentences). Name the exact
  function and the faulty condition/value. Do not invent names.
- relevant_files: files involved.
- evidence: the exact line ranges (as numbered in the read_file results) that show
  the cause. Point at the line that holds the WRONG value or condition (for example
  the table entry, the comparison or the missing check), not only at the code that
  uses it. Keep each range small (1-10 lines).
- confidence: low, medium or high.

Reply only with JSON."""


def diagnosis_feedback(problems):
    lines = "\n".join(f"- {p}" for p in problems)
    return ("Your diagnosis was rejected by the controller:\n" + lines +
            "\nIf you need to see more code, use the tools now (read_file etc.); "
            "otherwise call finish and write a corrected diagnosis.")


def research_task(issue, repo_map):
    # A repo map (files + the names they define) costs a few hundred tokens and
    # lets the model jump straight to the right function instead of guessing.
    return (f"Bug report:\n{issue}\n\n"
            f"Repository map (file: functions/classes defined there):\n{repo_map}\n\n"
            "Start by locating the code involved in this bug.")
