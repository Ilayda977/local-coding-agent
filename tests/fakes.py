"""A scripted stand-in for Ollama so the controller can be tested without a model.

Each test lists the exact replies the "model" will give, in order.
That lets us test the *controller's* behaviour (limits, validation, safety)
deterministically, which a real model never is.
"""
import json
from types import SimpleNamespace


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []  # every message list we were sent, for assertions

    def chat(self, model, messages, format=None, stream=False, options=None):
        self.requests.append({"messages": [dict(m) for m in messages], "format": format})
        if not self.replies:
            raise AssertionError("the fake model ran out of scripted replies")
        reply = self.replies.pop(0)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        # Stream in two pieces, like Ollama does (many small chunks + a final one).
        middle = len(text) // 2
        return iter([
            SimpleNamespace(message=SimpleNamespace(content=text[:middle]), done=False),
            SimpleNamespace(message=SimpleNamespace(content=text[middle:]), done=True,
                            prompt_eval_count=sum(len(m["content"]) for m in messages) // 4,
                            eval_count=len(text) // 4),
        ])


def act(tool, thought="", **args):
    """Shortcut for a scripted research action."""
    return {"thought": thought or f"use {tool}", "tool": tool, "args": args}
