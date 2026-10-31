"""Règles de rattachement d'un enregistrement source à sa revue, d'après la série qu'il décrit (`biblio.journal`).

Une revue correspond à un ISSN-L. L'ISSN-L d'un ISSN est celui du Sudoc, à défaut celui qu'OpenAlex donne avec cet ISSN, à défaut l'ISSN lui-même. Un enregistrement source rejoint la revue de l'ISSN-L de ses ISSN. Ses ISSN mènent parfois à plusieurs ISSN-L : il rejoint alors la seule revue de titre compatible avec le sien. À défaut, il rejoint la revue de son identifiant OpenAlex, puis la revue désignée par son titre.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from domain.serials.titles import compatible_titles


def effective_issnl(issn: str, sudoc_issnl: str | None, openalex_issnls: Mapping[str, str]) -> str:
    """Renvoie l'ISSN-L de `issn` : celui du Sudoc, à défaut celui d'OpenAlex, à défaut l'ISSN lui-même."""
    return sudoc_issnl or openalex_issnls.get(issn) or issn


def openalex_issnls(series: Iterable[tuple[str, Sequence[str]]]) -> dict[str, str]:
    """Renvoie l'ISSN-L qu'OpenAlex donne à chaque ISSN, le plus fréquent en cas de désaccord.

    Args:
        series: `(ISSN-L, ISSN)` de chaque série décrite par OpenAlex.
    """
    votes: dict[str, Counter[str]] = {}
    for issnl, issns in series:
        for issn in (issnl, *issns):
            votes.setdefault(issn, Counter())[issnl] += 1
    return {issn: most_frequent(counter) for issn, counter in votes.items()}


def most_frequent[T: str | int](counter: Counter[T]) -> T:
    """Renvoie la valeur la plus fréquente ; à égalité, la plus petite."""
    best = max(counter.values())
    return min(value for value, n in counter.items() if n == best)


def choose_issnl(title: str | None, candidates: Mapping[str, str]) -> str | None:
    """Renvoie l'ISSN-L de l'enregistrement source parmi `candidates`, ou `None` s'ils restent indiscernables.

    Un seul candidat l'emporte d'office. Parmi plusieurs, seul compte celui dont la revue a un titre compatible avec `title` (`compatible_titles`).

    Args:
        candidates: titre de la revue de chaque ISSN-L candidat.
    """
    if len(candidates) == 1:
        return next(iter(candidates))
    if not title:
        return None
    compatible = [issnl for issnl, name in candidates.items() if compatible_titles(title, name)]
    return compatible[0] if len(compatible) == 1 else None


@dataclass(frozen=True, slots=True)
class TitledSerial:
    """Revue à ISSN candidate au rattachement par titre."""

    id: int
    publisher_id: int | None


def match_by_title(publisher_id: int | None, serials: Sequence[TitledSerial]) -> int | None:
    """Renvoie la seule revue à ISSN de même titre et d'éditeur compatible, ou `None`. Deux éditeurs sont compatibles s'ils sont égaux, ou si l'un manque.

    Args:
        serials: revues à ISSN de même titre normalisé que la série.
    """
    matches = [
        s.id
        for s in serials
        if s.publisher_id is None or publisher_id is None or s.publisher_id == publisher_id
    ]
    return matches[0] if len(matches) == 1 else None
