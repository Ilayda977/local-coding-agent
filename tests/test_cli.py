"""The CLI wiring (argument parsing, approval prompt) with a scripted model."""
import json

from lca import cli
from tests.test_patching import scripted, inject_bug


def test_cli_json_report_without_fix(taskflow_copy, settings, monkeypatch, capsys):
    llm, _ = scripted(settings)
    import lca.agent as agent_module
    real_run = agent_module.run
    monkeypatch.setattr(cli.agent, "run", lambda *a, **k: real_run(*a, **{**k, "llm": llm}))
    inject_bug(taskflow_copy)
    code = cli.main(["--repo", str(taskflow_copy), "--json", "Done tasks are overdue"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["status"] == "diagnosed"


def test_cli_does_not_apply_without_a_terminal(taskflow_copy, settings, monkeypatch, capsys):
    llm, _ = scripted(settings)
    real_run = cli.agent.run
    monkeypatch.setattr(cli.agent, "run", lambda *a, **k: real_run(*a, **{**k, "llm": llm}))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    path = inject_bug(taskflow_copy)
    before = path.read_text()
    code = cli.main(["--repo", str(taskflow_copy), "--fix", "Done tasks are overdue"])
    out = capsys.readouterr().out
    assert "NOT applied" in out and code == 1
    assert path.read_text() == before


def test_missing_repo_gives_a_friendly_hint(capsys):
    code = cli.main(["--repo", "eval/workspace/easy_99", "anything"])
    err = capsys.readouterr().err
    assert code == 2
    assert "eval/issues.py prepare easy_99" in err


def test_summary_says_when_the_diff_was_rolled_back(capsys):
    report = {"status": "tests_failed", "files_read": [], "seconds": 1,
              "usage": {"model_calls": 1, "prompt_tokens": 1, "max_prompt_tokens": 1},
              "patch": {"diff": "-a\n+b\n", "rolled_back": True},
              "tests": {"passed": False, "repairs": 2}}
    cli._print_summary(report, color=False)
    assert "ROLLED BACK: files are unchanged" in capsys.readouterr().out
