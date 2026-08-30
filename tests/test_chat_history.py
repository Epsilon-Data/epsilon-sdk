"""Per-project session history: the database, the identity, the resume."""
import os
import sqlite3

import pytest

from sdk import chat_history as h


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    real = os.path.expanduser

    def fake(path):
        if path == "~" or path.startswith("~/"):
            return str(home) + path[1:]
        return real(path)

    monkeypatch.setattr(os.path, "expanduser", fake)
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)


class TestSchema:
    def test_creates_every_table_the_layer_touches(self):
        path = h.ensure_schema()
        tables = {r[0] for r in sqlite3.connect(path).execute(
            "select name from sqlite_master where type='table'")}
        assert {"users", "threads", "steps", "elements", "feedbacks"} <= tables

    def test_is_idempotent(self):
        h.ensure_schema()
        h.ensure_schema()

    def test_lives_in_the_sdk_directory_not_the_project(self):
        assert os.path.join(".epsilon_sdk", "chat.db") in h.ensure_schema()

    def test_steps_carry_every_column_chainlit_may_insert(self):
        """A missing column fails at insert time, silently killing history."""
        path = h.ensure_schema()
        cols = {r[1] for r in sqlite3.connect(path).execute(
            "pragma table_info(steps)")}
        for needed in ("threadId", "showInput", "defaultOpen", "generation",
                       "command", "streaming", "waitForAnswer"):
            assert needed in cols, needed


class TestSecret:
    def test_created_once_and_stable(self):
        first = h.ensure_secret()
        os.environ.pop("CHAINLIT_AUTH_SECRET", None)
        assert h.ensure_secret() == first

    def test_kept_private(self):
        h.ensure_secret()
        path = os.path.join(os.path.expanduser("~"), ".epsilon_sdk",
                            "chainlit_secret")
        assert os.stat(path).st_mode & 0o077 == 0

    def test_lands_in_the_environment_for_chainlit(self):
        secret = h.ensure_secret()
        assert os.environ["CHAINLIT_AUTH_SECRET"] == secret

    def test_an_explicit_environment_secret_wins(self, monkeypatch):
        monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "operator-chosen")
        assert h.ensure_secret() == "operator-chosen"


class TestIdentity:
    """The 'user' is the project; that is what scopes the sidebar."""

    def test_round_trips(self):
        ident = h.identity_for("diabetes-risk-factors")
        assert h.project_from_identity(ident) == "diabetes-risk-factors"

    def test_no_project_means_the_local_user(self):
        assert h.identity_for("") == h.LOCAL_USER
        assert h.project_from_identity(h.LOCAL_USER) == ""

    def test_reads_the_cookie_the_pages_leave(self):
        header = "other=1; epsilon_project=diabetes-risk-factors; theme=dark"
        assert h.project_from_cookie(header) == "diabetes-risk-factors"

    def test_no_cookie_reads_as_no_project(self):
        assert h.project_from_cookie("") == ""
        assert h.project_from_cookie("theme=dark") == ""


class TestResumeContext:
    THREAD = {"steps": [
        {"type": "user_message", "output": "What can I compute?"},
        {"type": "tool", "name": "list_analyses", "output": "..."},
        {"type": "assistant_message", "output": "Three analyses are open."},
        {"type": "user_message", "output": ""},
    ]}

    def test_keeps_what_was_said_and_drops_tool_chatter(self):
        pairs = h.resume_context(self.THREAD)
        assert pairs == [("user", "What can I compute?"),
                        ("assistant", "Three analyses are open.")]

    def test_caps_the_message_count(self):
        thread = {"steps": [
            {"type": "user_message", "output": "m{0}".format(i)}
            for i in range(50)]}
        pairs = h.resume_context(thread, limit=5)
        assert len(pairs) == 5
        assert pairs[-1] == ("user", "m49")

    def test_caps_each_message_length(self):
        thread = {"steps": [{"type": "user_message", "output": "x" * 9000}]}
        (role, text), = h.resume_context(thread, chars=100)
        assert len(text) == 100

    def test_an_empty_thread_yields_nothing(self):
        assert h.resume_context({}) == []
        assert h.resume_context({"steps": []}) == []
