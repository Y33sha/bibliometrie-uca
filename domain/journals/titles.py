"""Comparaison et lecture des titres de revues."""

import re
from collections.abc import Sequence
from functools import cache
from typing import NamedTuple

from domain.normalize import normalize_text

# Année d'une édition de congrès (« NuFACT 2022 ») : de 1800 à 2099. Précédée d'un chiffre, d'un trait ou d'une
# barre oblique, elle fait partie d'un nombre plus long ou d'une plage (« 11812 », « 101-1812 », « 2019/2020 »).
# Suivie d'une lettre, d'un chiffre, d'un trait ou d'une parenthèse ouvrante, elle fait partie d'un code ou date
# le fascicule d'une revue (« VTC2025-Spring », « 2018(7) »). Une lettre peut la précéder : « Goldschmidt2023 »,
# « PoS(ICRC2021) ».
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


# Mots qu'une abréviation de titre laisse tomber. Une lettre isolée compte : elle distingue les sections
# d'une revue (« Physical Review A », « Physical Review D »).
_STOP_WORDS = frozenset(
    {"an", "and", "at", "de", "des", "du", "en", "et", "for", "in", "la", "le", "les", "of", "on", "the", "to"}
)  # fmt: skip
# Article élidé : « d’histoire », « L'Archétype ».
_ELISION = re.compile(r"\b[dlDL]['’]")
_WORD = re.compile(r"[^\W_]+")
# Un acronyme compte au plus autant de lettres, dont deux capitales : « JINST », « UBB », « HiHEP ».
_ACRONYM_MAX = 5
# Titres parallèles d'une même revue : « JCSM/Journal of Clinical Sleep Medicine », « Arthritis Care & Research
# = Arthritis Care and Research ».
_PARALLEL_TITLES = re.compile(r"[/=]")
# Début d'un sous-titre ou d'un complément : « Notos - Espaces de la création », « Medicine (Baltimore) »,
# « Costellazioni : Rivista di lingue e letterature ».
_SUBTITLE = re.compile(r"\s[-–—]\s|[:(\[]")


class _Word(NamedTuple):
    """Mot significatif d'un titre, normalisé, et s'il s'écrit comme un acronyme."""

    text: str
    acronym: bool


def compatible_titles(a: str, b: str) -> bool:
    """Les deux titres désignent la même revue : l'un abrège l'autre, ou ils diffèrent seulement par la casse, l'accentuation, la ponctuation et les mots vides.

    Un mot abrégé est le début du mot complet (« Phys » pour « Physical ») ou sa contraction : même initiale, lettres dans l'ordre (« Rept » pour « Reports »). Un acronyme se découpe en débuts de mots successifs (« JINST » pour « Journal of Instrumentation »). Tous les mots du titre long sont abrégés, dans l'ordre : « Microscopy » n'abrège pas « Microscopy Today ». Chaque titre parallèle, séparé par `/` ou `=`, et chaque titre privé de son sous-titre sont essayés à leur tour.
    """
    return any(
        [w.text for w in x] == [w.text for w in y] or _abbreviates(x, y) or _abbreviates(y, x)
        for x in _variants(a)
        for y in _variants(b)
    )


def _variants(title: str) -> list[tuple[_Word, ...]]:
    """Le titre, ses titres parallèles, et chacun d'eux privé de son sous-titre."""
    parts = [title, *_PARALLEL_TITLES.split(title)]
    candidates = [*parts, *(_SUBTITLE.split(part, maxsplit=1)[0] for part in parts)]
    return [words for words in dict.fromkeys(_words(c) for c in candidates) if words]


def _words(title: str) -> tuple[_Word, ...]:
    words: list[_Word] = []
    for raw in _WORD.findall(_ELISION.sub(" ", title)):
        acronym = len(raw) <= _ACRONYM_MAX and sum(c.isupper() for c in raw) >= 2
        words.extend(
            _Word(text, acronym) for text in normalize_text(raw).split() if text not in _STOP_WORDS
        )
    return tuple(words)


def _abbreviates(short: Sequence[_Word], full: Sequence[_Word]) -> bool:
    """Les mots du titre court abrègent, dans l'ordre, tous ceux du titre long, et un mot au moins y est raccourci."""
    targets = [w.text for w in full]

    @cache
    def matches_from(i: int, start: int, j: int, shortened: bool) -> bool:
        """Le mot `i` du titre court, lu depuis sa lettre `start`, face au mot `j` du titre long."""
        if i == len(short):
            return shortened and j == len(targets)
        if j == len(targets):
            return False
        word = short[i]
        target = targets[j]
        if start == 0 and _abbreviates_word(word.text, target):
            if matches_from(i + 1, 0, j + 1, shortened or len(word.text) < len(target)):
                return True
        if not word.acronym:
            return False
        # Un acronyme couvre plusieurs mots : une tranche de ses lettres commence chacun d'eux.
        rest = word.text[start:]
        longest = len(rest) if start else len(rest) - 1
        return any(
            target.startswith(rest[:n])
            and (
                matches_from(i + 1, 0, j + 1, True)
                if n == len(rest)
                else matches_from(i, start + n, j + 1, True)
            )
            for n in range(1, longest + 1)
        )

    return matches_from(0, 0, 0, False)


def _abbreviates_word(short: str, full: str) -> bool:
    """Début du mot (« phys », « physical ») ou contraction : même initiale, lettres dans l'ordre (« rept », « reports »)."""
    if full.startswith(short):
        return True
    letters = iter(full)
    return short[0] == full[0] and all(letter in letters for letter in short)
