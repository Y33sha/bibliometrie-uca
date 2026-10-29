"""Matching des contributions sources aux personnes, par identifiant ou par nom."""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, NamedTuple

from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.persons.identifiers import PersonIdentifierType
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


ORCID_MATCH_SOURCES = frozenset({"crossref", "datacite", "openalex", "hal"})
"""Sources dont l'ORCID est déposé par l'auteur : auprès de l'éditeur (Crossref, et OpenAlex qui le recopie), de DataCite ou de HAL. Dans WoS et ScanR, l'ORCID résulte d'un matching automatique."""

STRONG_PERSON_IDENTIFIER_TYPES: tuple[PersonIdentifierType, ...] = (
    PersonIdentifierType.ORCID,
    PersonIdentifierType.IDREF,
    PersonIdentifierType.HAL_PERSON_ID,
)
"""Identifiants qui rattachent une contribution source à une personne sans forme de nom : hors périmètre, et pour l'entrée dans le périmètre d'une personne qui a une fiche RH."""


def trusted_identifier(id_type: str, source: str) -> bool:
    """Vrai si l'identifiant d'une contribution source sert au rattachement. Un ORCID sert seulement s'il vient de `ORCID_MATCH_SOURCES`."""
    return id_type != PersonIdentifierType.ORCID or source in ORCID_MATCH_SOURCES


class MatchReason(StrEnum):
    """Motif d'une décision par forme de nom (`decide_name_form_outcome`)."""

    COMPATIBLE_NAME = "compatible_name"
    AMBIGUOUS_NAME_FORM = "ambiguous_name_form"
    ALL_CANDIDATES_REJECTED = "all_candidates_rejected"
    CREATION_NOT_ALLOWED = "creation_not_allowed"


class Namesake(NamedTuple):
    """Personne d'un nom de famille donné, candidate au rattachement par initiales. `conflicting` : personne au prénom réduit à qui ses contributions sources donnent plusieurs prénoms pleins ; le rattachement par initiales l'écarte pour un prénom plein."""

    person_id: int
    last_name: str
    first_name: str
    conflicting: bool = False


def full_namesakes(initials: tuple[str, ...], namesakes: Iterable[Namesake]) -> list[int]:
    """Personnes au prénom plein dont les initiales commencent par `initials`."""
    return [n.person_id for n in namesakes if full_first_name_extends(initials, n.first_name)]


def compatible_namesakes(contributor_first_name: str, namesakes: Sequence[Namesake]) -> list[int]:
    """Personnes de même nom de famille qu'une contribution source désigne par ses initiales.

    - Prénom réduit (« A. ») : toute personne dont les initiales du prénom commencent par celles de la contribution source (« Abdul-Majeed », « A. M. »).
    - Prénom plein (« Abdellah ») : toute personne au prénom réduit dont les initiales commencent celles de la contribution source (« A. »). Sont exclues les personnes `conflicting`, et celles dont les initiales commencent le prénom plein d'une autre personne de même nom.
    - Sans prénom : aucune.
    """
    contributor_initials = first_name_initials(contributor_first_name)
    if contributor_initials is not None:
        return [
            n.person_id for n in namesakes if initials_extend(contributor_initials, n.first_name)
        ]
    if not normalize_text(contributor_first_name):
        return []
    candidates = []
    for n in namesakes:
        initials = first_name_initials(n.first_name)
        if (
            initials is None
            or n.conflicting
            or not initials_extend(initials, contributor_first_name)
        ):
            continue
        if not full_namesakes(initials, namesakes):
            candidates.append(n.person_id)
    return candidates


def compatible_persons(
    source_contribution: ContributorName, namesakes_by_last_name: Mapping[str, Sequence[Namesake]]
) -> list[int]:
    """Personnes que la contribution source désigne par ses initiales, pour chacun de ses découpages en nom et prénom, sans doublon. `namesakes_by_last_name` : personnes par nom de famille normalisé."""
    found: list[int] = []
    for last, first in source_contribution.splits():
        namesakes = namesakes_by_last_name.get(normalize_text(last), ())
        for person_id in compatible_namesakes(first, namesakes):
            if person_id not in found:
                found.append(person_id)
    return found


