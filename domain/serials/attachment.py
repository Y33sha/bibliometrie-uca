"""Règles de rattachement d'un enregistrement source à sa revue, d'après la série qu'il décrit (`biblio.journal`).

Une revue correspond à un ISSN-L. L'ISSN-L d'un ISSN est celui du Sudoc, à défaut celui qu'OpenAlex donne avec cet ISSN, à défaut l'ISSN lui-même. Un enregistrement source rejoint la revue de l'ISSN-L de ses ISSN. Ses ISSN mènent parfois à plusieurs ISSN-L : le titre départage alors les revues. À défaut, il rejoint la revue de son identifiant OpenAlex, puis la revue désignée par son titre. Sans revue à ISSN de même titre, une série désignée par son titre rejoint la revue à ISSN de titre compatible d'un autre enregistrement source de la même publication.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from domain.entity_resolution import most_frequent
from domain.normalize import normalize_text
from domain.title_comparison import compatible_titles


@dataclass(frozen=True)
class NewSerial:
    """Revue à créer, désignée par l'ISSN-L ou le titre normalisé qui la fonde."""

    key: str
    title: str


type SerialRef = int | NewSerial
"""Revue existante, par identifiant, ou revue à créer."""


class KnownIssn(NamedTuple):
    """ISSN connu, avec l'ISSN-L de la table de l'ISSN International Centre et sa revue."""

    issnl: str | None
    serial_id: int | None


@dataclass(frozen=True)
class IssnlPlan:
    """ISSN-L de chaque ISSN connu, et revue de chaque ISSN-L tenu par une série ou par une revue."""

    issnl_of: dict[str, str]
    serial_of: dict[str, SerialRef]


def effective_issnl(
    issn: str,
    issnl: str | None,
    openalex_issnls: Mapping[str, str],
    replacement_issnl: str | None = None,
) -> str:
    """Renvoie l'ISSN-L de `issn` : `issnl`, lu dans la table de l'ISSN International Centre, à défaut celui de l'ISSN qui l'annule (`replacement_issnl`), à défaut celui d'OpenAlex, à défaut l'ISSN lui-même."""
    return issnl or replacement_issnl or openalex_issnls.get(issn) or issn


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


def plan_issnl_serials(
    issns: Mapping[str, KnownIssn],
    replaced_by: Mapping[str, str],
    openalex_issnls: Mapping[str, str],
    series: Iterable[tuple[Sequence[str], str | None]],
) -> IssnlPlan:
    """Renvoie l'ISSN-L de chaque ISSN connu (`effective_issnl`) et la revue de chaque ISSN-L.

    Un ISSN-L reçoit une revue quand une série le cite, ou quand un de ses ISSN a une revue. Cette revue est celle de la ligne de l'ISSN-L, à défaut la plus fréquente parmi ses ISSN, à défaut une revue à créer. Une revue va à un seul ISSN-L. Une revue à créer prend le titre le plus fréquent des séries de l'ISSN-L, à défaut l'ISSN-L.

    Args:
        replaced_by: ISSN qui annule chaque ISSN annulé.
        series: ISSN valides et titre de chaque série décrite par un enregistrement source.
    """

    def own_issnl(issn: str) -> str:
        known = issns.get(issn)
        return effective_issnl(issn, known.issnl if known else None, openalex_issnls)

    issnl_of = {
        issn: effective_issnl(
            issn,
            known.issnl,
            openalex_issnls,
            own_issnl(replaced_by[issn]) if issn in replaced_by else None,
        )
        for issn, known in issns.items()
    }
    members: dict[str, list[str]] = {}
    for issn, issnl in issnl_of.items():
        members.setdefault(issnl, []).append(issn)
    titles: dict[str, Counter[str]] = {}
    for series_issns, title in series:
        if title:
            for issnl in {issnl_of[i] for i in series_issns if i in issnl_of}:
                titles.setdefault(issnl, Counter())[title] += 1
    held = set(titles) | {
        issnl for issnl, group in members.items() if any(issns[i].serial_id for i in group)
    }

    serial_of: dict[str, SerialRef] = {}
    claimed: set[int] = set()
    # Une revue va d'abord à l'ISSN-L dont la ligne la désigne, puis au plus fréquent parmi ses ISSN.
    for issnl in sorted(held):
        own = issns[issnl].serial_id if issnl in issns else None
        if own is not None and own not in claimed:
            serial_of[issnl] = own
            claimed.add(own)
    for issnl in sorted(held - set(serial_of)):
        votes = Counter(
            serial_id
            for i in members.get(issnl, [])
            if (serial_id := issns[i].serial_id) is not None and serial_id not in claimed
        )
        if votes:
            serial_id = most_frequent(votes)
            serial_of[issnl] = serial_id
            claimed.add(serial_id)
        else:
            title = most_frequent(titles[issnl]) if issnl in titles else issnl
            serial_of[issnl] = NewSerial(f"issnl:{issnl}", title)
    return IssnlPlan(issnl_of, serial_of)


def choose_issnl(title: str | None, candidates: Mapping[str, str]) -> str | None:
    """Renvoie l'ISSN-L de l'enregistrement source parmi `candidates`, ou `None` s'ils restent indiscernables.

    Un seul candidat l'emporte d'office. Parmi plusieurs, l'emporte la seule revue de même titre normalisé que `title`, à défaut la seule de titre compatible (`compatible_titles`). « INRA productions animales » est compatible avec « INRAE Productions Animales », « INRAE productions animales » est identique.

    Args:
        candidates: titre de la revue de chaque ISSN-L candidat.
    """
    if len(candidates) == 1:
        return next(iter(candidates))
    if not title:
        return None
    key = normalize_text(title)
    matches = [issnl for issnl, name in candidates.items() if normalize_text(name) == key] or [
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
