"""CLI tests for the copilot commands."""
import json
import os

import pytest
from typer.testing import CliRunner

from sdk.epsilon_cli import app

runner = CliRunner()


@pytest.fixture
def project(dataset_dir, monkeypatch):
    """An initialised project, with the CWD moved into it."""
    (dataset_dir / "main.py").write_text("def main():\n    return {}\n",
                                         encoding="utf-8")
    monkeypatch.chdir(dataset_dir)
    return dataset_dir


@pytest.fixture
def no_model(monkeypatch):
    from sdk.llm import config as ai_config
    for name in ai_config.ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: None)


class TestExplain:
    def test_renders_the_briefing(self, project, no_model):
        result = runner.invoke(app, ["explain"])
        assert result.exit_code == 0
        assert "GRAIN" in result.output
        assert "NO ENTITY KEY" in result.output

    def test_works_with_no_model_configured(self, project, no_model):
        assert runner.invoke(app, ["explain"]).exit_code == 0

    def test_reports_what_was_measured_not_what_was_declared(self, project, no_model):
        result = runner.invoke(app, ["explain"])
        assert "measured from the local dataset" in result.output

    def test_fails_helpfully_outside_a_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["explain"])
        assert result.exit_code == 1
        assert "epsilon init" in result.output
        assert "data.csv" in result.output


class TestExplainCatalogue:
    def test_explain_lists_what_is_computable(self, project, no_model):
        result = runner.invoke(app, ["explain"])
        assert result.exit_code == 0
        assert "AVAILABLE" in result.output
        assert "NOT AVAILABLE" in result.output

    def test_explain_shows_refusals_with_reasons(self, project, no_model):
        result = runner.invoke(app, ["explain"])
        assert "[NO] Prevalence" in result.output
        assert "why not:" in result.output
        assert "pseudonymised" in result.output

    def test_brief_drops_the_catalogue(self, project, no_model):
        result = runner.invoke(app, ["explain", "--brief"])
        assert result.exit_code == 0
        assert "GRAIN" in result.output
        assert "AVAILABLE" not in result.output


class TestSnippet:
    def test_writes_a_feasible_analysis(self, project, no_model):
        result = runner.invoke(app, ["snippet", "describe"])
        assert result.exit_code == 0
        assert os.path.exists(os.path.join(str(project), "analyses", "describe.py"))

    def test_show_prints_without_writing(self, project, no_model):
        result = runner.invoke(app, ["snippet", "describe", "--show"])
        assert result.exit_code == 0
        assert "def main():" in result.output
        assert not os.path.exists(os.path.join(str(project), "analyses"))

    def test_refuses_a_blocked_analysis_with_the_reason(self, project, no_model):
        result = runner.invoke(app, ["snippet", "prevalence"])
        assert result.exit_code == 1
        assert "not available" in result.output
        assert "per-entity quantity" in result.output

    def test_set_chooses_fields(self, project, no_model):
        result = runner.invoke(app, [
            "snippet", "cross_tab", "--set", "rows=patient.gender",
            "--set", "cols=admissions.type", "--show"])
        assert result.exit_code == 0
        assert "record.patient.gender" in result.output

    def test_set_rejects_a_field_of_the_wrong_kind(self, project, no_model):
        result = runner.invoke(app, [
            "snippet", "cross_tab", "--set", "rows=patient.age"])
        assert result.exit_code == 1
        assert "categorical or coded field" in result.output

    def test_set_requires_name_equals_field(self, project, no_model):
        result = runner.invoke(app, ["snippet", "cross_tab", "--set", "rows"])
        assert result.exit_code == 1
        assert "NAME=FIELD" in result.output

    def test_rejects_an_unknown_analysis(self, project, no_model):
        result = runner.invoke(app, ["snippet", "nonsense"])
        assert result.exit_code == 1
        assert "Available:" in result.output


class TestCheck:
    def test_passes_on_a_clean_project(self, project, no_model):
        result = runner.invoke(app, ["check"])
        assert result.exit_code == 0
        assert "All checks passed" in result.output

    def test_blocks_on_a_released_record(self, project, no_model):
        (project / "bad.py").write_text(
            "from generated.models import create_dataset\n"
            "for record in create_dataset():\n"
            "    print(record)\n", encoding="utf-8")
        result = runner.invoke(app, ["check"])
        assert result.exit_code == 1
        assert "no-record-output" not in result.output  # rule name is internal
        assert "per-record" in result.output

    def test_blocks_on_a_credential(self, project, no_model):
        (project / "conf.py").write_text(
            'KEY = "sk-ant-api03-' + "A" * 40 + '"\n', encoding="utf-8")
        result = runner.invoke(app, ["check"])
        assert result.exit_code == 1
        assert "credential" in result.output

    def test_strict_promotes_warnings(self, project, no_model):
        (project / "requirements.txt").write_text("pandas\n", encoding="utf-8")
        assert runner.invoke(app, ["check"]).exit_code == 0
        assert runner.invoke(app, ["check", "--strict"]).exit_code == 1


