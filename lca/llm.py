"""The only place that talks to Ollama.

Why JSON schemas instead of Ollama's native tool calling?
We tried native tool calling first: qwen2.5-coder:7b wrote the call as plain
text in ``content`` and left ``tool_calls`` empty. Ollama's *structured
outputs* (``format=<JSON schema>``) are more reliable: the model is forced
to produce JSON of the given shape. We still validate every reply with
Pydantic and allow one retry with the error message, because "the model
broke the format" is one of the expected problems in the assignment.
"""
import json
import time
from dataclasses import asdict, dataclass

import ollama
from pydantic import ValidationError


class LLMError(RuntimeError):
    """The model could not produce a valid answer (even after a retry)."""


@dataclass
class CallRecord:
    """What one model call cost us. Phase 5 is all about these numbers."""
    stage: str
    prompt_chars: int
    prompt_tokens: int
    output_tokens: int
    seconds: float
    ok: bool


class LLM:
    def __init__(self, settings, client=None, on_token=None):
        self.settings = settings
        self.client = client or ollama.Client(host=settings.host, timeout=settings.request_timeout)
        self.on_token = on_token  # called with every streamed piece of text (CLI shows it live)
        self.calls = []

    # ------------------------------------------------------------------
    def warm_up(self):
        """Load the model into memory once, so the first real call is not unfairly slow."""
        self.client.chat(model=self.settings.model, messages=[{"role": "user", "content": "hi"}],
                         options={"num_predict": 1, "num_ctx": self.settings.num_ctx})

    def chat_json(self, messages, schema, stage, model_cls, num_predict=512):
        """Ask for JSON matching ``schema`` and return it parsed into ``model_cls``."""
        attempt_messages = list(messages)
        last_error = None
        for _attempt in range(2):
            content = self._call(attempt_messages, schema, stage, num_predict)
            try:
                return model_cls.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = error
                self.calls[-1].ok = False
                # Show the model its own mistake once; small models often fix it.
                attempt_messages = attempt_messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content":
                        f"That reply was invalid: {_short_error(error)}. "
                        "Reply again with JSON that matches the schema exactly."},
                ]
        raise LLMError(f"{stage}: model reply was not valid JSON for the schema ({_short_error(last_error)})")

    # ------------------------------------------------------------------
    def _call(self, messages, schema, stage, num_predict):
        started = time.monotonic()
        prompt_chars = sum(len(m["content"]) for m in messages)
        pieces, prompt_tokens, output_tokens = [], 0, 0
        try:
            # stream=True: tokens arrive as they are generated, so the user never
            # stares at a frozen terminal (one of the assignment's UX rules).
            stream = self.client.chat(
                model=self.settings.model, messages=messages, format=schema, stream=True,
                options={"temperature": self.settings.temperature,
                         "num_ctx": self.settings.num_ctx, "num_predict": num_predict},
            )
            for chunk in stream:
                text = chunk.message.content or ""
                if text:
                    pieces.append(text)
                    if self.on_token:
                        self.on_token(text)
                if getattr(chunk, "done", False):
                    prompt_tokens = chunk.prompt_eval_count or 0
                    output_tokens = chunk.eval_count or 0
        except (ollama.ResponseError, ConnectionError, OSError) as error:
            raise LLMError(f"could not reach the model '{self.settings.model}': {error}") from error
        self.calls.append(CallRecord(stage, prompt_chars, prompt_tokens, output_tokens,
                                     round(time.monotonic() - started, 2), ok=True))
        return "".join(pieces)

    def usage(self):
        """Totals for the run report."""
        return {
            "model_calls": len(self.calls),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "output_tokens": sum(c.output_tokens for c in self.calls),
            "max_prompt_tokens": max((c.prompt_tokens for c in self.calls), default=0),
            "seconds": round(sum(c.seconds for c in self.calls), 1),
            "invalid_replies": sum(1 for c in self.calls if not c.ok),
            "calls": [asdict(c) for c in self.calls],
        }


def _short_error(error):
    text = str(error).replace("\n", " ")
    return text[:300]
