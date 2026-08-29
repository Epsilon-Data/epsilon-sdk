"""The open project, its cards, and the handoff into a session."""
import os
import time

import pytest

from sdk import projects as registry
from sdk import workspace as ws
from sdk.profile import profile_project


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
def no_model(monkeypatch):
    """Nothing reaches a real provider from these tests."""
    def refuse():
        raise RuntimeError("no model")
    monkeypatch.setattr("sdk.llm.get_provider", refuse)


@pytest.fixture
def space(dataset_dir, no_model):
    return ws.Workspace(str(dataset_dir), profile_project(str(dataset_dir)))


class TestOpening:
    def test_starts_on_the_given_directory(self, space, dataset_dir):
        assert space.ready
        assert space.project_dir == os.path.abspath(str(dataset_dir))

    def test_recognises_a_registered_directory(self, dataset_dir, no_model):
        registry.add("Cohort", str(dataset_dir))
        assert ws.Workspace(str(dataset_dir)).project.name == "Cohort"

    def test_open_switches_and_measures(self, dataset_dir, tmp_path, no_model):
        other = tmp_path / "empty"
        other.mkdir()
        registry.add("Measured", str(dataset_dir))
        registry.add("Empty", str(other))

        space = ws.Workspace(str(other))
        assert not space.ready
        assert space.open("measured").name == "Measured"
        assert space.ready

    def test_open_an_uninitialised_project_leaves_it_unready(self, tmp_path, no_model):
        folder = tmp_path / "fresh"
        folder.mkdir()
        registry.add("Fresh", str(folder))
        space = ws.Workspace(str(folder))
        assert space.open("fresh") is not None
        assert not space.ready

    def test_open_an_unknown_project_changes_nothing(self, space):
        before = space.project_dir
        assert space.open("ghost") is None
        assert space.project_dir == before

    def test_open_records_that_it_was_opened(self, dataset_dir, no_model):
        registry.add("Cohort", str(dataset_dir))
        opened_before = registry.get("cohort").opened
        time.sleep(1.05)
        ws.Workspace(".").open("cohort")
        assert registry.get("cohort").opened != opened_before

    def test_reopen_picks_up_a_project_initialised_meanwhile(self, tmp_path,
                                                              dataset_dir, no_model):
        import shutil
        folder = tmp_path / "later"
        space = ws.Workspace(str(tmp_path / "later"))
        shutil.copytree(str(dataset_dir), str(folder))
        assert not space.ready       # measured before init had run
        space.reopen()
        assert space.ready


class TestCards:
    def test_offers_only_feasible_analyses(self, space):
        from sdk import catalogue
        feasible = set(m.key for m in catalogue.evaluate(space.profile)
                       if m.feasible)
        cards = space.cards()
        assert cards
        assert all(c.analysis in feasible for c in cards)

    def test_measures_once_and_remembers(self, space, monkeypatch):
        calls = []
        real = ws.suggest_mod.propose

        def counted(profile, provider, *a, **kw):
            calls.append(1)
            return real(profile, None)

        monkeypatch.setattr(ws.suggest_mod, "propose", counted)
        space.cards()
        space.cards()
        assert len(calls) == 1

    def test_refresh_asks_again(self, space, monkeypatch):
        calls = []
        monkeypatch.setattr(ws.suggest_mod, "propose",
                            lambda p, prov, *a, **kw: calls.append(1) or [])
        space.cards()
        space.cards(refresh=True)
        assert len(calls) == 2

    def test_no_cards_before_a_project_is_measured(self, tmp_path, no_model):
        folder = tmp_path / "empty"
        folder.mkdir()
        assert ws.Workspace(str(folder)).cards() == []

    def test_switching_project_forgets_the_old_cards(self, space, dataset_dir, no_model):
        registry.add("Cohort", str(dataset_dir))
        space.cards()
        space.open("cohort")
        assert space._suggestions is None


