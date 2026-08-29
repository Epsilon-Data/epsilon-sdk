"""The registry of projects on this machine."""
import json
import os

import pytest

from sdk import projects


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    real = os.path.expanduser

    def fake(path):
        if path == "~" or path.startswith("~/"):
            return str(home) + path[1:]
        return real(path)

    monkeypatch.setattr(os.path, "expanduser", fake)
    return home


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


class TestAdd:
    def test_registers_a_directory(self, folder):
        p = projects.add("Diabetes cohort", folder, "Risk factors")
        assert p.name == "Diabetes cohort"
        assert p.description == "Risk factors"
        assert p.path == os.path.abspath(folder)
        assert projects.get(p.id) is not None

    def test_derives_a_readable_id(self, folder):
        assert projects.add("Diabetes Cohort 2026", folder).id == "diabetes-cohort-2026"

    def test_makes_ids_unique(self, tmp_path, folder):
        second = tmp_path / "other"
        second.mkdir()
        a = projects.add("Cohort", folder)
        b = projects.add("Cohort", str(second))
        assert a.id != b.id
        assert b.id == "cohort-2"

    def test_rejects_a_path_that_is_not_a_directory(self, tmp_path):
        with pytest.raises(projects.ProjectError):
            projects.add("Missing", str(tmp_path / "nope"))

    def test_rejects_a_directory_already_registered(self, folder):
        projects.add("First", folder)
        with pytest.raises(projects.ProjectError) as exc:
            projects.add("Second", folder)
        assert "already registered as 'First'" in str(exc.value)

    def test_expands_a_home_relative_path(self, isolated_home):
        (isolated_home / "cohort").mkdir(parents=True)
        p = projects.add("Cohort", "~/cohort")
        assert os.path.isabs(p.path)
        assert "~" not in p.path

    def test_stores_the_registry_under_the_sdk_directory(self, folder):
        projects.add("Cohort", folder)
        assert projects.registry_path().endswith(
            os.path.join(".epsilon_sdk", "projects.json"))
        assert os.path.exists(projects.registry_path())


class TestState:
    def test_knows_a_missing_directory(self, folder):
        p = projects.add("Cohort", folder)
        assert p.exists
        os.rmdir(folder)
        assert not projects.get(p.id).exists

    def test_knows_whether_init_has_run(self, folder):
        p = projects.add("Cohort", folder)
        assert not p.initialised
        os.makedirs(os.path.join(folder, "generated"))
        open(os.path.join(folder, "generated", "data.csv"), "w").close()
        assert projects.get(p.id).initialised


class TestListing:
    def test_recent_leads_with_the_last_opened(self, tmp_path):
        for name in ("one", "two"):
            (tmp_path / name).mkdir()
            projects.add(name, str(tmp_path / name))
        projects.touch("one")
        assert projects.recent()[0].id == "one"

    def test_by_path_finds_a_registered_directory(self, folder):
        projects.add("Cohort", folder)
        assert projects.by_path(folder).name == "Cohort"

    def test_by_path_returns_none_for_a_stranger(self, tmp_path):
        assert projects.by_path(str(tmp_path)) is None


class TestRemove:
    def test_forgets_the_project_but_keeps_the_files(self, folder):
        p = projects.add("Cohort", folder)
        assert projects.remove(p.id) is True
        assert projects.get(p.id) is None
        assert os.path.isdir(folder)

    def test_reports_an_unknown_project(self):
        assert projects.remove("ghost") is False


class TestDurability:
    def test_a_corrupt_registry_does_not_stop_the_researcher(self, folder):
        projects.add("Cohort", folder)
        with open(projects.registry_path(), "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        assert projects.load() == []
        assert projects.add("Recovered", folder).name == "Recovered"

    def test_survives_a_round_trip(self, folder):
        projects.add("Diabetes cohort", folder, "Risk factors in adults")
        with open(projects.registry_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
        assert raw["version"] == projects.REGISTRY_VERSION
        loaded = projects.load()[0]
        assert loaded.description == "Risk factors in adults"

    def test_the_registry_directory_is_private(self, folder):
        projects.add("Cohort", folder)
        mode = os.stat(os.path.dirname(projects.registry_path())).st_mode
        assert mode & 0o077 == 0


class TestRefusals:
    """An empty field must not quietly become the working directory."""

    def test_an_empty_path_is_refused(self):
        with pytest.raises(projects.ProjectError) as exc:
            projects.add("Cohort", "")
        assert "needs a folder" in str(exc.value)

    def test_a_whitespace_path_is_refused(self):
        with pytest.raises(projects.ProjectError):
            projects.add("Cohort", "   ")

    def test_an_empty_name_is_refused(self, folder):
        with pytest.raises(projects.ProjectError) as exc:
            projects.add("  ", folder)
        assert "needs a name" in str(exc.value)

    def test_a_padded_path_still_registers(self, folder):
        assert projects.add("Cohort", "  " + folder + "  ").path == \
            os.path.abspath(folder)


class TestEnsure:
    """Starting the workspace inside a project registers it, without a form."""

    def test_registers_an_initialised_directory(self, folder):
        os.makedirs(os.path.join(folder, "generated"))
        open(os.path.join(folder, "generated", "data.csv"), "w").close()
        project = projects.ensure(folder, "DiaBD Diabetes Risk")
        assert project is not None
        assert project.name == "DiaBD Diabetes Risk"

    def test_registers_a_directory_with_a_project_file(self, folder):
        open(os.path.join(folder, "project.yml"), "w").close()
        assert projects.ensure(folder) is not None

    def test_names_it_after_the_folder_when_nothing_better_is_known(self, folder):
        open(os.path.join(folder, "project.yml"), "w").close()
        assert projects.ensure(folder).name == os.path.basename(folder)

    def test_ignores_a_directory_that_is_not_a_project(self, folder):
        assert projects.ensure(folder) is None
        assert projects.load() == []

    def test_returns_the_existing_entry_rather_than_a_second_one(self, folder):
        open(os.path.join(folder, "project.yml"), "w").close()
        first = projects.ensure(folder, "First")
        again = projects.ensure(folder, "Second")
        assert again.id == first.id
        assert len(projects.load()) == 1

    def test_an_already_registered_directory_is_returned_as_is(self, folder):
        added = projects.add("Cohort", folder)
        assert projects.ensure(folder, "Other").id == added.id

    def test_looks_like_project_is_what_decides(self, folder):
        assert projects.looks_like_project(folder) is False
        open(os.path.join(folder, "project.yml"), "w").close()
        assert projects.looks_like_project(folder) is True
