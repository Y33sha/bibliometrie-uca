"""Lecture des titres de conteneurs : revue, collection, livre ou volume d'actes."""

import re

# Année d'une édition de congrès (« NuFACT 2022 ») : de 1800 à 2099. Une lettre peut la précéder : « Goldschmidt2023 », « PoS(ICRC2021) ».
# Précédée d'un chiffre, d'un trait ou d'une barre oblique, elle fait partie d'un nombre ou d'une plage (« 11812 », « 2019/2020 »).
# Suivie d'une lettre, d'un chiffre, d'un trait ou d'une parenthèse ouvrante, elle fait partie d'un code ou date un fascicule (« VTC2025-Spring », « 2018(7) »).
_EVENT_YEAR = re.compile(r"(?<![\d\-–/])(?:1[89]\d\d|20\d\d)(?![\w\-–/(])")
_YEAR_RANGE = re.compile(r"(\d{4})\s*[-–]\s*(\d{4})")
_JOURNAL_WORD = re.compile(r"\bjournal\b", re.IGNORECASE)
_PROCEEDINGS = re.compile(r"\bproceedings\b", re.IGNORECASE)
_EBOOK_PLATFORM = re.compile(r"\seBooks$")
_LEARNED_BODY = re.compile(r"\b(?:societ(?:y|ies)|academ(?:y|ies)|institutions?)\b", re.IGNORECASE)
_LEGAL_PROCEEDINGS = re.compile(
    r"\b(?:criminal|civil|legal|judicial|court|insolvency|bankruptcy|arbitral|arbitration|administrative|disciplinary)\s+proceedings\b",
    re.IGNORECASE,
)


def names_proceedings(title: str) -> bool:
    """Vrai si le titre annonce des actes : « Proceedings of the Thirtieth International Joint Conference on Artificial Intelligence ».

    Une société savante, une académie ou une institution publient des revues ainsi nommées : « Proceedings of the National Academy of Sciences », « Proceedings of the Institution of Civil Engineers ». Leur titre ne compte pas, pas plus qu'une procédure judiciaire : « Third Parties in Criminal Proceedings ».

    Seul le mot anglais compte : en sciences humaines, les chapitres d'« Actes du colloque » restent des chapitres.
    """
    return (
        bool(_PROCEEDINGS.search(title))
        and not _LEARNED_BODY.search(title)
        and not _LEGAL_PROCEEDINGS.search(title)
    )


def names_ebook_platform(title: str) -> bool:
    """Vrai si le titre est celui donné par OpenAlex à la plateforme d'ebooks d'un éditeur : « ENS Éditions eBooks ». Une plateforme d'ebooks n'est le conteneur d'aucun document."""
    return bool(_EBOOK_PLATFORM.search(title))


def names_a_dated_event(title: str) -> bool:
    """Vrai si le titre nomme une édition datée : « NuFACT 2022 », « 2024 IEEE SENSORS », « Goldschmidt2023 abstracts ».

    Ne comptent pas : une période (« Poetry, 1960–2015 »), une année seule entre parenthèses (« 22 Seiten (2023). »), un titre qui contient le mot « journal » (« Journal of high energy physics 2018(7) »).
    """
    if _JOURNAL_WORD.search(title):
        return False
    title = _YEAR_RANGE.sub(lambda m: " " if m.group(1) < m.group(2) else m.group(0), title)
    return any(
        not (title[m.start() - 1 : m.start()] == "(" and title[m.end() : m.end() + 1] == ")")
        for m in _EVENT_YEAR.finditer(title)
    )
