"""Règles pures de matching de contributions à des personnes."""

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
    """Personne ciblée par une valeur d'identifiant, avec son nom normalisé pour corroboration."""

    person_id: int
    last_name: str
    first_name: str


# TODO(scanr-idref-asymetrie) : l'IdRef est matché sans restriction de source
# (`decide_match_by_identifier(idref, idref_map)`), alors que l'IdRef ScanR provient
# du même bloc `denormalized` que son ORCID exclu. Asymétrie possiblement défendable
# (ScanR relève de l'autorité française IdRef/SUDOC) mais à objectiver : mesurer le
# taux d'accord de l'IdRef ScanR vs sources fiables avant de le garder ou de le
# source-restreindre comme l'ORCID.
ORCID_MATCH_SOURCES = frozenset({"crossref", "datacite", "openalex", "hal"})
"""Sources dont l'ORCID porté par une contribution est déposé par l'auteur, fiable comme signal de matching personne.

- `crossref` : ORCID fourni par l'auteur à l'éditeur lors de la soumission.
- `datacite` : ORCID du créateur, déposé avec l'enregistrement (`creators[].nameIdentifiers`).
- `openalex` : `raw_orcid` recopié par OpenAlex de la métadonnée brute de la source amont (cf. `_extract_openalex_orcid`) — même provenance que Crossref.
- `hal` : ORCID attaché à l'auteur dans le TEI HAL (`label_xml`).

`wos` et `scanr` sont exclus : leur ORCID est dérivé (matching algorithmique interne pour WoS, couche de dénormalisation pour ScanR), pas déposé par l'auteur. Il reste enregistré sur `person_identifiers` mais n'est pas utilisé comme signal de matching."""

STRONG_PERSON_IDENTIFIER_TYPES: tuple[PersonIdentifierType, ...] = (
    PersonIdentifierType.ORCID,
    PersonIdentifierType.IDREF,
    PersonIdentifierType.HAL_PERSON_ID,
)
"""Identifiants qui rattachent une contribution source à une personne sans forme de nom : hors périmètre, et pour l'entrée dans le périmètre d'une personne qui a une fiche RH."""


def trusted_identifier(id_type: str, source: str) -> bool:
    """Vrai quand l'identifiant `id_type` d'une contribution source de `source` sert de signal de rattachement. Un ORCID compte seulement s'il vient de `ORCID_MATCH_SOURCES`."""
    return id_type != PersonIdentifierType.ORCID or source in ORCID_MATCH_SOURCES


class MatchReason(StrEnum):
    """Motif d'une décision par forme de nom (`decide_name_form_outcome`)."""

    COMPATIBLE_NAME = "compatible_name"
    AMBIGUOUS_NAME_FORM = "ambiguous_name_form"
    ALL_CANDIDATES_REJECTED = "all_candidates_rejected"
    CREATION_NOT_ALLOWED = "creation_not_allowed"


class ResolutionMode(StrEnum):
    """Valeurs de l'enum PostgreSQL `resolution_mode`, qui type la colonne `source_contributions.resolution_mode`. Aucun code n'écrit cette colonne : la personne et son mode de résolution sont portés par le groupe (`source_contribution_groups`)."""

    IDENTIFIER = "identifier"
    NAME = "name"
    CROSS_SOURCE = "cross_source"


class Namesake(NamedTuple):
    """Personne portant un nom de famille donné, telle que la voit le rattachement par initiales.

    `conflicting` marque une personne au prénom réduit dont les contributions sources donnent plusieurs prénoms pleins distincts : elle ne peut recevoir aucun prénom plein de plus.
    """

    person_id: int
    last_name: str
    first_name: str
    conflicting: bool = False


def full_namesakes(initials: tuple[str, ...], namesakes: Iterable[Namesake]) -> list[int]:
    """Personnes au prénom plein dont les initiales commencent par `initials`."""
    return [n.person_id for n in namesakes if full_first_name_extends(initials, n.first_name)]


def compatible_namesakes(contributor_first_name: str, namesakes: Sequence[Namesake]) -> list[int]:
    """Personnes de même nom de famille qu'une contribution source désigne par la compatibilité des initiales, quand sa forme de nom exacte est inconnue.

    - Contribution source au prénom réduit (« A. ») : toute personne dont les initiales du prénom commencent par celles de la contribution source (« Abdul-Majeed », « A. M. »).
    - Contribution source au prénom plein (« Abdellah ») : toute personne au prénom réduit dont les initiales commencent celles de la contribution source (« A. »), et qu'aucun autre prénom ne revendique : ni une personne de même nom au prénom plein compatible, ni plusieurs prénoms pleins distincts donnés par ses contributions sources (`conflicting`).
    - Contribution source sans prénom : aucune.
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
    """Personnes que la contribution source désigne par ses initiales (`compatible_namesakes`), sur tous ses découpages (`ContributorName.splits`).

    `namesakes_by_last_name` indexe les personnes par nom de famille normalisé. Chaque personne figure une fois, dans l'ordre de découverte.
    """
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
    """Prénoms pleins que des contributions sources donnent à une personne au prénom réduit, indexés par leur forme normalisée.

    Retient les contributions sources dont un découpage donne le même nom de famille (`ContributorName.first_name_for`) et un prénom plein qui prolonge `initials`. Chaque prénom est rendu dans sa graphie la plus fréquente, la plus petite dans l'ordre alphabétique en cas d'égalité.
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
    """Décision résultant du lookup d'une contribution dans `person_name_forms`.

    Trois actions possibles : `match` (rattacher à une personne existante), `create` (créer une personne), `skip` (ne rien faire — soit ambiguïté de nom, soit création interdite par `allow_create`). Le `reason` dit pourquoi un `skip`, et distingue le `match` par initiales compatibles (`compatible_name`) du `match` par forme exacte, sans motif.
    """

    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: MatchReason | None = None