class TestBuildGate:
    def test_build_refuses_to_package_a_credential(self, project, monkeypatch):
        (project / "project.yml").write_text(
            "entry_point: main.py\ndataset_id: d\narchetype_id: a\n", encoding="utf-8")
        (project / "leak.py").write_text(
            'KEY = "sk-ant-api03-' + "A" * 40 + '"\n', encoding="utf-8")
        result = runner.invoke(app, ["build"])
        assert result.exit_code == 1
        assert "credential" in result.output

    def test_skip_checks_bypasses_the_gate(self, project, monkeypatch):
        (project / "project.yml").write_text(
            "entry_point: main.py\ndataset_id: d\narchetype_id: a\n", encoding="utf-8")
        (project / "leak.py").write_text(
            'KEY = "sk-ant-api03-' + "A" * 40 + '"\n', encoding="utf-8")
        result = runner.invoke(app, ["build", "--skip-checks"])
        assert "credential" not in result.output


class TestAiCommands:
    @pytest.fixture(autouse=True)
    def isolated_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "home"))

    def test_status_reports_no_key(self, no_model):
        result = runner.invoke(app, ["ai", "status"])
        assert result.exit_code == 0
        assert "not found" in result.output
        assert "work without a model" in result.output

    def test_status_reports_the_key_source(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        result = runner.invoke(app, ["ai", "status"])
        assert "env:ANTHROPIC_API_KEY" in result.output

    def test_status_warns_when_an_env_var_shadows_the_keyring(self, monkeypatch):
        from sdk.llm import config as ai_config
        monkeypatch.setenv("EPSILON_LLM_API_KEY", "ollama")
        monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: "sk-stored")
        result = runner.invoke(app, ["ai", "status"])
        assert "shadowing a key stored in your keyring" in result.output
        assert "unset EPSILON_LLM_API_KEY" in result.output

    def test_status_is_quiet_when_nothing_is_shadowed(self, monkeypatch):
        from sdk.llm import config as ai_config
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
        monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: None)
        result = runner.invoke(app, ["ai", "status"])
        assert "shadowing" not in result.output

    def test_login_rejects_an_unknown_provider(self):
        result = runner.invoke(app, ["ai", "login", "--provider", "mystery"])
        assert result.exit_code == 1
        assert "Provider must be one of" in result.output

    def test_login_rejects_an_unknown_tier(self):
        result = runner.invoke(app, [
            "ai", "login", "--provider", "anthropic", "--model", "m",
            "--tier", "Z"])
        assert result.exit_code == 1
        assert "Tier must be A, B or C" in result.output

    def test_login_writes_settings_but_never_the_key(self, monkeypatch):
        from sdk.llm import config as ai_config
        monkeypatch.setattr(ai_config, "store_key", lambda key: "keyring")
        result = runner.invoke(app, [
            "ai", "login", "--provider", "anthropic",
            "--model", "claude-sonnet-5", "--tier", "A"], input="secret-key\n")
        assert result.exit_code == 0
        with open(ai_config.config_path(), encoding="utf-8") as fh:
            body = fh.read()
        assert "secret-key" not in body

    def test_login_warns_when_no_keyring_exists(self, monkeypatch):
        from sdk.llm import config as ai_config
        monkeypatch.setattr(ai_config, "store_key", lambda key: "unavailable")
        result = runner.invoke(app, [
            "ai", "login", "--provider", "anthropic", "--model", "m",
            "--tier", "A"], input="secret-key\n")
        assert "ANTHROPIC_API_KEY" in result.output


class TestCommandSurface:
    """The copilot adds four commands, not a drawer of overlapping ones."""

    def test_suggest_was_removed(self):
        import typer
        from sdk.epsilon_cli import app
        assert "suggest" not in typer.main.get_command(app).commands

    def test_the_copilot_commands_are_exactly_these(self):
        import typer
        from sdk.epsilon_cli import app
        commands = set(typer.main.get_command(app).commands)
        assert {"explain", "snippet", "check", "chat", "ai"} <= commands

    def test_no_module_imports_the_removed_one(self):
        import pytest as _pytest
        with _pytest.raises(ImportError):
            import sdk.suggest  # noqa: F401
