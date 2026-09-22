"""Conservative source checks. These never import code or inspect dataset rows."""
import ast
import sys

from sdk.workbench.libraries import LIBRARIES

# Python 3.9 hosts do not expose stdlib_module_names. Its fallback covers the
# common analysis modules; any other import is reported as unverified.
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names) | set(
    "abc array ast base64 bisect calendar collections contextlib copy csv dataclasses datetime decimal enum fractions functools hashlib heapq html inspect io itertools json math numbers operator os pathlib pickle platform random re statistics string struct sys tempfile textwrap time traceback types typing unicodedata uuid warnings weakref zoneinfo".split())


# Arithmetic on text either fails ("Cannot convert ... to numeric") or, worse,
# quietly compares strings: "88.9" sorts above "175.7".
NUMERIC_CALLS = {"mean", "median", "sum", "std", "var", "sem", "quantile", "min", "max", "idxmin", "idxmax",
                 "corr", "cov", "cumsum", "cumprod", "nlargest", "nsmallest", "hist", "rank", "round", "abs", "diff"}
CONVERSIONS = {"to_numeric", "astype", "to_datetime", "convert_dtypes", "infer_objects"}


def check_code(source, fields, runtime, context=(), numeric=()):
    """Check explicit imports and literal selections on a known synthetic frame.

    Dynamic Python and package API compatibility require execution. Unknown
    imports are unverified, not claimed missing: the inventory is intentionally
    limited to the managed scientific libraries.
    """
    issues, seen = [], set()
    available = {p["module"] for p in runtime.get("packages", [])}
    managed = {p[0] for p in LIBRARIES.values()}
    verified = runtime.get("inventory_verified", False)
    fields, numeric = set(fields), set(numeric)

    def issue(code, line, message, **detail):
        key = (code, line, message)
        if key not in seen and len(issues) < 20:
            seen.add(key)
            issues.append(dict({"code": code, "line": line, "message": message}, **detail))

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"status": "issues", "issues": [{"code": "syntax", "line": exc.lineno or 1,
                "message": "Python could not parse this code."}], "scope": "Static code checks; code has not been run."}
    for node in ast.walk(tree):
        names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        for name in names:
            module = name.split(".")[0]
            if module in STDLIB or module in available or name == "generated.models":
                continue
            missing = verified and module in managed
            issue("missing_library" if missing else "unverified_library", node.lineno,
                  f"{module or 'Relative import'} is not installed in this notebook." if missing else
                  f"{module or 'Relative import'} is not in the verified library list. Check availability before running.")

    # Track only straight-line, known pandas reads and aliases. Avoid guessing
    # column provenance across functions, loops, joins or arbitrary Python.
    pandas, readers, frames = set(), set(), {}
    # Frames built from create_dataset().records hold every value as text,
    # because the generated wrapper reads the CSV without types.
    text_frames, converted = set(), set()

    def labels(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [value for item in node.elts for value in labels(item)]
        return []

    def frame(node):
        if isinstance(node, ast.Name) and node.id in frames:
            return frames[node.id]
        if isinstance(node, ast.Call):
            fn = node.func
            is_read = (isinstance(fn, ast.Name) and fn.id in readers) or (
                isinstance(fn, ast.Attribute) and fn.attr == "read_csv" and
                isinstance(fn.value, ast.Name) and fn.value.id in pandas)
            path = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "filepath_or_buffer"), None)
            if is_read and isinstance(path, ast.Constant) and path.value in ("generated/data.csv", "./generated/data.csv"):
                # Custom names/headers change the column vocabulary.
                if any(k.arg in ("names", "header", "index_col") for k in node.keywords):
                    return None
                return set(fields)
            if is_records(node):
                return set(fields)
            if isinstance(fn, ast.Attribute) and fn.attr in ("copy", "dropna", "fillna", "sort_values", "reset_index"):
                known = frame(fn.value)
                return set(known) if known is not None else None
        return None

    def is_records(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "DataFrame"
                and isinstance(node.func.value, ast.Name) and node.func.value.id in pandas and node.args
                and isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "records")

    def calls(node):
        return {c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
                for c in ast.walk(node) if isinstance(c, ast.Call)}

    def text_columns(node):
        """Numeric schema columns read, unconverted, from a text-valued frame."""
        found = []
        for item in ast.walk(node):
            if isinstance(item, ast.Subscript) and any(isinstance(n, ast.Name) and n.id in text_frames for n in ast.walk(item.value)):
                found += [label for label in labels(item.slice) if label in numeric and label not in converted]
        return found

    def text_maths(node, report):
        if not report or not text_frames:
            return
        for item in ast.walk(node):
            used = []
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr in NUMERIC_CALLS:
                if not calls(item.func.value) & CONVERSIONS:
                    used = text_columns(item.func.value)
            elif isinstance(item, (ast.Compare, ast.BinOp)) and not calls(item) & CONVERSIONS:
                sides = [item.left] + (item.comparators if isinstance(item, ast.Compare) else [item.right])
                if any(isinstance(side, ast.Constant) and isinstance(side.value, (int, float)) and not isinstance(side.value, bool) for side in sides):
                    used = [label for side in sides for label in text_columns(side)]
            for label in used:
                issue("text_values", getattr(item, "lineno", 1),
                      f"{label} is numeric, but create_dataset() loads every value as text. Convert it before calculating, "
                      f"for example data['{label}'] = pd.to_numeric(data['{label}'], errors='coerce').", field=label)

    def select(node, known, report):
        if known is None or not report:
            return
        for label in labels(node):
            if label not in known:
                issue("unknown_field", getattr(node, "lineno", 1),
                      f"{label[:160]} is not a known column at this point. Check its spelling or create it first.",
                      field=label[:160])

    def inspect(node, report):
        for item in ast.walk(node):
            if isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Load):
                if isinstance(item.value, ast.Attribute) and item.value.attr == "loc":
                    if isinstance(item.slice, ast.Tuple) and len(item.slice.elts) == 2:
                        select(item.slice.elts[1], frame(item.value.value), report)
                else:
                    select(item.slice, frame(item.value), report)
            if isinstance(item, ast.Call):
                fn = item.func
                if isinstance(fn, ast.Attribute):
                    known = frame(fn.value)
                    if fn.attr in ("groupby", "sort_values", "value_counts") and item.args:
                        select(item.args[0], known, report)
                    if fn.attr in ("groupby", "sort_values", "pivot_table", "pivot", "drop", "value_counts"):
                        for kw in item.keywords:
                            if kw.arg in ("by", "index", "columns", "values", "subset") and not (fn.attr == "drop" and kw.arg == "index"):
                                select(kw.value, known, report)
                data = next((kw.value for kw in item.keywords if kw.arg == "data"), None)
                known = frame(data)
                if known is not None:
                    for kw in item.keywords:
                        if kw.arg in ("x", "y", "hue", "col", "row", "size", "style"):
                            select(kw.value, known, report)

    def statements(module, report):
        for node in module.body:
            if isinstance(node, ast.Import):
                pandas.update(a.asname or a.name for a in node.names if a.name == "pandas")
            elif isinstance(node, ast.ImportFrom) and node.module == "pandas":
                readers.update(a.asname or a.name for a in node.names if a.name == "read_csv")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                if node.value is not None:
                    inspect(node.value, report)
                    text_maths(node.value, report)
                known = frame(node.value)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                changed = node.value is not None and bool(calls(node.value) & (CONVERSIONS | {"apply"}))
                for target in targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in text_frames and changed:
                        converted.update(labels(target.slice))
                    if isinstance(target, ast.Name):
                        value = node.value
                        derived = value is not None and any(isinstance(n, ast.Name) and n.id in text_frames for n in ast.walk(value))
                        text_frames.discard(target.id)
                        # A filtered or copied text frame is still text, unless
                        # the statement converted it as a whole.
                        if is_records(value) or (derived and not changed):
                            text_frames.add(target.id)
                    if isinstance(target, ast.Name):
                        frames.pop(target.id, None)
                        if known is not None:
                            frames[target.id] = known
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in frames:
                        frames[target.value.id].update(labels(target.slice))
                    elif isinstance(target, ast.Attribute) and target.attr == "columns":
                        # Replacing the whole column index invalidates inferred
                        # vocabulary, including aliases to that frame.
                        frames.clear()
            elif isinstance(node, ast.Expr):
                inspect(node, report)
                text_maths(node, report)
                # Mutation can rename or replace columns; stop inferring them.
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                    fn = node.value.func
                    if isinstance(fn.value, ast.Name) and fn.attr in ("rename", "set_axis", "drop", "insert", "pop", "update"):
                        frames.pop(fn.value.id, None)
            else:
                # Control flow and explicit rebinding invalidate assumptions.
                text_maths(node, report)
                for item in ast.walk(node):
                    if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
                        frames.pop(item.id, None)

    for previous in context:
        try:
            statements(ast.parse(previous), False)
        except (SyntaxError, RecursionError):
            frames.clear()
    statements(tree, True)
    return {"status": "issues" if issues else "checked" if verified else "limited", "issues": issues,
            "scope": "Checks cover explicit imports and detectable column names. Code has not been run; research and disclosure review are separate."}
