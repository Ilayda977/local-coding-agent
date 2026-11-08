import shutil
from pathlib import Path

import pytest

from lca.config import Settings
from lca.llm import LLM
from lca.tools import Repo

TASKFLOW = Path(__file__).resolve().parent.parent / "taskflow"


@pytest.fixture
def settings():
    # Tests must not depend on LCA_* variables of the person running them.
    return Settings(compact_history=False)


@pytest.fixture
def taskflow_copy(tmp_path):
    """A private, clean copy of the sample repo that tests may modify."""
    dest = tmp_path / "taskflow"
    shutil.copytree(TASKFLOW, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dest


@pytest.fixture
def repo(taskflow_copy, settings):
    return Repo(taskflow_copy, max_read_lines=settings.max_read_lines)


def make_llm(settings, replies):
    from tests.fakes import FakeClient
    client = FakeClient(replies)
    return LLM(settings, client=client), client
