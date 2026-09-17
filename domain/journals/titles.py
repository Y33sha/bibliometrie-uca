"""Comparaison et lecture des titres de revues."""

import re

from domain.normalize import normalize_text

# Année d'édition : ni précédée d'un chiffre ou d'un trait (« 1-26 », « 1812 »), ni suivie d'une lettre, d'un
# trait ou d'une parenthèse ouvrante (« 2018(7) », numéro de fascicule). Une lettre peut la précéder :
# « Goldschmidt2023 », « PoS(ICRC2021) ».
_YEAR = re.compile(r"(?<![\d\-–/])(?:1[89]\d\d|20\d\d)(?![\w\-–/(])")
_YEAR_RANGE = re.compile(r"(\d{4})\s*[-–]\s*(\d{4})")
_JOURNAL = re.compile(r"\bjournal\b", re.IGNORECASE)
_PROCEEDINGS = re.compile(r"\bproceedings\b", re.IGNORECASE)
_LEARNED_BODY = re.compile(r"\b(?:societ(?:y|ies)|academ(?:y|ies)|institutions?)\b", re.IGNORECASE)


def names_proceedings(title: str) -> bool:
    """Indique si le titre annonce des actes : « Proceedings of the Thirtieth International Joint Conference on Artificial Intelligence ».

    Une société savante, une académie ou une institution publient des revues ainsi nommées : « Proceedings of the National Academy of Sciences », « Proceedings of the Institution of Civil Engineers ». Leur titre ne compte pas.
    """
    return bool(_PROCEEDINGS.search(title)) and not _LEARNED_BODY.search(title)


def names_a_dated_event(title: str) -> bool:
    """Indique si le titre nomme une édition datée : « NuFACT 2022 », « 2024 IEEE SENSORS », « Goldschmidt2023 abstracts ».

    Ne comptent pas : une période (« Poetry, 1960–2015 »), une année seule entre parenthèses (« 22 Seiten (2023). »), un titre qui contient le mot « journal » (« Journal of high energy physics 2018(7) »).
    """
    if _JOURNAL.search(title):
        return False
    title = _YEAR_RANGE.sub(lambda m: " " if m.group(1) < m.group(2) else m.group(0), title)
    return any(
        not (title[m.start() - 1 : m.start()] == "(" and title[m.end() : m.end() + 1] == ")")
        for m in _YEAR.finditer(title)
    )


def nested_titles(a: str | None, b: str | None) -> bool:
    """Les mots d'un titre sont tous dans l'autre : « BMJ » et « BMJ British Medical Journal », pas « Physical review C » et « Physical review D »."""
    if not a or not b:
        return False
    words_a, words_b = set(normalize_text(a).split()), set(normalize_text(b).split())
    return bool(words_a and words_b) and (words_a <= words_b or words_b <= words_a)
