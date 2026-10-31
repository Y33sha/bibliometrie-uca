"""Règles de rattachement d'un enregistrement source à sa revue, d'après la série qu'il décrit (`biblio.journal`).

Une revue correspond à un ISSN-L. L'ISSN-L d'un ISSN est celui du Sudoc, à défaut celui qu'OpenAlex donne avec cet ISSN, à défaut l'ISSN lui-même. Un enregistrement source rejoint la revue de l'ISSN-L de ses ISSN. Ses ISSN mènent parfois à plusieurs ISSN-L : le titre départage alors les revues. À défaut, il rejoint la revue de son identifiant OpenAlex, puis la revue désignée par son titre. Sans revue à ISSN de même titre, une série désignée par son titre rejoint la revue à ISSN de titre compatible d'un autre enregistrement source de la même publication.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from domain.normalize import normalize_text, to_plain_text
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


def title_key(title: str | None) -> str:
    """Renvoie la forme de comparaison d'un titre de série reçu d'une source."""
    return normalize_text(to_plain_text(title)) if title else ""


def choose_issnl(title: str | None, candidates: Mapping[str, str]) -> str | None:
    """Renvoie l'ISSN-L de l'enregistrement source parmi `candidates`, ou `None` s'ils restent indiscernables.

    Un seul candidat l'emporte d'office. Parmi plusieurs, l'emporte la seule revue de même titre normalisé que `title`, à défaut la seule de titre compatible (`compatible_titles`) : « INRA productions animales » est compatible avec « INRAE Productions Animales », « INRAE productions animales » est identique.

    Args:
        candidates: titre de la revue de chaque ISSN-L candidat.
    """
    if len(candidates) == 1:
        return next(iter(candidates))
    if not title:
        return None
    key = title_key(title)
    matches = [issnl for issnl, name in candidates.items() if title_key(name) == key] or [
        issnl for issnl, name in candidates.items() if compatible_titles(title, name)
    ]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True, slots=True)
class TitledSerial:
    """Revue à ISSN candidate au rattachement par titre."""

    id: int
    publisher_id: int | None


def match_by_title(publisher_id: int | None, serials: Sequence[TitledSerial]) -> int | None:
    """Renvoie la seule revue à ISSN de même titre, quel que soit son éditeur. Parmi plusieurs, renvoie la seule de l'éditeur `publisher_id`, ou `None`.

    Args:
        serials: revues à ISSN de même titre normalisé que la série.
    """
    if len(serials) == 1:
        return serials[0].id
    same = [s.id for s in serials if publisher_id is not None and s.publisher_id == publisher_id]
    return same[0] if len(same) == 1 else None


def match_in_publication(title: str | None, publication_serials: Mapping[int, str]) -> int | None:
    """Renvoie la seule revue à ISSN de titre compatible avec `title` (`compatible_titles`) parmi celles de la publication, ou `None` : « JHEP » rejoint « Journal of High Energy Physics ».

    Args:
        publication_serials: titre de chaque revue à ISSN des autres enregistrements sources de la publication.
    """
    if not title:
        return None
    matches = [s for s, name in publication_serials.items() if compatible_titles(title, name)]
    return matches[0] if len(matches) == 1 else None
