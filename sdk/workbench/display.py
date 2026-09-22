"""Bounded notebook MIME rendering. Kernel output is always untrusted data."""
import ast
import base64
import copy
import html
import json
import math
import re
import struct
from datetime import date
from html.parser import HTMLParser

MAX_TEXT = 120000
MAX_BLOCKS = 32
MAX_TOTAL = 900000
PREVIEW_MIME = "application/vnd.epsilon.preview+json"
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_BAND = re.compile(r"^(-?\d+(?:\.\d+)?) to < (-?\d+(?:\.\d+)?)$")


def text(value, limit=MAX_TEXT):
    return _ANSI.sub("", value if isinstance(value, str) else str(value or ""))[:limit]


class _HTML(HTMLParser):
    # Rebuild a small inert subset. No URLs, style, IDs, forms, event handlers,
    # embedded images, scripts or SVG are carried out of the kernel.
    tags = set("p div span table thead tbody tfoot tr th td caption colgroup col h1 h2 h3 h4 h5 h6 strong b em i u s del pre code blockquote ul ol li br hr sub sup dl dt dd details summary".split())
    blocked = set("script style iframe object embed svg math template noscript".split())
    void = {"br", "hr", "col"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output, self.stack, self.hidden = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            self.hidden.append(tag)
            return
        if self.hidden or tag not in self.tags:
            return
        kept = []
        for key, value in attrs:
            if tag in ("td", "th", "col") and key in ("colspan", "rowspan", "span") and value and value.isascii() and value.isdecimal():
                kept.append(' %s="%s"' % (key, min(100, max(1, int(value[:6])))))
            if tag == "details" and key == "open":
                kept.append(" open")
        self.output.append("<" + tag + "".join(kept) + ">")
        if tag not in self.void:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.output.append("</" + current + ">")
                if current == tag:
                    break

    def handle_data(self, data):
        if not self.hidden:
            self.output.append(html.escape(data))


def safe_html(value):
    parser = _HTML()
    parser.feed(text(value))
    parser.close()
    while parser.stack:
        parser.output.append("</" + parser.stack.pop() + ">")
    return "".join(parser.output)


def markdown(value):
    from markdown_it import MarkdownIt
    return safe_html(MarkdownIt("commonmark", {"html": False}).enable("table").render(text(value)))


def png(value):
    if not isinstance(value, str) or len(value) > 500000:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
        if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) > 375000:
            return None
        width, height = struct.unpack(">II", raw[16:24])
        return value if 0 < width <= 2000 and 0 < height <= 2000 else None
    except (ValueError, TypeError, struct.error):
        return None


def preview(value):
    """Recognise only the bounded aggregate format, never an approval flag."""
    if not isinstance(value, dict) or value.get("policy") != "local-preview-v1" or value.get("synthetic") is not True:
        return None
    minimum, tables = value.get("min_cell"), value.get("tables")
    if type(minimum) is not int or minimum < 10 or not isinstance(tables, list) or not 0 < len(tables) <= 100:
        return None
    for table in tables:
        if not isinstance(table, dict) or not isinstance(table.get("name"), str):
            return None
        columns, rows, chart = table.get("columns"), table.get("rows"), table.get("chart")
        if not isinstance(columns, list) or not 2 <= len(columns) <= 3 or columns[-1] != "records" or any(not isinstance(c, str) or len(c) > 160 for c in columns):
            return None
        if not isinstance(rows, list) or len(rows) > 30 or not isinstance(chart, dict):
            return None
        labels, values = [], []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns) or type(row.get("records")) is not int or not minimum <= row["records"] <= 1000000:
                return None
            if any(not isinstance(row[c], str) or len(row[c]) > 200 for c in columns[:-1]):
                return None
            labels.append(" / ".join(row[c] for c in columns[:-1]))
            values.append(row["records"])
        if chart.get("labels") != labels or chart.get("values") != values:
            return None
        if type(table.get("withheld_groups")) is not int or not 0 <= table["withheld_groups"] <= 10000:
            return None
    return value


