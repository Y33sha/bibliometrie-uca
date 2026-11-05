"""Règles de rattachement d'un enregistrement source à sa revue, d'après la série qu'il décrit (`biblio.journal`).

Une revue correspond à un ISSN-L. L'ISSN-L d'un ISSN est celui du Sudoc, à défaut celui qu'OpenAlex donne avec cet ISSN, à défaut l'ISSN lui-même. Un enregistrement source rejoint la revue de l'ISSN-L de ses ISSN. Ses ISSN mènent parfois à plusieurs ISSN-L : le titre départage alors les revues. À défaut, il rejoint la revue de son identifiant OpenAlex, puis la revue désignée par son titre. Sans revue à ISSN de même titre, une série désignée par son titre rejoint la revue à ISSN de titre compatible d'un autre enregistrement source de la même publication.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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


class SeriesMention(NamedTuple):
    """Série décrite par un enregistrement source."""

    record_id: int
    publication_id: int | None
    """Publication de l'enregistrement source au run précédent."""
    publisher_id: int | None
    title: str | None
    openalex_id: str | None
    issns: tuple[str, ...]
    """ISSN valides."""


class KnownSerial(NamedTuple):
    """Revue existante."""

    title: str
    title_normalized: str
    publisher_id: int | None
    openalex_id: str | None


@dataclass
class SerialAttachment:
    """Revue de chaque enregistrement source, et compte des rattachements par voie."""

    serial_of: dict[int, SerialRef | None] = field(default_factory=dict)
    by_way: Counter[str] = field(default_factory=Counter)


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

    id: SerialRef
    publisher_id: int | None


def match_by_title(publisher_id: int | None, serials: Sequence[TitledSerial]) -> SerialRef | None:
    """Renvoie la seule revue à ISSN de même titre, quel que soit son éditeur. Parmi plusieurs, renvoie la seule de l'éditeur `publisher_id`, ou `None`.

    Args:
        serials: revues à ISSN de même titre normalisé que la série.
    """
    if len(serials) == 1:
        return serials[0].id
    same = [s.id for s in serials if publisher_id is not None and s.publisher_id == publisher_id]
    return same[0] if len(same) == 1 else None


def match_in_publication(
    title: str | None, publication_serials: Mapping[SerialRef, str]
) -> SerialRef | None:
    """Renvoie la seule revue à ISSN de titre compatible avec `title` (`compatible_titles`) parmi celles de la publication, ou `None` : « JHEP » rejoint « Journal of High Energy Physics ».

    Args:
        publication_serials: titre de chaque revue à ISSN des autres enregistrements sources de la publication.
    """
    if not title:
        return None
    matches = [s for s, name in publication_serials.items() if compatible_titles(title, name)]
    return matches[0] if len(matches) == 1 else None


