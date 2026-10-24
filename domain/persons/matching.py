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
    """Motif d'une décision de la cascade de rattachement (`decide_person_match`, `decide_name_form_outcome`)."""

    ORCID = "orcid"
    HAL_PERSON_ID = "hal_person_id"
    IDREF = "idref"
    CROSS_SOURCE = "cross_source"
    SINGLE_NAME = "single_name"
    COMPATIBLE_NAME = "compatible_name"
    NEW = "new"
    AMBIGUOUS_NAME_FORM = "ambiguous_name_form"
    ALL_CANDIDATES_REJECTED = "all_candidates_rejected"
    CREATION_NOT_ALLOWED = "creation_not_allowed"
    OUT_OF_PERIMETER = "out_of_perimeter"


class ResolutionMode(StrEnum):
    """Canal de résolution par lequel la cascade a posé le `person_id` d'une contribution source, indexé par le `reason` de `decide_person_match`. Enregistré dans `source_contributions.resolution_mode`, il guide les réinitialisations ordre-indépendantes de la phase : re-null ciblé des `identifier` transférés, re-orphelinage des `name` à forme devenue ambiguë, recompute en bloc des `cross_source`. La création par nom vaut `name` (elle ancre une personne sur sa forme). Mappe l'enum PostgreSQL `resolution_mode`."""

    IDENTIFIER = "identifier"
    NAME = "name"
    CROSS_SOURCE = "cross_source"


RESOLUTION_MODE_BY_REASON: dict[MatchReason, ResolutionMode] = {
    MatchReason.ORCID: ResolutionMode.IDENTIFIER,
    MatchReason.HAL_PERSON_ID: ResolutionMode.IDENTIFIER,
    MatchReason.IDREF: ResolutionMode.IDENTIFIER,
    MatchReason.CROSS_SOURCE: ResolutionMode.CROSS_SOURCE,
    MatchReason.SINGLE_NAME: ResolutionMode.NAME,
    MatchReason.COMPATIBLE_NAME: ResolutionMode.NAME,
}


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


def decide_cross_source_match(
    contribution_source: str,
    last_norm: str,
    first_norm: str,
    candidates: list[tuple[int, str, str, str]],
) -> int | None:
    """Décide si une contribution peut être rattachée à la `person` d'une autre contribution source de son groupe (contributions sources du même auteur dans la publication, `source_contribution_group_members`).

    Quand HAL a déjà rattaché un auteur à la personne 42, la contribution source OpenAlex du même groupe reçoit la même personne, à condition que son nom soit compatible.

    Paramètres :

    - `contribution_source` : source de la contribution qu'on cherche à rattacher. Sert à exclure les candidats de la même source (qui ne porteraient aucun signal supplémentaire).
    - `last_norm`, `first_norm` : nom normalisé de la contribution.
    - `candidates` : liste de tuples `(person_id, last_norm, first_norm, source)` — les contributions déjà rattachées du même groupe.

    Cascade :

    - Aucun candidat compatible → `None`.
    - Candidats compatibles convergent tous vers la même `person_id` → cette `person_id`.
    - Candidats compatibles divergent (≥ 2 `person_id` distincts) → `None` (conflit, pas de match safe).
    """
    matched_pid: int | None = None
    for pid, ln, fn, src in candidates:
        if src == contribution_source:
            continue
        if names_compatible(last_norm, first_norm, ln, fn):
            if matched_pid is not None and matched_pid != pid:
                return None
            matched_pid = pid
    return matched_pid


# Motifs d'un `skip` par forme de nom connue : la contribution source ne peut ni se rattacher par son nom, ni créer de personne.
UNDECIDABLE_NAME_FORM_REASONS = frozenset(
    {MatchReason.AMBIGUOUS_NAME_FORM, MatchReason.ALL_CANDIDATES_REJECTED}
)


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

    `rejected_person_ids` : personnes déjà rejetées pour la publication de la contribution traitée (store `rejected_contributions`). Elles sont **éliminées** de la liste des candidats avant arbitrage : une paire `(publication, personne)` rejetée est tenue hors du matching. L'élimination peut désambiguïser — si 2 personnes partagent la forme de nom mais qu'une est rejetée, il ne reste qu'une candidate et l'`ambiguous_name_form` devient un `match` univoque.

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


@dataclass(frozen=True)
class PersonMatchDecision:
    """Décision de la cascade de matching unifiée. `reason` identifie le signal qui a tranché."""

    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: MatchReason | None = None


def decide_person_match(
    *,
    orcid_match: int | None,
    hal_match: int | None,
    idref_match: int | None,
    cross_source_match: int | None,
    name_form_outcome: NameFormDecision,
    rejected_person_ids: frozenset[int] = frozenset(),
) -> PersonMatchDecision:
    """Cascade unifiée de matching personne, du signal le plus fiable au moins fiable.

    Hiérarchie par fiabilité de provenance :

    1. **ORCID déposé par l'auteur** (`orcid_match`) — ORCID issu d'une source à dépôt auteur (`ORCID_MATCH_SOURCES`), borné côté caller.
    2. **`hal_person_id`** (`hal_match`) — compte HAL de l'auteur, attaché à la contribution source dans le TEI HAL.
    3. **IdRef** (`idref_match`).
    4. **Match par `person_name_forms`** (`name_form_outcome` d'action `match`) — nom normalisé désignant une seule personne, ou, à forme inconnue, seule personne aux initiales compatibles (`reason="compatible_name"`). Placé avant le cross-source pour maximiser les ancres fermes que ce dernier exploite.
    5. **Cross-source** (`cross_source_match`) — match par le groupe de contributions sources, avec une contribution d'une autre source et nom compatible. Inopérant au bootstrap (suppose des matchings préexistants).
    6. **Création par `person_name_forms`** (`name_form_outcome` d'action `create`) — nom inconnu, en dernier recours. La création est différée en fin de cascade côté orchestrateur : une contribution source à créer peut encore rejoindre une ancre cross-source posée par une contribution source traitée plus loin.

    `rejected_person_ids` : personnes déjà rejetées pour la publication de la contribution (store `rejected_contributions`). Un match d'identifiant ou cross-source pointant vers une personne rejetée est **annulé** — la cascade retombe au signal suivant, et faute de mieux laisse la contribution orpheline, sans recréer le lien rejeté. Le tiroir name form est déjà gardé en amont : `name_form_outcome` doit être calculé avec le même `rejected_person_ids` (cf. `decide_name_form_outcome`).

    Pure, testable sans BDD : les paramètres sont précalculés par le caller via prefetch.
    """
    if orcid_match is not None and orcid_match not in rejected_person_ids:
        return PersonMatchDecision("match", orcid_match, MatchReason.ORCID)
    if hal_match is not None and hal_match not in rejected_person_ids:
        return PersonMatchDecision("match", hal_match, MatchReason.HAL_PERSON_ID)
    if idref_match is not None and idref_match not in rejected_person_ids:
        return PersonMatchDecision("match", idref_match, MatchReason.IDREF)
    if name_form_outcome.action == "match":
        return PersonMatchDecision(
            "match",
            name_form_outcome.person_id,
            name_form_outcome.reason or MatchReason.SINGLE_NAME,
        )
    if cross_source_match is not None and cross_source_match not in rejected_person_ids:
        return PersonMatchDecision("match", cross_source_match, MatchReason.CROSS_SOURCE)
    if name_form_outcome.action == "create":
        return PersonMatchDecision("create", reason=MatchReason.NEW)
    return PersonMatchDecision("skip", reason=name_form_outcome.reason)