def specification(source):
    """Read a literal SPEC for axis semantics without executing notebook code."""
    try:
        tree = ast.parse(source[:50000])
        for statement in tree.body:
            if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SPEC" for t in statement.targets):
                if sum(1 for _ in ast.walk(statement.value)) > 4000:
                    return {}
                value = ast.literal_eval(statement.value)
                return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, SyntaxError, RecursionError):
        pass
    return {}


def axes(result, source):
    spec = specification(source)
    descriptors = {d.get("path"): d for d in spec.get("descriptors", []) if isinstance(d, dict) and isinstance(d.get("path"), str)} if isinstance(spec.get("descriptors"), list) else {}
    output = []
    for table in result.get("tables", []):
        descriptor = descriptors.get(table.get("name"), {})
        kind = descriptor.get("type") if spec.get("analysis") == "describe" else None
        bucket = descriptor.get("bucket", "year")
        if spec.get("analysis") == "trend" and table.get("name") == "result":
            kind = "date"
            bucket = spec.get("fields", {}).get("bucket", "year") if isinstance(spec.get("fields"), dict) else "year"
        points, step = [], 1
        for index, label in enumerate(table.get("chart", {}).get("labels", [])):
            try:
                if kind in ("integer", "number"):
                    match = _BAND.fullmatch(label)
                    if not match:
                        continue
                    position, end = map(float, match.groups())
                    if not math.isfinite(position) or not math.isfinite(end) or end <= position:
                        continue
                    step = end - position
                elif kind in ("date", "timestamp"):
                    if bucket == "year" and re.fullmatch(r"\d{4}", label):
                        position = date(int(label), 1, 1).year
                    elif bucket == "quarter" and re.fullmatch(r"\d{4} Q[1-4]", label):
                        position = date(int(label[:4]), 1, 1).year * 4 + int(label[-1])
                    elif bucket == "month" and re.fullmatch(r"\d{4}-\d{2}", label):
                        value = date.fromisoformat(label + "-01")
                        position = value.year * 12 + value.month
                    elif bucket == "day":
                        position = date.fromisoformat(label).toordinal()
                    else:
                        continue
                else:
                    continue
                points.append({"index": index, "x": position})
            except (ValueError, TypeError, OverflowError):
                continue
        output.append({"kind": "numeric" if kind in ("integer", "number") else "time" if kind in ("date", "timestamp") else "category",
                       "points": sorted(points, key=lambda p: p["x"]), "step": step})
    return output


def _json_block(value, source):
    try:
        if len(json.dumps(value, allow_nan=False)) > MAX_TEXT:
            return {"kind": "text", "text": "JSON display exceeds the notebook output limit."}
    except (ValueError, TypeError, RecursionError):
        return {"kind": "text", "text": "The result cannot be displayed as bounded JSON."}
    result = preview(value)
    if result is not None:
        return {"kind": "preview", "result": result, "axes": axes(result, source)}
    return {"kind": "json", "value": value}


