"""
Tests for the agent loop, driven by a scripted provider.

The point of these is the division of authority: the model chooses what to do,
and the tools decide what is true. A model that claims an analysis is possible,
or asks for a record, must not get either.
"""
import json
import os

import pytest

from sdk.agent import MAX_STEPS, SYSTEM, Session, Step
from sdk.llm.base import AgentReply, LLMError, ToolCall


class ScriptedProvider:
    """Replays planned replies and records the history it was given."""

    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def converse(self, system, history, tools=None, max_tokens=4096,
                 temperature=0.0):
        self.seen.append({"system": system, "history": list(history),
                          "tools": [t.name for t in (tools or [])]})
        if not self.replies:
            return AgentReply(text="done")
        return self.replies.pop(0)


@pytest.fixture
def project(dataset_dir):
    return dataset_dir


def session(provider, profile, project, **kwargs):
    return Session.create(provider, profile, project_dir=str(project), **kwargs)


class TestLoop:
    def test_a_plain_answer_ends_the_turn(self, profile, project):
        provider = ScriptedProvider([AgentReply(text="Hello.")])
        s = session(provider, profile, project)
        assert s.ask("hi") == "Hello."
        assert len(provider.seen) == 1

    def test_a_tool_call_is_executed_and_fed_back(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[ToolCall("1", "read_dataset", {})]),
            AgentReply(text="It is a diagnosis-level dataset."),
        ])
        s = session(provider, profile, project)
        reply = s.ask("what is this?")
        assert reply == "It is a diagnosis-level dataset."
        # the second call carries the tool result
        results = provider.seen[1]["history"][-1].tool_results
        assert results[0].name == "read_dataset"
        assert "GRAIN" in results[0].content

    def test_several_tools_in_one_turn(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[ToolCall("1", "read_dataset", {}),
                                   ToolCall("2", "list_analyses", {})]),
            AgentReply(text="ok"),
        ])
        s = session(provider, profile, project)
        s.ask("go")
        assert len(provider.seen[1]["history"][-1].tool_results) == 2

    def test_every_tool_is_offered(self, profile, project):
        provider = ScriptedProvider([AgentReply(text="ok")])
        s = session(provider, profile, project)
        s.ask("hi")
        offered = provider.seen[0]["tools"]
        for name in ("read_dataset", "list_analyses", "check_analysis",
                     "generate_analysis", "run_analysis", "run_checks",
                     "profile_field", "read_file", "write_file", "list_files"):
            assert name in offered

    def test_steps_are_reported_for_display(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[ToolCall("1", "read_dataset", {})]),
            AgentReply(text="ok"),
        ])
        steps = []
        session(provider, profile, project).ask("go", on_step=steps.append)
        assert [s.kind for s in steps] == ["tool"]
        assert steps[0].label == "read_dataset"

    def test_the_loop_is_bounded(self, profile, project):
        provider = ScriptedProvider(
            [AgentReply(tool_calls=[ToolCall(str(i), "read_dataset", {})])
             for i in range(MAX_STEPS + 5)])
        reply = session(provider, profile, project).ask("loop forever")
        assert "Stopped after" in reply


class TestResilience:
    def test_an_unknown_tool_is_reported_not_raised(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[ToolCall("1", "rm_rf", {})]),
            AgentReply(text="recovered"),
        ])
        s = session(provider, profile, project)
        assert s.ask("go") == "recovered"
        result = provider.seen[1]["history"][-1].tool_results[0]
        assert result.is_error
        assert "No such tool" in result.content

    def test_bad_arguments_come_back_as_guidance(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[ToolCall("1", "read_file", {"wrong": 1})]),
            AgentReply(text="recovered"),
        ])
        s = session(provider, profile, project)
        s.ask("go")
        result = provider.seen[1]["history"][-1].tool_results[0]
        assert result.is_error
        assert "Bad arguments" in result.content

    def test_a_refusal_is_information_not_a_crash(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[
                ToolCall("1", "generate_analysis", {"analysis": "prevalence"})]),
            AgentReply(text="I explained why not."),
        ])
        s = session(provider, profile, project)
        assert s.ask("compute prevalence") == "I explained why not."
        result = provider.seen[1]["history"][-1].tool_results[0]
        assert result.content.startswith("REFUSED:")

    def test_a_provider_failure_is_surfaced(self, profile, project):
        class Broken:
            def converse(self, *a, **k):
                raise LLMError("endpoint unreachable")
        reply = session(Broken(), profile, project).ask("hi")
        assert "endpoint unreachable" in reply


class TestAuthority:
    def test_the_model_cannot_generate_a_blocked_analysis(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[
                ToolCall("1", "generate_analysis", {"analysis": "prevalence"})]),
            AgentReply(text="done"),
        ])
        session(provider, profile, project).ask("just do it")
        assert not os.path.exists(os.path.join(str(project), "analyses",
                                               "prevalence.py"))

    def test_the_model_cannot_write_outside_the_project(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[ToolCall("1", "write_file", {
                "path": "../escaped.py", "content": "x = 1"})]),
            AgentReply(text="done"),
        ])
        session(provider, profile, project).ask("write it")
        assert not os.path.exists(os.path.join(os.path.dirname(str(project)),
                                               "escaped.py"))

    def test_the_system_prompt_states_who_decides(self, profile, project):
        assert "NOT YOURS TO MAKE" in SYSTEM
        assert "authoritative" in SYSTEM

    def test_the_system_prompt_pins_the_reply_language(self):
        """Open models drift language mid-answer without being told."""
        assert "language the researcher wrote in" in SYSTEM

    def test_the_system_prompt_flags_synthetic_data(self):
        assert "SYNTHETIC" in SYSTEM


class TestTranscript:
    def test_a_transcript_is_written(self, profile, project):
        provider = ScriptedProvider([
            AgentReply(tool_calls=[ToolCall("1", "read_dataset", {})]),
            AgentReply(text="answered"),
        ])
        s = session(provider, profile, project)
        s.ask("what is this?")
        assert s.transcript_path and os.path.exists(s.transcript_path)
        entries = [json.loads(l) for l in open(s.transcript_path, encoding="utf-8")]
        roles = [e["role"] for e in entries]
        assert roles[0] == "session"
        assert "user" in roles and "tool" in roles and "assistant" in roles

    def test_recording_can_be_declined(self, profile, project):
        provider = ScriptedProvider([AgentReply(text="ok")])
        s = session(provider, profile, project, record=False)
        s.ask("hi")
        assert s.transcript_path is None
        assert not os.path.exists(os.path.join(str(project), ".epsilon"))

    def test_the_session_header_pins_the_card(self, profile, project):
        s = session(ScriptedProvider([AgentReply(text="ok")]), profile, project)
        first = json.loads(open(s.transcript_path, encoding="utf-8").readline())
        assert first["archetype"] == profile.archetype_id
        assert first["schema_hash"] == profile.schema_hash
