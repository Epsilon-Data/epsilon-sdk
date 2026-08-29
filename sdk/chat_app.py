"""
The assistant, as a Chainlit app.

Chainlit owns the chat: markdown, code blocks, tables, tool-call steps,
threads, streaming and session history. What stays ours is everything a
framework cannot know -- measuring the projection, deciding what is
computable, and refusing what is not.

Run through `epsilon start`, which points Chainlit at this module in the
researcher's project directory. Nothing is hosted; it is one local process.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import List, Optional

import chainlit as cl

from sdk import catalogue as catalogue_mod
from sdk import profile as profile_mod
from sdk.agent import Session
from sdk.profile import Profile

# The project the researcher started us in. Set by `epsilon start`; falls back
# to the working directory so `chainlit run sdk/chat_app.py` also works.
PROJECT_DIR = os.environ.get("EPSILON_PROJECT_DIR", ".")


def _load() -> Optional[Profile]:
    try:
        return profile_mod.profile_project(PROJECT_DIR)
    except profile_mod.ProfileError:
        return None


def _greeting(profile: Profile) -> str:
    rows = format(profile.grain.rows or 0, ",")
    return (
        "Measured the projection on disk — **{0} columns**, **{1} rows**, one "
        "row per {2}, suppression threshold {3}.\n\n"
        "Describe what you want to find out and I will check whether this "
        "archetype can answer it, write the analysis and run it against the "
        "synthetic data. Where the answer is no, you get the reason and what "
        "would unlock it."
    ).format(len(profile.leaves), rows, profile.grain.label, profile.min_cell)


@cl.set_starters
async def starters():
    """Suggested openings, drawn from what this dataset can and cannot do."""
    profile = _load()
    if profile is None:
        return []

    blocked = [m for m in catalogue_mod.evaluate(profile) if not m.feasible]
    available = [m for m in catalogue_mod.evaluate(profile) if m.feasible]

    out = [cl.Starter(
        label="What can I compute?",
        message="What can I compute with this dataset, and what can't I?")]
    if blocked:
        out.append(cl.Starter(
            label="Why is {0} blocked?".format(blocked[0].key),
            message="Why is {0} blocked here, and what would unlock it?".format(
                blocked[0].key)))
    if available:
        out.append(cl.Starter(
            label="Run a {0}".format(available[-1].key),
            message="Generate a {0} analysis, run it, and show me the "
                    "results.".format(available[-1].key)))
    return out


@cl.on_chat_start
async def start():
    profile = _load()
    if profile is None:
        await cl.Message(content=(
            "**No project here.** The assistant only answers about a dataset "
            "already initialised in this directory — run `epsilon init "
            "<dataset_id>` first.")).send()
        return

    try:
        from sdk import llm
        provider = llm.get_provider(llm.TIER_A, "the assistant")
    except Exception as exc:
        await cl.Message(content=(
            "**No model configured.** {0}\n\nEverything else — `epsilon "
            "explain`, `epsilon snippet`, `epsilon check` — works without "
            "one.".format(exc))).send()
        return

    session = Session.create(provider, profile, project_dir=PROJECT_DIR)
    cl.user_session.set("session", session)
    cl.user_session.set("profile", profile)
    await cl.Message(content=_greeting(profile)).send()


@cl.on_message
async def on_message(message: cl.Message):
    session: Optional[Session] = cl.user_session.get("session")
    if session is None:
        await cl.Message(content=(
            "The assistant is not available — see the message above.")).send()
        return

    # Session.ask is synchronous and blocking, so it runs off the event loop
    # while tool calls are pushed back as they happen.
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_step(step):
        loop.call_soon_threadsafe(queue.put_nowait, step)

    task = loop.run_in_executor(
        None, lambda: session.ask(message.content, on_step=on_step))

    async def drain():
        while True:
            step = await queue.get()
            if step is None:
                return
            name, arg = _split(step.label)
            async with cl.Step(name=name, type="tool") as s:
                s.input = arg
                s.output = _summarise(step.detail)

    drainer = asyncio.create_task(drain())
    try:
        reply = await task
    finally:
        queue.put_nowait(None)
        await drainer

    await cl.Message(content=reply).send()
    await _send_charts(session)


async def _send_charts(session: Session) -> None:
    """Draw whatever the analyses produced this turn.

    The numbers come from the released result, never from the model, so a
    chart cannot disagree with the table beside it.
    """
    for chart in (session.box.charts if session.box else []):
        groups = [{
            "label": g["label"],
            "bars": [{"who": str(value)[:24],
                      "value": count,
                      "label": "{0:,}".format(count)}
                     for value, count in g["pairs"]],
        } for g in chart["groups"]]

        element = cl.CustomElement(name="BarChart", props={
            "title": chart["title"],
            "caption": chart["source"],
            "groups": groups,
            "held": chart.get("held", 0),
        })
        await cl.Message(content="", elements=[element]).send()


_CALL = re.compile(r"^(\w+)(?:\((.*)\))?$")


def _split(label: str):
    match = _CALL.match(label or "")
    if not match:
        return label or "tool", ""
    return match.group(1), match.group(2) or ""


# A tool result is context for the model, not reading material. Show enough to
# audit what happened without reprinting the dataset into the transcript.
def _summarise(detail: str, limit: int = 600) -> str:
    text = (detail or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… ({0} more characters)".format(len(text) - limit)
