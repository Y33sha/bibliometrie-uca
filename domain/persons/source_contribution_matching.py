"""Matching des contributions sources aux personnes, par identifiant ou par nom."""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.persons.name_matching import (
    first_name_initials,
    full_first_name_extends,
    initials_extend,
    names_compatible,
)


class IdentifiedPerson(NamedTuple):
    """Personne désignée par une valeur d'identifiant, avec son nom normalisé, qui corrobore l'identifiant."""

    person_id: int
    last_name: str
    first_name: str
    human_attribution: bool = False
    """L'attribution est confirmée par l'administration ou authentifiée par le chercheur (`HUMAN_ATTRIBUTION_STATUSES`)."""


ORCID_MATCH_SOURCES = frozenset({"crossref", "datacite", "openalex", "hal", "inspire"})
"""Sources dont l'ORCID sert au rattachement. L'auteur le dépose auprès de l'éditeur (Crossref, et OpenAlex qui le recopie), de DataCite ou de HAL. Les équipes d'INSPIRE-HEP vérifient ses listes d'auteurs. Dans WoS et ScanR, l'ORCID résulte d'un matching automatique."""

STRONG_PERSON_IDENTIFIER_TYPES: tuple[PersonIdentifierType, ...] = (
    PersonIdentifierType.ORCID,
    PersonIdentifierType.IDREF,
    PersonIdentifierType.HAL_PERSON_ID,
)
"""Identifiants qui rattachent une contribution source à une personne sans forme de nom : hors périmètre, et pour l'entrée dans le périmètre d'une personne qui a une fiche RH."""


def trusted_identifier(id_type: str, source: str) -> bool:
    """Vrai si l'identifiant d'une contribution source sert au rattachement. Un ORCID sert seulement s'il vient de `ORCID_MATCH_SOURCES`."""
    return id_type != PersonIdentifierType.ORCID or source in ORCID_MATCH_SOURCES


class Namesake(NamedTuple):
    """Personne d'un nom de famille donné, candidate au rattachement par initiales."""

    person_id: int
    last_name: str
    first_name: str
    conflicting: bool = False
    """Vrai pour une personne au prénom réduit, à qui ses contributions sources donnent plusieurs prénoms pleins. Le rattachement par initiales l'écarte pour un prénom plein."""
    hr_record: bool = False
    """La personne a une fiche RH : son prénom vient du SI RH, jamais réduit à des initiales."""

    @property
    def matching_first_name(self) -> str:
        """Prénom lu par le rattachement par initiales. Un prénom du SI RH, écrit en capitales, passe en minuscules : deux ou trois capitales accolées (« LEA ») ne s'y lisent pas comme des initiales (`first_name_initials`)."""
        return self.first_name.lower() if self.hr_record else self.first_name


def _full_namesakes(initials: tuple[str, ...], namesakes: Iterable[Namesake]) -> list[int]:
    """Renvoie les personnes au prénom plein dont les initiales commencent par `initials`."""
    return [
        n.person_id for n in namesakes if full_first_name_extends(initials, n.matching_first_name)
    ]


def _compatible_namesakes(contributor_first_name: str, namesakes: Sequence[Namesake]) -> list[int]:
    """Renvoie les personnes de même nom de famille désignées par les initiales d'une contribution source.

    - Prénom réduit (« A. ») : toute personne dont les initiales du prénom commencent par celles de la contribution source (« Abdul-Majeed », « A. M. »).
    - Prénom plein (« Abdellah ») : toute personne au prénom réduit dont les initiales commencent celles de la contribution source (« A. »). Sont exclues les personnes `conflicting`, et celles dont les initiales commencent le prénom plein d'une autre personne de même nom.
    - Sans prénom : aucune.
    """
    contributor_initials = first_name_initials(contributor_first_name)
    if contributor_initials is not None:
        return [
            n.person_id
            for n in namesakes
            if initials_extend(contributor_initials, n.matching_first_name)
        ]
    if not normalize_text(contributor_first_name):
        return []
    candidates = []
    for n in namesakes:
        initials = first_name_initials(n.matching_first_name)
        if (
            initials is None
            or n.conflicting
            or not initials_extend(initials, contributor_first_name)
        ):
            continue
        if not _full_namesakes(initials, namesakes):
            candidates.append(n.person_id)
    return candidates


