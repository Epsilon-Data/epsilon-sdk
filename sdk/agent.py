"""
The copilot agent loop.

The model drives. It decides what to look at, what to write, what to run and
what to say; there is no fixed script and no menu. What it cannot do is invent
the things that have to be true -- the grain of a row, whether an analysis is
computable, what main.py currently contains -- because each of those is a tool
call rather than a recollection.

That is the same bargain a coding agent makes when it reads a file instead of
remembering it, and here it carries more weight: an analysis that is wrong for
a dataset still runs, still clears the submission gate, and still comes back
attested.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from sdk.profile import Profile
from sdk.llm.base import (AgentReply, LLMError, Provider, ToolCall, ToolResult,
                          ToolSpec, Turn)
from sdk.tools import Tool, ToolError, Toolbox, build_tools

TRANSCRIPT_DIR = os.path.join(".epsilon", "chat")

# A single researcher request should not run away. Well past what any real
# request needs, low enough to stop a loop.
MAX_STEPS = 24

SYSTEM = """You are the Epsilon research copilot. You help a researcher working \
in a trusted research environment (TRE) go from a research question to an \
analysis whose output will actually clear disclosure review.

You are working inside the researcher's project directory. Use your tools \
rather than your memory: call read_dataset before discussing the data, read_file \
before discussing code, and run_analysis before reporting what code produces.

READ THE DATA BEFORE DESCRIBING IT. read_dataset reports what was measured \
from the local projection: field types, ranges, distinct counts, and anything \
the measurement flagged. It describes shape, not meaning -- it does not know \
what the data is for or how it was collected. Never assert a statistic, a \
value domain or a grain you have not read from a tool, and never supply \
domain knowledge the measurement could not have seen.

FEASIBILITY VERDICTS ARE NOT YOURS TO MAKE. check_analysis and list_analyses \
return authoritative verdicts from a deterministic matcher. If a verdict says \
an analysis is blocked, it is blocked: explain why in plain language, say what \
would unlock it, and offer what is available instead. Never tell a researcher \
they can compute something the matcher refused, and never work around a \
refusal by writing the code by hand.

DISCLOSURE RULES ARE STRUCTURAL. Any code you write must aggregate before it \
returns, apply the suppression threshold to every cell, and never print \
or save an individual record. Prefer generate_analysis, whose templates already \
do this, and write code by hand only when no template fits.

THE LOCAL DATA IS SYNTHETIC. Numbers from run_analysis are not results. Say so \
whenever you report one.

NEVER REPORT A NUMBER YOU HAVE NOT SEEN. Report only figures that appear in a \
tool result from this turn. If a result is marked INCOMPLETE, say so and \
narrow the request; do not fill the missing part from an earlier tool result, \
earlier message, or from what you expect the value to be. A fabricated figure \
presented as output is the worst thing you can do here.

Be concise and concrete. Lead with what you found or did. When a researcher's \
question cannot be answered as asked, say that first and clearly -- a wrong \
number that runs cleanly is the failure mode this platform exists to prevent.

Always reply in the language the researcher wrote in."""


@dataclass
class Step:
    """One thing the agent did, for display and for the transcript."""
    kind: str           # "text" | "tool" | "error"
    label: str = ""
    detail: str = ""


@dataclass
class Session:
    provider: Provider
    profile: Profile
    project_dir: str = "."
    history: List[Turn] = field(default_factory=list)
    tools: List[Tool] = field(default_factory=list)
    transcript_path: Optional[str] = None
    box: Optional[Toolbox] = None

    @classmethod
    def create(cls, provider: Provider, profile: Profile,
               project_dir: str = ".", record: bool = True) -> "Session":
        box = Toolbox(project_dir, profile)
        session = cls(provider=provider, profile=profile, project_dir=project_dir,
                      tools=build_tools(box), box=box)
        if record:
            session.transcript_path = _open_transcript(project_dir, profile)
        return session

    @property
    def specs(self) -> List[ToolSpec]:
        return [tool.spec for tool in self.tools]

    def _tool(self, name: str) -> Optional[Tool]:
        for tool in self.tools:
            if tool.spec.name == name:
                return tool
        return None

    def _invoke(self, call: ToolCall) -> ToolResult:
        tool = self._tool(call.name)
        if tool is None:
            return ToolResult(call.id, call.name,
                              "No such tool '{0}'. Available: {1}".format(
                                  call.name,
                                  ", ".join(t.spec.name for t in self.tools)),
                              is_error=True)
        try:
            output = tool.run(**(call.input or {}))
            return ToolResult(call.id, call.name, output)
        except ToolError as exc:
            # A refusal is information for the model, not a crash: it should
            # read the reason and change course.
            return ToolResult(call.id, call.name, "REFUSED: " + str(exc),
                              is_error=True)
        except TypeError as exc:
            return ToolResult(call.id, call.name,
                              "Bad arguments for {0}: {1}".format(call.name, exc),
                              is_error=True)
        except Exception as exc:  # a tool bug must not kill the session
            return ToolResult(call.id, call.name,
                              "{0} failed: {1}: {2}".format(
                                  call.name, type(exc).__name__, exc),
                              is_error=True)

    def ask(self, message: str,
            on_step: Optional[Callable[[Step], None]] = None) -> str:
        """Run one researcher request to completion. Returns the final reply."""
        on_step = on_step or (lambda step: None)
        if self.box is not None:
            self.box.charts = []   # charts belong to the turn that produced them
        self.history.append(Turn("user", text=message))
        _record(self.transcript_path, {"role": "user", "text": message})

        final = ""
        for _ in range(MAX_STEPS):
            try:
                reply = self.provider.converse(SYSTEM, self.history, self.specs)
            except LLMError as exc:
                on_step(Step("error", detail=str(exc)))
                return str(exc)

            self.history.append(Turn("assistant", text=reply.text,
                                     tool_calls=reply.tool_calls))
            if reply.text:
                _record(self.transcript_path,
                        {"role": "assistant", "text": reply.text})

            if not reply.wants_tools:
                final = reply.text
                break

            results = []
            for call in reply.tool_calls:
                tool = self._tool(call.name)
                label = call.name
                if tool and tool.summarise:
                    try:
                        label = tool.summarise(call.input or {}, "")
                    except Exception:
                        pass
                result = self._invoke(call)
                results.append(result)
                on_step(Step("tool", label=label, detail=result.content))
                _record(self.transcript_path,
                        {"role": "tool", "name": call.name,
                         "input": call.input, "error": result.is_error,
                         "output": result.content[:2000]})
            self.history.append(Turn("user", tool_results=results))
        else:
            final = ("Stopped after {0} steps without finishing. Try asking "
                     "for something narrower.".format(MAX_STEPS))
            on_step(Step("error", detail=final))

        return final


def _open_transcript(project_dir: str, profile: Profile) -> Optional[str]:
    """Start a transcript so the AI assistance is part of the job's record.

    With a bring-your-own-key setup the platform never sees these calls, so the
    only account of how an analysis was shaped is the one written here and
    attached at build time.
    """
    directory = os.path.join(project_dir, TRANSCRIPT_DIR)
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
        path = os.path.join(
            directory, datetime.now().strftime("%Y-%m-%d") + ".jsonl")
        _record(path, {"role": "session",
                       "started": datetime.now().isoformat(),
                       "archetype": profile.archetype_id,
                       "schema_hash": profile.schema_hash,
                       "rows": profile.grain.rows})
        return path
    except OSError:
        return None


def _record(path: Optional[str], entry: Dict) -> None:
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass
