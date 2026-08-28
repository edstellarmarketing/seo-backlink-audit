"""
Topical relevance without embeddings.

The naive version -- does the page contain this exact phrase -- fails on the
cases that matter. A page about "staff development programmes" is squarely
relevant to a corporate-training site and scores zero against the keyword
"employee training". Meanwhile a keyword appearing once in a footer counts the
same as one in the H1.

Three cheap fixes get most of the way to something useful:

  1. STEM both sides, so programmes/programme/program and training/trainings
     collapse together, and British spellings match American ones.
  2. SYNONYM GROUPS, so a concept can be expressed several ways and still
     register once. Concepts are what we score, not strings.
  3. FIELD WEIGHTING, because a term in the title or the anchor text says far
     more about what a page is than the same term buried in the body.

This is still lexical, not semantic -- it cannot know that "upskilling" and
"capability building" are the same idea unless you tell it. But it is honest,
fast, offline, and configurable, and it no longer returns zero for an obvious
match.
"""

import re

_WORD = re.compile(r"[a-z][a-z'-]*", re.IGNORECASE)

# Field weights. Title/H1/anchor are where a page declares its subject.
WEIGHTS = {"title": 3.0, "h1": 3.0, "anchor": 3.0, "meta": 2.0, "body": 1.0}

# British -> American, plus a few irregulars that suffix-stripping cannot reach.
_NORMALISE = {
    "programme": "program", "programmes": "program",
    "organisation": "organization", "organisations": "organization",
    "organise": "organize", "organised": "organize", "organising": "organize",
    "centre": "center", "centres": "center",
    "center": "center", "centers": "center",
    "leader": "leader", "leaders": "leader",
    "manager": "manager", "managers": "manager",
    "trainer": "trainer", "trainers": "trainer",
    "licence": "license", "practise": "practice",
    "skilling": "skill", "upskilling": "upskill", "reskilling": "reskill",
    "learnt": "learn", "taught": "teach", "teaching": "teach",
    "people": "person", "staff": "employee", "staffs": "employee",
    "employees": "employee", "employers": "employer",
    "courses": "course", "classes": "class", "studies": "study",
    # Canonical forms that must NOT be stripped further.
    "organization": "organization", "organizations": "organization",
    "development": "development", "developments": "development",
    "management": "management", "leadership": "leadership",
    "certification": "certification", "certifications": "certification",
    "education": "education", "communication": "communication",
}

# Ordered longest-first. Note what is deliberately ABSENT: "ization",
# "isation" and "ational". Stripping those turns "organization" into "organ"
# and "educational" into "educ" -- not a stem, just damage.
# Also absent: "er", "ers" and "est". They look like plural/comparative
# suffixes but wreck ordinary nouns -- centre/center becomes "cent", leader
# becomes "lead", manager becomes "manag". Plain "s" already handles
# trainer/trainers and worker/workers, which is the case that mattered.
_SUFFIXES = ("iveness", "fulness", "ousness", "ments", "ment",
             "ings", "ing", "edly", "edness",
             "ies", "ied", "ed", "ly", "es", "s")


def stem(word: str) -> str:
    """
    Deliberately crude suffix stripper. A real Porter stemmer would be better,
    but it is a dependency and this is enough to collapse the inflections that
    actually cause false zeroes.
    """
    w = word.lower().strip("'-")
    # A word in the table is already canonical -- return it, do not keep
    # stripping. Continuing turned "organisations" into "organ", and worse,
    # stemmed it differently from plain "organization", which silently breaks
    # matching between the two spellings.
    if w in _NORMALISE:
        return _NORMALISE[w]
    if len(w) <= 4:
        return w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            base = w[: -len(suf)]
            if base in _NORMALISE:
                return _NORMALISE[base]
            # "ies" -> "y" reads better than a bare stem (studies -> study)
            if suf == "ies":
                return base + "y"
            return base
    return w


def tokens(text: str) -> list:
    return [stem(m.group()) for m in _WORD.finditer(text or "")]


def _concept_forms(concept, synonyms: dict) -> list:
    """Every phrase that counts as this concept, as stemmed token tuples."""
    forms = [concept] + list(synonyms.get(concept, []) or [])
    out = []
    for f in forms:
        toks = tuple(tokens(f))
        if toks:
            out.append(toks)
    return out


def _contains(hay: list, needle: tuple) -> bool:
    """Is this stemmed phrase present as a contiguous run?"""
    n = len(needle)
    if not n or n > len(hay):
        return False
    if n == 1:
        return needle[0] in hay
    first = needle[0]
    for i, t in enumerate(hay):
        if t == first and tuple(hay[i:i + n]) == needle:
            return True
    return False


def score(fields: dict, keywords, synonyms=None) -> dict:
    """
    fields: {"title":..., "h1":..., "meta":..., "anchor":..., "body":...}
    keywords: the concepts you care about
    synonyms: {concept: [other ways of saying it]}

    Returns:
      score      0-100, share of concepts found, weighted by where they appeared
      matched    concepts found, best field first
      where      {concept: field it was strongest in}
      missing    concepts not found at all
    """
    synonyms = synonyms or {}
    concepts = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    if not concepts:
        return {"score": 0, "matched": [], "where": {}, "missing": [], "detail": ""}

    toks = {f: tokens(v) for f, v in (fields or {}).items()}

    matched, where, total_weight = [], {}, 0.0
    for concept in concepts:
        forms = _concept_forms(concept, synonyms)
        best_field, best_w = None, 0.0
        for field, weight in WEIGHTS.items():
            hay = toks.get(field) or []
            if not hay:
                continue
            if any(_contains(hay, f) for f in forms):
                if weight > best_w:
                    best_field, best_w = field, weight
        if best_field:
            matched.append(concept)
            where[concept] = best_field
            total_weight += best_w

    # Normalise against the best achievable: every concept in a heavy field.
    ceiling = len(concepts) * WEIGHTS["title"]
    pct = int(round(100 * total_weight / ceiling)) if ceiling else 0
    # A concept found anywhere should never read as 0%, so floor a real match.
    if matched and pct == 0:
        pct = 1

    matched.sort(key=lambda c: -WEIGHTS.get(where.get(c, "body"), 0))
    detail = ", ".join(f"{c} ({where[c]})" for c in matched[:6])
    return {
        "score": min(100, pct),
        "matched": matched,
        "where": where,
        "missing": [c for c in concepts if c not in where],
        "detail": detail,
    }
