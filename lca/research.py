"""Phase 1: the agent loop.

    model picks a tool  ->  controller runs it safely  ->  short observation back

The *model* decides where to look. The *controller* (this file) enforces the
rules a small model cannot be trusted with: step budget, no repeated calls,
no finishing before reading anything, and never more text than we can afford.
"""
import json
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel

from lca import prompts
from lca.tools import TOOL_NAMES, ToolError, relevant_args, run_tool

# Handwritten JSON schema for one action. Ollama uses it to constrain decoding,
# so the model literally cannot produce an unknown tool name.
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "tool": {"type": "string", "enum": TOOL_NAMES},
        "args": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "query": {"type": "string"},
                "name": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
        },
    },
    "required": ["thought", "tool", "args"],
}


class ActionArgs(BaseModel):
    path: Optional[str] = None
    query: Optional[str] = None
    name: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None


class Action(BaseModel):
    thought: str = ""
    tool: Literal["list_files", "search_code", "find_symbol", "read_file", "finish"]
    args: ActionArgs = ActionArgs()

    def clean_args(self):
        return relevant_args(self.tool, self.args.model_dump())

    def call_text(self):
        """Human-readable form, e.g. read_file(path='a.py', start_line=1)."""
        parts = [f"{k}={v!r}" for k, v in self.clean_args().items()]
        return f"{self.tool}({', '.join(parts)})"


@dataclass
class Step:
    number: int
    thought: str
    call: str
    observation: str
    status: str  # ok | error | repeated | refused


@dataclass
class Research:
    messages: list
    steps: list = field(default_factory=list)
    finished: bool = False
    stop_reason: str = ""

    def count(self, status):
        return sum(1 for step in self.steps if step.status == status)


def shorten(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {len(text) - limit} more characters cut; read a smaller range]"


def run_research(issue, repo, llm, settings, on_step=None, compactor=None):
    """Let the model explore until it calls finish or runs out of steps."""
    messages = [
        {"role": "system", "content": prompts.RESEARCH_SYSTEM},
        {"role": "user", "content": prompts.research_task(issue, repo.repo_map())},
    ]
    research = Research(messages=messages)
    seen_calls = set()

    for number in range(1, settings.max_steps + 1):
        visible = compactor(messages) if compactor else messages
        action = llm.chat_json(visible, ACTION_SCHEMA, "research", Action, num_predict=256)
        call = action.call_text()
        key = (action.tool, json.dumps(action.clean_args(), sort_keys=True))

        if action.tool == "finish":
            if repo.reads:
                research.finished = True
                research.stop_reason = "model finished"
                step = Step(number, action.thought, call, "", "ok")
                research.steps.append(step)
                if on_step:
                    on_step(step)
                break
            # Guardrail: "finish" without reading code would mean guessing.
            observation, status = ("You have not read any code yet. Use find_symbol/search_code "
                                   "and read_file before finishing."), "refused"
        elif key in seen_calls:
            # Tell the model what to do instead, not only what not to do.
            observation, status = ("You already made this exact call; its result is above. "
                                   "Pick the most promising file:line from earlier results and "
                                   "read it with read_file (about 20 lines around it), "
                                   "or call finish if you already read the cause."), "repeated"
        else:
            seen_calls.add(key)
            try:
                observation, status = run_tool(repo, action.tool, action.clean_args()), "ok"
            except ToolError as error:
                observation, status = f"ERROR: {error}", "error"
        observation = shorten(observation, settings.max_observation_chars)

        step = Step(number, action.thought, call, observation, status)
        research.steps.append(step)
        if on_step:
            on_step(step)
        messages.append({"role": "assistant", "content": action.model_dump_json(exclude_none=True)})
        messages.append({"role": "user", "content": f"Result of {call}:\n{observation}"})

        # Three useless replies in a row means the model is stuck: stop cleanly.
        if [s.status for s in research.steps[-3:]] == ["repeated"] * 3:
            research.stop_reason = "stuck: repeated the same call"
            break
    else:
        research.stop_reason = f"step budget ({settings.max_steps}) used up"
    return research