def render_output(output, source=""):
    """Normalise current MIME envelopes and old saved text without mutation."""
    blocks, patches, used, truncated = [], [], 0, False
    raw = output.get("outputs")
    if not isinstance(raw, list) and isinstance(output.get("display"), dict):
        raw = []
        for block in output["display"].get("blocks", [])[:MAX_BLOCKS]:
            if not isinstance(block, dict):
                continue
            kind = block.get("kind")
            if kind in ("text", "error"):
                item = {"output_type": "error" if kind == "error" else "stream", "text": block.get("text", ""), "name": block.get("name", "stdout")}
            else:
                mime, value = {"image": ("image/png", block.get("data")), "html": ("text/html", block.get("html")),
                               "json": ("application/json", block.get("value")), "preview": (PREVIEW_MIME, block.get("result"))}.get(kind, ("text/plain", "Unsupported display."))
                item = {"output_type": "display_data", "data": {mime: value}}
            item["display_id"] = block.get("display_id")
            raw.append(item)
    if not isinstance(raw, list):
        raw = [{"output_type": "stream", "name": "stdout", "text": output.get("text", "")}]
        raw += [{"output_type": "display_data", "data": {"image/png": value}} for value in (output.get("images") or [])[:2]]
    for item in raw[:MAX_BLOCKS]:
        if not isinstance(item, dict):
            continue
        kind = item.get("output_type")
        if kind in ("stream", "error"):
            trace = item.get("traceback")
            value = text(item.get("text") or ("\n".join(text(line) for line in trace[:20]) if isinstance(trace, list) else ""))
            block = {"kind": "error" if kind == "error" else "text", "text": value}
            if kind == "stream":
                block["name"] = "stderr" if item.get("name") == "stderr" else "stdout"
            if kind == "stream" and item.get("name") != "stderr":
                try:
                    decoded = json.loads(value)
                    if preview(decoded) is not None:
                        block = _json_block(decoded, source)
                except (ValueError, TypeError, RecursionError):
                    pass
        else:
            data = item.get("data") or {}
            if not isinstance(data, dict):
                continue
            if PREVIEW_MIME in data:
                block = _json_block(data[PREVIEW_MIME], source)
            elif "image/png" in data and png(data["image/png"]):
                block = {"kind": "image", "data": png(data["image/png"])}
            elif "text/html" in data:
                block = {"kind": "html", "html": safe_html(data["text/html"])}
            elif "text/markdown" in data:
                block = {"kind": "html", "html": markdown(data["text/markdown"])}
            elif "application/json" in data:
                block = _json_block(data["application/json"], source)
            else:
                block = {"kind": "text", "text": text(data.get("text/plain") or "This output format is not supported. Use a static table or PNG figure.")}
        display_id = item.get("display_id")
        if isinstance(display_id, str) and len(display_id) <= 100:
            block["display_id"] = display_id
        size = len(json.dumps(block))
        if used + size > MAX_TOTAL:
            truncated = True
            break
        used += size
        if kind == "update_display_data":
            if block.get("display_id"):
                patches.append(block)
                blocks = [copy.deepcopy(block) if old.get("display_id") == block["display_id"] else old for old in blocks]
        else:
            blocks.append(block)
    return {"blocks": blocks, "updates": patches, "truncated": bool(truncated or output.get("truncated") or len(raw) > MAX_BLOCKS)}


def legacy_fields(output):
    """Maintain the old text/image accessors without flattening the rich view."""
    blocks = output["display"]["blocks"]
    output["text"] = "\n".join(block.get("text", "") if block["kind"] in ("text", "error") else
                               json.dumps(block["result"], indent=2) if block["kind"] == "preview" else
                               json.dumps(block["value"], indent=2) if block["kind"] == "json" else "" for block in blocks)[:MAX_TEXT]
    output["images"] = [block["data"] for block in blocks if block["kind"] == "image"][:2]
    return output


def apply_updates(notebook, output):
    """A display handle may update earlier cells in this kernel session only."""
    for patch in output.get("display", {}).get("updates", []):
        for cell in notebook["cells"]:
            previous = cell.get("output") or {}
            if not output.get("kernel_id") or previous.get("kernel_id") != output["kernel_id"] or not previous.get("display"):
                continue
            previous["display"]["blocks"] = [copy.deepcopy(patch) if block.get("display_id") == patch["display_id"] else block
                                               for block in previous["display"]["blocks"]]
            previous["display"] = render_output(previous, cell["source"])
            legacy_fields(previous)


def notebook_view(notebook):
    from sdk.workbench.store import cell_digest
    result = copy.deepcopy(notebook)
    for cell in result["cells"]:
        cell["digest"] = cell_digest(cell)
        if cell.get("ai"):
            cell["ai"]["can_undo"] = cell["ai"].get("digest") == cell_digest(cell)
        if cell.get("kind") == "markdown":
            cell["html"] = markdown(cell["source"])
        if cell.get("output"):
            cell["output"]["display"] = render_output(cell["output"], cell["source"])
    return result


def artifact_view(artifact):
    return dict(artifact, axes=axes(artifact["result"], artifact["code"]))