def attested_full_first_names(
    last_name: str, initials: tuple[str, ...], contributor_names: Iterable[ContributorName]
) -> dict[str, str]:
    """Prénoms pleins que des contributions sources donnent à une personne au prénom réduit, par forme normalisée.

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
class NameFormDecision:
    """Décision par forme de nom : rattacher (`match`), créer une personne (`create`) ou s'abstenir (`skip`). `reason` motive un `skip`, et marque un `match` par initiales compatibles."""

    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: MatchReason | None = None


def decide_name_form_outcome(
    person_ids: list[int] | None,
    allow_create: bool,
    rejected_person_ids: frozenset[int] = frozenset(),
    compatible_person_ids: Sequence[int] = (),
) -> NameFormDecision:
    """Décision par forme de nom.

    `person_ids` : personnes de la forme de nom exacte, `None` si la forme est inconnue. `compatible_person_ids` : personnes désignées par les initiales, candidates seulement si la forme est inconnue. `rejected_person_ids` : personnes rejetées pour la publication, écartées des candidats.

    - Un candidat → `match`.
    - Plusieurs candidats → `skip`, `ambiguous_name_form`.
    - Candidats tous rejetés → `skip`, `all_candidates_rejected`.
    - Aucun candidat → `create` si `allow_create`, sinon `skip`, `creation_not_allowed`.
    """
    match_reason: MatchReason | None = None
    if person_ids is None:
        if not compatible_person_ids:
            if allow_create:
                return NameFormDecision(action="create")
            return NameFormDecision(action="skip", reason=MatchReason.CREATION_NOT_ALLOWED)
        person_ids = list(compatible_person_ids)
        match_reason = MatchReason.COMPATIBLE_NAME
    candidates = [pid for pid in person_ids if pid not in rejected_person_ids]
    if len(candidates) == 1:
        return NameFormDecision(action="match", person_id=candidates[0], reason=match_reason)
    if not candidates:
        return NameFormDecision(action="skip", reason=MatchReason.ALL_CANDIDATES_REJECTED)
    return NameFormDecision(action="skip", reason=MatchReason.AMBIGUOUS_NAME_FORM)


@dataclass(frozen=True)
class IdentifierMatch:
    """Rattachement par identifiant. `person_id` : personne désignée, si son nom est compatible. `rejection` : personne désignée et son nom, si ce nom est incompatible ; sert à journaliser le refus."""

    person_id: int | None = None
    rejection: tuple[int, str] | None = None


def decide_match_by_identifier(
    value: str | None,
    identifier_map: Mapping[str, IdentifiedPerson],
    source_contribution: ContributorName,
    contributor_name_forms: Sequence[str],
    name_form_status: Mapping[tuple[str, int], str],
) -> IdentifierMatch:
    """Personne désignée par une valeur d'identifiant, corroborée par le nom de la contribution source. `identifier_map` : personnes par valeur d'identifiant, attributions rejetées exclues.

    Le statut d'une forme de nom de la contribution source pour cette personne tranche d'abord : `confirmed` corrobore, `rejected` refuse. Sinon, les noms doivent être compatibles. La compatibilité admet une variante de graphie (« Toufic », « Toufik ») ou un nom réduit au nom de famille. Elle refuse un co-auteur ou un autre auteur de même nom de famille.
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
    if verdict == "confirmed":
        return IdentifierMatch(person_id=person_id)
    if verdict == "rejected":
        return IdentifierMatch(
            rejection=(person_id, f"{target.first_name} {target.last_name}".strip())
        )

    contributor_last_name, contributor_first_name = source_contribution.split()
    if names_compatible(
        contributor_last_name, contributor_first_name, target.last_name, target.first_name
    ):
        return IdentifierMatch(person_id=person_id)
    return IdentifierMatch(rejection=(person_id, f"{target.first_name} {target.last_name}".strip()))


def strict_majority[K](votes: Mapping[K, int]) -> K | None:
    """Clé qui a strictement plus de voix que chacune des autres. `None` en cas d'égalité en tête ou sans aucune voix."""
    if not votes:
        return None
    best, *others = sorted(votes.values(), reverse=True)
    if best <= 0 or (others and others[0] == best):
        return None
    return max(votes, key=votes.__getitem__)


def identifier_misplaced(contributor_name_form: str, consensus: str | None) -> bool:
    """Vrai si le consensus d'une valeur d'identifiant désigne un nom incompatible avec celui de la contribution source. Faux sans consensus."""
    return consensus is not None and not names_compatible(contributor_name_form, "", consensus, "")
