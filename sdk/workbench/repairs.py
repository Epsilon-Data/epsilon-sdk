"""Explicit sharing of one reviewed cell for one question or repair request."""
import hashlib
import hmac
import json
import re

from sdk.checks import scan_secrets
from sdk.workbench.errors import PublicError
from sdk.workbench.security import check_outbound
from sdk.workbench.store import cell_digest


ERRORS = {
    "ModuleNotFoundError": "A Python library could not be found.",
    "ImportError": "Python could not import a requested module or name.",
    "NameError": "A name was used before it was defined.",
    "UnboundLocalError": "A local variable was used before it had a value.",
    "KeyError": "A requested column or mapping key could not be found.",
    "AttributeError": "An object does not support the requested attribute or method.",
    "TypeError": "An operation received an incompatible type or argument.",
    "ValueError": "An operation received a value it could not use.",
    "IndexError": "An index was outside the available range.",
    "SyntaxError": "Python could not parse the cell.",
    "IndentationError": "Python could not parse the cell's indentation.",
    "ZeroDivisionError": "An operation attempted to divide by zero.",
    "FileNotFoundError": "A required file could not be found.",
    "MemoryError": "The computation exhausted available memory.",
}


def diagnostic(output):
    """Only fixed vocabulary leaves this function, never traceback fragments.

    Older kernels store the error as text. Recognise an allowlisted exception
    name, but do not send its message, values, paths, variables or line excerpts.
    """
    blocks = output.get("display", {}).get("blocks", [])
    texts = [b.get("text", "") for b in blocks if b.get("kind") == "error"]
    if not texts:
        texts = [output.get("text", "")]
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", "\n".join(t for t in texts if isinstance(t, str))[:50000])
    found = re.findall(r"(?m)^\s*(" + "|".join(ERRORS) + r")\s*:", value)
    category = found[-1] if found else "ExecutionError"
    return {"category": category, "summary": ERRORS.get(category, "The cell did not complete successfully.")}


def connection(bench):
    status = bench.ai_status()
    if not status.get("configured"):
        raise PublicError("Connect AI in Settings before sharing a cell.")
    return {key: status.get(key, "") for key in ("provider", "model", "base_url", "source")}


def preview(bench, project_id, notebook_id, cell_id, *, purpose="repair", helper_cell_ids=()):
    helper_cell_ids = list(helper_cell_ids or [])
    if helper_cell_ids and purpose == "repair":
        raise PublicError("Repair requests share one failed cell at a time.")
    if len(helper_cell_ids) > 8 or len(set(helper_cell_ids)) != len(helper_cell_ids):
        raise PublicError("Choose at most eight different helper cells.")
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value)
           for value in helper_cell_ids):
        raise PublicError("The selected helper cells are invalid.")
    if cell_id in helper_cell_ids:
        raise PublicError("The main cell is already selected.")
    bench.project(project_id)
    book = bench.store.notebook(project_id, notebook_id)
    index = next((i for i, c in enumerate(book["cells"]) if c["id"] == cell_id), None)
    if index is None:
        raise PublicError("This cell is no longer in the notebook.")
    cell = book["cells"][index]
    output = cell.get("output") or {}
    if purpose == "repair" and (cell.get("kind") != "code" or not output.get("error")):
        raise PublicError("Run this Python cell first. Fix with AI is available after an error.")
    if purpose == "repair" and (output.get("stale") or output.get("code_digest") != hashlib.sha256(cell["source"].encode()).hexdigest()):
        raise PublicError("The code or an earlier cell changed. Run this cell again before requesting a fix.")
    source = cell["source"]
    if len(source) > 40000:
        raise PublicError("This cell is too long to share. Split it into smaller cells first.")
    check_outbound(source, bench.known_secrets())
    # Include suspicious assignments, not just high-confidence credentials.
    if scan_secrets("selected.py", source):
        raise PublicError("This cell may contain a credential. Remove it before sharing code with AI.")
    ai = cell.get("ai") or {}
    automatic = False
    if ai.get("shareable", True) and ai.get("digest") == cell_digest(cell):
        change = bench.store.get(project_id, "notebook_change", ai["change_id"])
        automatic = change["notebook_id"] == notebook_id and change["source"] == source
    result = {"project_id": project_id, "notebook_id": notebook_id, "cell_id": cell_id,
              "cell_number": index + 1, "revision": book["revision"], "source": source,
              "kind": cell.get("kind", "code"), "purpose": purpose,
              "expected_digest": cell_digest(cell), "diagnostic": diagnostic(output) if purpose == "repair" else None,
              "connection": connection(bench), "private_context": purpose != "repair" or not automatic,
              "sharing": ("Only this cell and the error description below, with permitted field definitions and notebook library information. No other cells, raw traceback or displayed outputs." if purpose == "repair" else
                          "Your next question and this cell, with permitted field definitions and notebook library information. The code is shared for this request only. Outputs and other cells are excluded.")}
    if helper_cell_ids:
        helpers = [preview(bench, project_id, notebook_id, helper_id, purpose="question")
                   for helper_id in helper_cell_ids]
        if any(helper["kind"] != "code" for helper in helpers):
            raise PublicError("Only Python helper cells can be shared with a question.")
        shared_cells = [{"cell_id": cell_id, "cell_number": result["cell_number"],
                         "source": result["source"], "kind": result["kind"],
                         "expected_digest": result["expected_digest"]}]
        shared_cells.extend({"cell_id": helper["cell_id"], "cell_number": helper["cell_number"],
                             "source": helper["source"], "kind": helper["kind"],
                             "expected_digest": helper["expected_digest"]} for helper in helpers)
        combined = "\n\n".join(
            f"# Shared notebook cell {item['cell_number']}\n{item['source']}"
            for item in shared_cells
        )
        if len(combined) > 120000:
            raise PublicError("The selected cells are too long to share together. Choose fewer helpers.")
        result.update({
            "source": combined,
            "helper_cell_ids": helper_cell_ids,
            "shared_cells": shared_cells,
            "private_context": bool(result["private_context"] or any(helper["private_context"] for helper in helpers)),
            "sharing": "Your next question and the selected notebook cells, with permitted field definitions and notebook library information. Outputs and unselected cells are excluded.",
        })
    fingerprint = result if purpose == "repair" else {key: value for key, value in result.items() if key not in ("revision", "cell_number")}
    result["context_digest"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    return result


def selected(bench, project_id, notebook_id, cell_id, context_digest, *, purpose="question", helper_cell_ids=()):
    value = preview(bench, project_id, notebook_id, cell_id, purpose=purpose,
                    helper_cell_ids=helper_cell_ids)
    if not hmac.compare_digest(value["context_digest"], context_digest):
        raise PublicError("The cell or AI connection changed. Review the selected cell again before sending.")
    return value


def submit(bench, project_id, notebook_id, cell_id, context_digest):
    from sdk.workbench import assistant
    selected = preview(bench, project_id, notebook_id, cell_id)
    if not hmac.compare_digest(selected["context_digest"], context_digest):
        raise PublicError("The cell, error or AI connection changed. Review what will be shared again.")
    tid = bench.store.notebook_thread(project_id, notebook_id)
    # Capture the approved connection before queuing work. Later settings edits
    # must not redirect already-approved source to a different provider.
    provider = bench.provider()
    if connection(bench) != selected["connection"]:
        raise PublicError("The AI connection changed. Review what will be shared again.")
    question = f"Help fix Python cell {selected['cell_number']}. Propose a corrected cell for me to review."
    return assistant.chat(bench, project_id, tid, question, notebook_id, repair=selected, repair_provider=provider)
