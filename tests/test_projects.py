"""Naming and recognising project folders."""
from sdk import projects


def test_slug_is_readable_and_never_empty():
    assert projects.slug("Diabetes Cohort 2026") == "diabetes-cohort-2026"
    assert projects.slug("  ¿Qué? / BMI & risk  ") == "qu-bmi-risk"
    assert projects.slug("") == projects.slug("!!!") == "project"


def test_only_initialised_folders_look_like_projects(tmp_path):
    assert not projects.looks_like_project(str(tmp_path))
    (tmp_path / "project.yml").write_text("dataset_id: x\n")
    assert projects.looks_like_project(str(tmp_path))
    other = tmp_path / "other"
    (other / "generated").mkdir(parents=True)
    (other / "generated" / "data.csv").write_text("a\n1\n")
    assert projects.looks_like_project(str(other))