def compatible_persons(
    source_contribution: ContributorName, namesakes_by_last_name: Mapping[str, Sequence[Namesake]]
) -> list[int]:
    """Renvoie les personnes désignées par les initiales de la contribution source, pour chacun de ses découpages en nom et prénom, sans doublon.

    Args:
        namesakes_by_last_name: personnes par nom de famille normalisé.
    """
    found: list[int] = []
    for last, first in source_contribution.splits():
        namesakes = namesakes_by_last_name.get(normalize_text(last), ())
        for person_id in _compatible_namesakes(first, namesakes):
            if person_id not in found:
                found.append(person_id)
    return found


def attested_full_first_names(
    last_name: str, initials: tuple[str, ...], contributor_names: Iterable[ContributorName]
) -> dict[str, str]:
    """Renvoie les prénoms pleins donnés par des contributions sources à une personne au prénom réduit, par forme normalisée.

    Un prénom compte s'il accompagne le même nom de famille et prolonge `initials`. Chaque prénom prend sa graphie la plus fréquente, puis la première dans l'ordre alphabétique.
    """
    spellings: dict[str, Counter[str]] = {}
    for name in contributor_names:
        contributor_first_name = name.first_name_for(last_name)
        if contributor_first_name is None or not full_first_name_extends(
            initials, contributor_first_name
        ):
            continue
        spellings.setdefault(normalize_text(contributor_first_name), Counter())[
            contributor_first_name
        ] += 1
    return {
        norm: min(counter, key=lambda s: (-counter[s], s)) for norm, counter in spellings.items()
    }


@dataclass(frozen=True)
class IdentifierMatch:
    """Rattachement par identifiant."""

    person_id: int | None = None
    """Personne désignée, si son nom est compatible."""
    rejected: bool = False
    """Une personne est désignée, mais son nom est incompatible."""


def decide_match_by_identifier(
    value: str | None,
    identifier_map: Mapping[str, IdentifiedPerson],
    source_contribution: ContributorName,
    contributor_name_forms: Sequence[str],
    name_form_status: Mapping[tuple[str, int], str],
) -> IdentifierMatch:
    """Renvoie la personne désignée par une valeur d'identifiant, corroborée par le nom de la contribution source.

    Le statut d'une forme de nom de la contribution source pour cette personne tranche d'abord : `confirmed` corrobore, `rejected` refuse. Sinon, les noms doivent être compatibles. La compatibilité admet une variante de graphie (« Toufic », « Toufik ») ou un nom réduit au nom de famille. Elle refuse un co-auteur ou un autre auteur de même nom de famille.

    Args:
        identifier_map: personnes par valeur d'identifiant, attributions rejetées exclues.
    """
    if not value:
        return IdentifierMatch()
    target = identifier_map.get(value)
    if target is None:
        return IdentifierMatch()
    person_id = target.person_id

    verdict = next(
        (
            name_form_status[(f, person_id)]
            for f in contributor_name_forms
            if (f, person_id) in name_form_status
        ),
        None,
    )
    if verdict == AttributionStatus.CONFIRMED:
        return IdentifierMatch(person_id=person_id)
    if verdict == AttributionStatus.REJECTED:
        return IdentifierMatch(rejected=True)

    contributor_last_name, contributor_first_name = source_contribution.split()
    if names_compatible(
        contributor_last_name, contributor_first_name, target.last_name, target.first_name
    ):
        return IdentifierMatch(person_id=person_id)
    return IdentifierMatch(rejected=True)


def strict_majority[K](votes: Mapping[K, int]) -> K | None:
    """Renvoie la clé qui a strictement plus de voix que chacune des autres. `None` en cas d'égalité en tête ou sans aucune voix."""
    if not votes:
        return None
    best, *others = sorted(votes.values(), reverse=True)
    if best <= 0 or (others and others[0] == best):
        return None
    return max(votes, key=votes.__getitem__)


def identifier_misplaced(contributor_name_form: str, consensus: str | None) -> bool:
    """Vrai si le consensus d'une valeur d'identifiant désigne un nom incompatible avec celui de la contribution source. Faux sans consensus."""
    return consensus is not None and not names_compatible(contributor_name_form, "", consensus, "")