def decide_name_form_outcome(
    person_ids: list[int] | None,
    allow_create: bool,
    rejected_person_ids: frozenset[int] = frozenset(),
    compatible_person_ids: Sequence[int] = (),
) -> NameFormDecision:
    """Arbitre la décision de matching après lookup dans `person_name_forms`.

    `rejected_person_ids` : personnes déjà rejetées pour la publication de la contribution source traitée (store `rejected_contributions`). Elles sont **éliminées** de la liste des candidats avant arbitrage : une paire `(publication, personne)` rejetée est tenue hors du matching. L'élimination peut désambiguïser — si 2 personnes partagent la forme de nom mais qu'une est rejetée, il ne reste qu'une candidate et l'`ambiguous_name_form` devient un `match` univoque.

    `compatible_person_ids` : personnes de même nom de famille que la contribution source désigne par ses initiales (`compatible_namesakes`). Consultées seulement quand la forme exacte est inconnue.

    Cascade (sur les candidats restants après élimination) :

    - Forme connue, 1 candidat → `match`.
    - Forme connue, N candidats → `skip` avec `reason="ambiguous_name_form"` (homonymes en BDD, on laisse le traitement manuel trancher).
    - Forme connue, 0 candidat (tous rejetés) → `skip` avec `reason="all_candidates_rejected"` : la contribution source reste orpheline, sans création.
    - Forme inconnue, personnes compatibles : mêmes règles sur elles, le `match` portant `reason="compatible_name"`.
    - Forme inconnue, aucune personne compatible, `allow_create` → `create`.
    - Forme inconnue, aucune personne compatible, pas `allow_create` → `skip` avec `reason="creation_not_allowed"` (rôles de jury de thèse seuls, cf. `domain.persons.creation.allow_person_creation`).
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
    """Résultat de la résolution d'un identifiant vers une personne, corroborée par le nom.

    - `person_id` : la personne si l'identifiant résout **et** que son nom est compatible avec la contribution source ; `None` sinon.
    - `rejection` : `(person_id, target_name)` quand l'identifiant résolvait vers une personne mais que son nom est jugé incompatible avec la contribution source — le match est refusé, et l'info sert à journaliser le rejet (identifiant + les deux formes).
    """

    person_id: int | None = None
    rejection: tuple[int, str] | None = None


def decide_match_by_identifier(
    value: str | None,
    identifier_map: Mapping[str, IdentifiedPerson],
    source_contribution: ContributorName,
    contributor_name_forms: Sequence[str],
    name_form_status: Mapping[tuple[str, int], str],
) -> IdentifierMatch:
    """Résout un identifiant (IdRef, ORCID…) vers une `person_id`, corroboré par le nom.

    `identifier_map` est typiquement `{idref: (person_id, last_name_normalized, first_name_normalized)}` prefetché via `fetch_identifier_to_person_map(conn, id_type)`, déjà filtré sur les statuts non-`rejected`. La fonction est générique : elle marche pour n'importe quel id_type indexé sur `person_identifiers`.

    Corroboration par le nom, du verdict humain au test heuristique :

    1. Le statut du couple (forme de la contribution source, `person_id`) dans `person_name_forms` (`name_form_status`), pour la première des `contributor_name_forms` qui en a un, tranche en priorité — `confirmed` corrobore le match sans test (la forme appartient à la personne, y compris un changement de nom), `rejected` le refuse sans test.
    2. À défaut de verdict (`pending` ou forme inconnue), on teste la compatibilité via `names_compatible`, tolérante à la graphie : un identifiant présent sur une contribution source étrangère (corruption éparse : un ORCID recopié sur le mauvais co-auteur) ou par un homonyme de patronyme est refusé, mais une **variante de graphie du propriétaire lui-même** (« toufic » pour « toufik ») corrobore et se rattache — ce qui évite de la rejeter puis d'en créer un doublon au canal nominal. Une contribution source trop pauvre (réduite au nom de famille) reste compatible (sous-ensemble de tokens), sans être refusée.

    Un refus est matérialisé dans `rejection` pour journalisation.
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
    """Clé qui porte strictement plus de voix que chacune des autres. `None` en cas d'égalité en tête ou sans aucune voix."""
    if not votes:
        return None
    best, *others = sorted(votes.values(), reverse=True)
    if best <= 0 or (others and others[0] == best):
        return None
    return max(votes, key=votes.__getitem__)


def identifier_misplaced(contributor_name_form: str, consensus: str | None) -> bool:
    """Vrai quand le consensus d'une valeur d'identifiant désigne une autre personne que le nom de la contribution source qui la contient. Sans consensus, aucun identifiant n'est mal placé."""
    return consensus is not None and not names_compatible(contributor_name_form, "", consensus, "")
