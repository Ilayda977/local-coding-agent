"""All tunable limits live here, so we never hunt for magic numbers.

Every value can be overridden with an environment variable (LCA_<NAME>),
which is handy for comparing the 3B and 7B models without touching code.
"""
import os
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class Settings:
    # Which model Ollama should run. 7B is our daily driver, 3B the quick baseline.
    model: str = "qwen2.5-coder:7b"
    host: str = "http://127.0.0.1:11434"

    # 8K context is plenty for small observations; the model supports 32K
    # but a bigger window costs memory and speed on a 16 GB machine.
    num_ctx: int = 8192
    temperature: float = 0.0  # same input -> (almost) same answer; helps evaluation

    # Agent loop guardrails. Small numbers on purpose: a lost agent should stop early.
    max_steps: int = 12            # research steps before we force a diagnosis
    max_read_lines: int = 80       # one read_file call never returns more than this
    max_search_results: int = 30
    max_observation_chars: int = 4000
    max_evidence_retries: int = 1  # chances to fix a diagnosis that cites unread code

    # Patch + test loop (Phase 3/4)
    max_changed_lines: int = 40
    max_repairs: int = 2
    test_timeout: int = 60

    # Phase 5: replace old observations with one-line summaries
    compact_history: bool = True
    keep_recent_observations: int = 3

    # A request that runs longer than this is cancelled (seconds)
    request_timeout: int = 180


def _convert(value, current):
    if isinstance(current, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def load_settings(**overrides):
    """Defaults <- environment (LCA_*) <- explicit keyword overrides."""
    settings = Settings()
    from_env = {}
    for field in fields(Settings):
        raw = os.environ.get(f"LCA_{field.name.upper()}")
        if raw is not None:
            from_env[field.name] = _convert(raw, getattr(settings, field.name))
    settings = replace(settings, **from_env)
    return replace(settings, **{k: v for k, v in overrides.items() if v is not None})
