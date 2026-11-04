"""Comparaison de titres et de noms : emboîtement des mots, abréviation."""

import re
from collections.abc import Sequence
from functools import cache
from typing import NamedTuple

from domain.normalize import normalize_text


def nested_titles(a: str | None, b: str | None) -> bool:
    """Vrai si les mots d'un titre sont tous dans l'autre : « BMJ » et « BMJ British Medical Journal », pas « Physical review C » et « Physical review D »."""
    if not a or not b:
        return False
    words_a, words_b = set(normalize_text(a).split()), set(normalize_text(b).split())
    return bool(words_a and words_b) and (words_a <= words_b or words_b <= words_a)


_STOP_WORDS = frozenset(
    {"an", "and", "at", "de", "des", "du", "en", "et", "for", "in", "la", "le", "les", "of", "on", "the", "to"}
)  # fmt: skip
"""Mots qu'une abréviation de titre laisse tomber. Une lettre isolée compte : elle distingue les sections d'une revue (« Physical Review A », « Physical Review D »)."""
_ELISION = re.compile(r"\b[dlDL]['’]")
"""Article élidé : « d’histoire », « L'Archétype »."""
_WORD = re.compile(r"[^\W_]+")
_ACRONYM_MAX = 5
"""Un acronyme compte au plus autant de lettres, dont deux capitales : « JINST », « UBB », « HiHEP »."""
_PARALLEL_TITLES = re.compile(r"[/=]")
"""Titres parallèles : « JCSM/Journal of Clinical Sleep Medicine », « Arthritis Care & Research = Arthritis Care and Research »."""
_SUBTITLE = re.compile(r"\s[-–—]\s|[:(\[]")
"""Début d'un sous-titre ou d'un complément : « Notos - Espaces de la création », « Medicine (Baltimore) », « Costellazioni : Rivista di lingue e letterature »."""


class _Word(NamedTuple):
    """Mot significatif d'un titre, normalisé."""

    text: str
    acronym: bool
    """Le mot s'écrit comme un acronyme."""


def compatible_titles(a: str, b: str) -> bool:
    """Vrai si les deux titres désignent la même entité : l'un abrège l'autre, ou ils diffèrent seulement par la casse, l'accentuation, la ponctuation et les mots vides.

    Un mot abrégé est le début du mot complet (« Phys » pour « Physical ») ou sa contraction : même initiale, lettres dans l'ordre (« Rept » pour « Reports »). Un acronyme se découpe en débuts de mots successifs (« JINST » pour « Journal of Instrumentation »). Tous les mots du titre long sont abrégés, dans l'ordre : « Microscopy » n'abrège pas « Microscopy Today ». Chaque titre parallèle, séparé par `/` ou `=`, et chaque titre privé de son sous-titre sont essayés à leur tour.
    """
    return any(
        [w.text for w in x] == [w.text for w in y] or _abbreviates(x, y) or _abbreviates(y, x)
        for x in _variants(a)
        for y in _variants(b)
    )


def _variants(title: str) -> list[tuple[_Word, ...]]:
    """Renvoie le titre, ses titres parallèles, et chacun d'eux privé de son sous-titre."""
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
    """Vrai si les mots du titre court abrègent, dans l'ordre, tous ceux du titre long, et un mot au moins y est raccourci."""
    targets = [w.text for w in full]

    @cache
    def matches_from(i: int, start: int, j: int, shortened: bool) -> bool:
        """Vrai si la suite du titre court abrège la suite du titre long : le mot `i`, lu depuis sa lettre `start`, face au mot `j`."""
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
    """Vrai si `short` est le début de `full` (« phys », « physical ») ou sa contraction : même initiale, lettres dans l'ordre (« rept », « reports »)."""
    if full.startswith(short):
        return True
    letters = iter(full)
    return short[0] == full[0] and all(letter in letters for letter in short)
