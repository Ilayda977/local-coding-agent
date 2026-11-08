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
from lca.context import state_messages
from lca.tools import TOOL_NAMES, ToolError, relevant_args, run_tool

# Handwritten JSON schema for one action. Ollama uses it to constrain decoding,
# so the model literally cannot produce an unknown tool name.
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        # maxLength: a rambling thought once used up the token budget and the
        # JSON was cut in half. The grammar now stops it at 200 characters.
        "thought": {"type": "string", "maxLength": 200},
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
    seen_calls: set = field(default_factory=set)
    notes: list = field(default_factory=list)  # controller feedback (compact mode)

    def count(self, status):
        return sum(1 for step in self.steps if step.status == status)


def shorten(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {len(text) - limit} more characters cut; read a smaller range]"


def _already_read(repo, action):
    """A read_file whose lines are all already known counts as a repeat."""
    if action.tool != "read_file":
        return False
    args = action.clean_args()
    if "path" not in args or not args.get("start_line") or not args.get("end_line"):
        return False
    return repo.was_read(args["path"], args["start_line"], args["end_line"])


def start_research(issue, repo):
    """The opening conversation: rules + bug report + repository map."""
    return Research(messages=[
        {"role": "system", "content": prompts.RESEARCH_SYSTEM},
        {"role": "user", "content": prompts.research_task(issue, repo.repo_map())},
    ])


def run_research(issue, repo, llm, settings, on_step=None,
                 research=None, feedback=None, max_steps=None):
    """Let the model explore until it calls finish or runs out of steps.

    Called a second time with ``research`` + ``feedback`` it *continues* the same
    investigation; that is how a rejected diagnosis sends the agent back to read more.
    """
    if research is None:
        research = start_research(issue, repo)
    messages = research.messages
    if feedback:
        messages.append({"role": "user", "content": feedback})
        research.notes.append(feedback)
        research.finished = False
    seen_calls = research.seen_calls
    first = len(research.steps) + 1
    budget = max_steps or settings.max_steps

    for number in range(first, first + budget):
        # Full chat history, or a compact state summary (Phase 5, see context.py).
        if settings.compact_history:
            visible = state_messages(issue, repo, research)
        else:
            visible = messages
        action = llm.chat_json(visible, ACTION_SCHEMA, "research", Action, num_predict=400)
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
                # Keep the finish in the history so the conversation stays coherent.
                messages.append({"role": "assistant", "content": action.model_dump_json()})
                break
            # Guardrail: "finish" without reading code would mean guessing.
            observation, status = ("You have not read any code yet. Use find_symbol/search_code "
                                   "and read_file before finishing."), "refused"
        elif key in seen_calls or _already_read(repo, action):
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
        messages.append({"role": "assistant", "content": json.dumps(
            {"thought": action.thought, "tool": action.tool, "args": action.clean_args()})})
        messages.append({"role": "user", "content": f"Result of {call}:\n{observation}"})

        # Two useless replies in a row: the model has nothing new to look at.
        # Stop cleanly; the diagnosis step will use what was already read.
        if [s.status for s in research.steps[-2:]] == ["repeated"] * 2:
            research.stop_reason = "stuck: repeated the same call"
            break
    else:
        research.stop_reason = f"step budget ({budget}) used up"
    return research