def plan_record_serials(
    mentions: Sequence[SeriesMention],
    issnl_plan: IssnlPlan,
    serials: Mapping[int, KnownSerial],
    decisions: Mapping[str, int],
) -> SerialAttachment:
    """Renvoie la revue de l'enregistrement source de chaque série de `mentions`.

    Un enregistrement source rejoint la revue de l'ISSN-L de ses ISSN (`choose_issnl`), à défaut celle de son identifiant OpenAlex, à défaut celle de son titre. Pour le titre, dans l'ordre : décision de l'administration, seule revue à ISSN de même titre (`match_by_title`), revue à ISSN de titre compatible d'un autre enregistrement source de sa publication (`match_in_publication`), plus ancienne revue sans ISSN de même titre, revue sans ISSN à créer. Une série sans titre reste sans revue.

    Les revues à ISSN sont celles des ISSN-L de `issnl_plan`. Une revue sans ISSN à créer prend le titre le plus fréquent de ses séries.

    Args:
        serials: revues existantes, par identifiant.
        decisions: revue décidée par l'administration pour chaque titre normalisé.
    """
    serial_of_issnl = issnl_plan.serial_of
    with_issn = set(serial_of_issnl.values())

    def title_of(serial: SerialRef) -> str:
        return serial.title if isinstance(serial, NewSerial) else serials[serial].title

    by_openalex = {s.openalex_id: serial_id for serial_id, s in serials.items() if s.openalex_id}
    by_title = _with_issn_by_title(with_issn, serials)
    result = SerialAttachment()
    # Séries désignées par leur seul titre, sans revue à ISSN de ce titre : série, titre et titre normalisé.
    title_only: list[tuple[SeriesMention, str, str]] = []
    for m in mentions:
        candidates = {
            issnl: title_of(serial_of_issnl[issnl])
            for issnl in {issnl_plan.issnl_of.get(i, i) for i in m.issns}
            if issnl in serial_of_issnl
        }
        if candidates and (issnl := choose_issnl(m.title, candidates)) is not None:
            result.serial_of[m.record_id] = serial_of_issnl[issnl]
            result.by_way["issn"] += 1
            continue
        if m.openalex_id and m.openalex_id in by_openalex:
            result.serial_of[m.record_id] = by_openalex[m.openalex_id]
            result.by_way["openalex"] += 1
            continue
        title_normalized = normalize_text(m.title or "")
        if not title_normalized:
            result.serial_of[m.record_id] = None
            result.by_way["unattached"] += 1
            continue
        found = decisions.get(title_normalized) or match_by_title(
            m.publisher_id, by_title.get(title_normalized, [])
        )
        if found is None:
            title_only.append((m, m.title or "", title_normalized))
            continue
        result.serial_of[m.record_id] = found
        result.by_way["title"] += 1

    publication_serials: dict[int, dict[SerialRef, str]] = {}
    for m in mentions:
        serial = result.serial_of.get(m.record_id)
        if m.publication_id is not None and serial is not None and serial in with_issn:
            publication_serials.setdefault(m.publication_id, {})[serial] = title_of(serial)
    _attach_title_only(
        title_only, result, publication_serials, _oldest_without_issn(serials, with_issn)
    )
    return result


def _with_issn_by_title(
    with_issn: Iterable[SerialRef], serials: Mapping[int, KnownSerial]
) -> dict[str, list[TitledSerial]]:
    """Renvoie les revues à ISSN par titre normalisé, candidates au rattachement par titre."""
    by_title: dict[str, list[TitledSerial]] = {}
    for serial in with_issn:
        if isinstance(serial, NewSerial):
            by_title.setdefault(normalize_text(serial.title), []).append(TitledSerial(serial, None))
        else:
            known = serials[serial]
            by_title.setdefault(known.title_normalized, []).append(
                TitledSerial(serial, known.publisher_id)
            )
    return by_title


def _oldest_without_issn(
    serials: Mapping[int, KnownSerial], with_issn: set[SerialRef]
) -> dict[str, int]:
    """Renvoie la plus ancienne revue sans ISSN de chaque titre normalisé."""
    oldest: dict[str, int] = {}
    for serial_id in sorted(serials):
        if serial_id not in with_issn:
            oldest.setdefault(serials[serial_id].title_normalized, serial_id)
    return oldest


def _attach_title_only(
    title_only: Sequence[tuple[SeriesMention, str, str]],
    result: SerialAttachment,
    publication_serials: Mapping[int, Mapping[SerialRef, str]],
    without_issn: Mapping[str, int],
) -> None:
    """Rattache dans `result` les séries désignées par leur seul titre : revue à ISSN de titre compatible de leur publication, plus ancienne revue sans ISSN de même titre, à défaut revue à créer.

    Args:
        title_only: série, titre et titre normalisé.
        publication_serials: titre des revues à ISSN de chaque publication.
        without_issn: plus ancienne revue sans ISSN de chaque titre normalisé.
    """
    new_titles: dict[str, Counter[str]] = {}
    for m, title, title_normalized in title_only:
        in_publication = (
            publication_serials.get(m.publication_id, {}) if m.publication_id is not None else {}
        )
        found = match_in_publication(title, in_publication) or without_issn.get(title_normalized)
        if found is None:
            new_titles.setdefault(title_normalized, Counter())[title] += 1
        result.serial_of[m.record_id] = found
        result.by_way["title"] += 1
    new_serials = {
        key: NewSerial(f"title:{key}", most_frequent(titles)) for key, titles in new_titles.items()
    }
    for m, _, title_normalized in title_only:
        if result.serial_of[m.record_id] is None:
            result.serial_of[m.record_id] = new_serials[title_normalized]
