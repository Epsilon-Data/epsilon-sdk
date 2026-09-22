"""Match the words a researcher uses to the columns the dataset really has.

Matching is local and deterministic: the model never decides which columns
exist. It receives candidates drawn only from the schema, and the researcher
picks one. Nothing here reads dataset rows or observed values.
"""
import difflib
import re

# Research vocabulary that spelling similarity cannot bridge. Each group is a
# set of interchangeable words; keep it to everyday, unambiguous equivalents.
SYNONYMS = [
    {"sex", "gender"},
    {"age", "years", "yrs"},
    {"dob", "birth", "birthdate", "born"},
    {"bmi", "bodymass", "bodymassindex"},
    {"ethnicity", "ethnic", "race"},
    {"weight", "wt", "kg"},
    {"height", "ht", "cm"},
    {"bp", "bloodpressure", "systolic", "diastolic"},
    {"smoking", "smoker", "smoke", "tobacco", "cigarette"},
    {"alcohol", "drinking", "drinker"},
    {"diabetes", "diabetic", "dm", "t2dm"},
    {"hypertension", "hypertensive", "htn"},
    {"glucose", "sugar", "hba1c", "glycaemic", "glycemic"},
    {"cholesterol", "lipid", "ldl", "hdl"},
    {"income", "salary", "earnings", "wage"},
    {"education", "schooling", "qualification"},
    {"occupation", "job", "employment", "work"},
    {"marital", "married", "marriage"},
    {"region", "district", "area", "location", "state", "province"},
    {"date", "dt", "day", "time", "when"},
    {"id", "identifier", "key"},
    {"outcome", "result", "status", "diagnosis", "diagnosed"},
    {"death", "died", "mortality", "deceased"},
    {"visit", "encounter", "admission", "attendance"},
    {"medication", "drug", "medicine", "prescription", "treatment"},
]
_GROUP = {word: index for index, group in enumerate(SYNONYMS) for word in group}
_STOP = {"the", "a", "an", "of", "by", "in", "for", "and", "or", "to", "is", "per", "column", "field", "variable"}


def tokens(text):
    """Lowercase words from snake_case, camelCase, dotted paths and prose."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return [w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if w and w not in _STOP]


def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) else word


def _concepts(words):
    found = set()
    for word in list(words) + ["".join(words)]:
        if word in _GROUP:
            found.add(_GROUP[word])
        elif len(word) >= 6:
            # A misspelt research term ("etnicity") still names its concept.
            near = difflib.get_close_matches(word, _GROUP, n=1, cutoff=0.85)
            found.update(_GROUP[n] for n in near)
    return found


def _word(asked, have):
    if asked == have:
        return 1.0
    short, long = sorted((asked, have), key=len)
    if len(short) >= 3 and long.startswith(short):
        return 0.75
    if len(short) >= 4:
        ratio = difflib.SequenceMatcher(None, asked, have).ratio()
        return ratio if ratio >= 0.75 else 0.0
    return 0.0


def score(term, path):
    """0..1 similarity between a researcher's term and one schema path."""
    wanted, leaf = tokens(term), tokens(path.rsplit(".", 1)[-1])
    whole = tokens(path)
    if not wanted or not whole:
        return 0.0
    if "".join(wanted) in ("".join(leaf), "".join(whole)):
        return 1.0
    best = 0.0
    asked = {_stem(w) for w in wanted}
    for candidate in (leaf, whole):
        have = {_stem(w) for w in candidate}
        shared = asked & have
        overlap = len(shared) / len(asked | have)
        # Every requested word present, with extra qualifiers on the column.
        contained = 0.85 if shared and asked <= have else 0.0
        spelling = difflib.SequenceMatcher(None, "".join(wanted), "".join(candidate)).ratio()
        # Only a near-identical spelling is a typo. Sharing an ending is not:
        # "genotype" must never be offered "admissions.type". Short strings
        # look alike by accident, so they never match on spelling alone.
        if spelling < 0.8 or min(len("".join(wanted)), len("".join(candidate))) < 4:
            spelling = 0.0
        # Word by word, so a typo or an abbreviation ("adm_type") inside a
        # longer name still finds its column.
        words = 0.9 * sum(max(_word(w, c) for c in have) for w in asked) / len(asked)
        best = max(best, overlap, contained, spelling * 0.95, words)
    meant = _concepts(wanted)
    if meant & _concepts(whole):
        # Rank a column covering every idea asked for above one covering some.
        best = max(best, 0.6 + 0.2 * len(meant & _concepts(whole)) / len(meant))
    return round(best, 3)


def resolve(term, fields, limit=4, threshold=0.6):
    """Match one term against schema fields ({"path", "type", ...}).

    Returns the exact path when the term names a column, otherwise the closest
    columns, best first. An empty candidate list means the dataset has nothing
    like it, which the assistant must say instead of guessing.
    """
    term = str(term).strip()[:160]
    by_path = {f["path"]: f for f in fields}
    lowered = {path.lower(): path for path in by_path}
    exact = by_path.get(term, {}).get("path") or lowered.get(term.lower())
    if exact is None:
        # A bare leaf name is exact only when a single column ends with it.
        leaves = [path for path in by_path if path.rsplit(".", 1)[-1].lower() == term.lower()]
        exact = leaves[0] if len(leaves) == 1 else None
    if exact:
        return {"term": term, "exact": exact, "candidates": []}
    ranked = sorted(((score(term, path), path) for path in by_path), key=lambda item: (-item[0], item[1]))
    # The same words in another spelling ("admission type") name the column
    # outright, provided only one column reads that way.
    if ranked and ranked[0][0] == 1.0 and (len(ranked) == 1 or ranked[1][0] < 1.0):
        return {"term": term, "exact": ranked[0][1], "candidates": []}
    return {"term": term, "exact": None,
            "candidates": [{"path": path, "type": by_path[path].get("type", "unknown"), "score": value}
                           for value, path in ranked[:limit] if value >= threshold]}


def identifier_terms(question, limit=8):
    """Words in a question that are written like column names.

    Only quoted, backticked, snake_case or dotted words qualify: ordinary prose
    is left to the model, which asks the resolver about the terms it notices.
    """
    found = re.findall(r"`([^`\n]{1,80})`|\"([A-Za-z][\w. ]{0,79})\"|'([A-Za-z][\w.]{0,79})'|\b([A-Za-z][A-Za-z0-9]*(?:[_.][A-Za-z0-9]+)+)\b", question or "")
    terms = []
    for groups in found:
        term = next(g for g in groups if g).strip()
        if term and term.lower() not in {t.lower() for t in terms} and not re.fullmatch(r"[\d.]+", term):
            terms.append(term)
    return terms[:limit]
