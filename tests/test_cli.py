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