class TestSeeds:
    def _card(self, space, i=0):
        """A card as the page would send it back."""
        return space.fallback_cards()[i].to_json()

    def test_a_card_becomes_a_seed(self, space):
        seed = space.hand_off(self._card(space))
        assert seed is not None
        assert seed.question
        assert seed.project_dir == space.project_dir

    def test_the_brief_names_the_analysis_to_start_from(self, space):
        seed = space.hand_off(self._card(space))
        assert seed.question in seed.brief()
        assert seed.analysis in seed.brief()

    def test_a_free_question_becomes_a_seed_with_no_analysis(self, space):
        seed = space.ask_seed("What is the age distribution?")
        assert seed.analysis == ""
        assert seed.brief() == "What is the age distribution?"

    def test_a_blocked_card_hands_off_nothing(self, space):
        """A forged or stale card is re-checked against the catalogue."""
        assert space.hand_off({"title": "Prevalence", "question": "q",
                               "analysis": "prevalence", "fields": {}}) is None

    def test_garbage_hands_off_nothing(self, space):
        assert space.hand_off(None) is None
        assert space.hand_off({}) is None
        assert space.hand_off("card") is None

    def test_a_seed_is_claimed_by_token(self, space):
        seed = space.hand_off(self._card(space))
        claimed = ws.take_seed(seed.token)
        assert claimed is not None
        assert claimed.title == seed.title

    def test_a_seed_is_claimed_only_once(self, space):
        seed = space.hand_off(self._card(space))
        assert ws.take_seed(seed.token) is not None
        assert ws.take_seed(seed.token) is None

    def test_the_newest_seed_is_claimed_when_the_token_is_lost(self, space):
        space.hand_off(self._card(space, 0))
        second = space.hand_off(self._card(space, 1))
        claimed = ws.take_seed()
        assert claimed is not None
        assert claimed.token == second.token

    def test_an_unknown_token_claims_nothing(self, space):
        space.hand_off(self._card(space))
        assert ws.take_seed("not-a-token") is None

    def test_a_stale_seed_is_not_claimed(self, space, monkeypatch):
        space.hand_off(self._card(space))
        later = time.time() + ws.SEED_TTL + 10
        monkeypatch.setattr(ws.time, "time", lambda: later)
        assert ws.take_seed() is None

    def test_no_seeds_at_all_claims_nothing(self):
        assert ws.take_seed() is None

    def test_seeds_are_kept_privately(self, space):
        space.hand_off(self._card(space))
        assert os.stat(ws.seed_dir()).st_mode & 0o077 == 0


class TestReferrer:
    """The token survives the trip through the page URL, or it does not."""

    def test_reads_the_token_from_the_page_url(self):
        assert ws.token_from_referrer(
            "http://127.0.0.1:7878/chat?seed=cohort-123-1") == "cohort-123-1"

    def test_reads_it_beside_other_parameters(self):
        assert ws.token_from_referrer(
            "http://x/chat?tab=2&seed=abc&z=1") == "abc"

    def test_a_trimmed_referrer_yields_nothing(self):
        assert ws.token_from_referrer("http://127.0.0.1:7878/chat") == ""
        assert ws.token_from_referrer("") == ""

    def test_an_unrelated_url_yields_nothing(self):
        assert ws.token_from_referrer("https://example.com/?q=seedling") == ""


class TestAutoRegister:
    def test_registering_is_opt_in(self, dataset_dir, no_model):
        ws.Workspace(str(dataset_dir))
        assert registry.load() == []

    def test_starting_inside_a_project_registers_it(self, dataset_dir, no_model):
        space = ws.Workspace(str(dataset_dir), profile_project(str(dataset_dir)),
                             register=True)
        assert space.project is not None
        assert space.project.name == space.profile.title

    def test_starting_somewhere_else_registers_nothing(self, tmp_path, no_model):
        folder = tmp_path / "elsewhere"
        folder.mkdir()
        space = ws.Workspace(str(folder), register=True)
        assert space.project is None
        assert registry.load() == []

    def test_starting_twice_does_not_duplicate(self, dataset_dir, no_model):
        profile = profile_project(str(dataset_dir))
        ws.Workspace(str(dataset_dir), profile, register=True)
        ws.Workspace(str(dataset_dir), profile, register=True)
        assert len(registry.load()) == 1


class TestChatSession:
    def test_no_model_means_no_session(self, space):
        assert space.chat() is None

    def test_a_preset_session_is_kept(self, dataset_dir, no_model):
        marker = object()
        space = ws.Workspace(str(dataset_dir), profile_project(str(dataset_dir)),
                             session=marker)
        assert space.chat() is marker

    def test_no_project_means_no_session(self, tmp_path, no_model):
        folder = tmp_path / "empty"
        folder.mkdir()
        assert ws.Workspace(str(folder)).chat() is None

    def test_opening_another_project_drops_the_old_session(self, dataset_dir,
                                                           no_model):
        from sdk import projects as registry
        registry.add("Cohort", str(dataset_dir))
        space = ws.Workspace(str(dataset_dir),
                             profile_project(str(dataset_dir)),
                             session=object())
        space.open("cohort")
        assert space.session is None
