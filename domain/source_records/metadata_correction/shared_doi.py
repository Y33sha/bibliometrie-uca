"""Correction du DOI partagé par plusieurs enregistrements sources.

Une forme secondaire DataCite (version, variante, pièce d'un jeu de données) qui déclare son œuvre principale, présente en base, donne au DOI partagé une cible : le DOI de cette œuvre (`doi_target`). Un DOI à suffixe de version a pour cible sa forme sans version ou sa version la plus récente (`version_targets`). Un DOI partagé par des œuvres distinctes est retiré des membres qui l'ont à tort (`resolve_cluster_doi_corrections`). Les membres qui gardent le DOI perdent les clés de confirmation qu'ils partagent avec ceux qui le perdent (`confirmation_id_removals`).
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Set
from enum import StrEnum
from itertools import combinations
from typing import NamedTuple

from domain.publications.doc_types import DocType
from domain.publications.identifiers import doi_version, same_registrant
from domain.source_records.identifiers import STRONG_ROLES, SourceIdentifier, SourceIdentifierType
from domain.source_records.keys import CONFIRMATION_ID_TYPES
from domain.sources.registry import AGGREGATOR_SOURCES, Source


class DoiTargetRule(StrEnum):
    """Règle qui donne une cible au DOI d'une forme secondaire. Inscrite dans `doi_targets.rule`."""

    DATACITE_VERSION_TO_CONCEPT = "DATACITE_VERSION_TO_CONCEPT"
    """Version → concept (`IsVersionOf`)."""
    DATACITE_VARIANT_TO_PRIMARY = "DATACITE_VARIANT_TO_PRIMARY"
    """Copie de repository → version publiée (`IsVariantFormOf`)."""
    DATACITE_PACKAGE_PIECE = "DATACITE_PACKAGE_PIECE"
    """Pièce d'un dataset → dataset parent présent (`IsPartOf`, ou fichier complémentaire figshare)."""
    DOI_VERSION_TO_UNVERSIONED = "DOI_VERSION_TO_UNVERSIONED"
    """DOI à suffixe de version → sa forme sans version, DOI `primary` ou `derived` d'un enregistrement source."""
    DOI_VERSION_TO_LATEST = "DOI_VERSION_TO_LATEST"
    """DOI à suffixe de version → version de plus grand numéro en base."""


class DoiClusterCase(StrEnum):
    """Cas de retrait du DOI d'un membre d'un groupe partageant un DOI. Inscrit dans `source_record_identifiers.removed_by`."""

    OUVRAGE_VS_CHAPITRE = "OUVRAGE_VS_CHAPITRE"
    """Ouvrage et chapitre partageant un DOI : le DOI est celui de l'ouvrage, le chapitre d'un autre titre le perd."""
    CHAPITRES_TITRES_DIFFERENTS = "CHAPITRES_TITRES_DIFFERENTS"
    """Chapitres de titres différents partageant un DOI : celui de l'ouvrage, absent du groupe. Tous le perdent."""
    ACTES_VS_COMMUNICATION = "ACTES_VS_COMMUNICATION"
    """Volume d'actes et documents d'autres titres partageant son DOI : ces communications perdent le DOI."""
    NUMERO_VS_ARTICLE = "NUMERO_VS_ARTICLE"
    """Numéro de revue et documents d'autres titres partageant son DOI : ces articles perdent le DOI."""
    DOI_D_UNE_AUTRE_OEUVRE = "DOI_D_UNE_AUTRE_OEUVRE"
    """Enregistrement source dont le DOI est celui d'une autre œuvre (`_records_of_another_work`) : il le perd."""
    UNRESOLVED_DOI_TO_NULL = "UNRESOLVED_DOI_TO_NULL"
    """DOI inconnu de doi.org (`failed_lookups`, source `doi_org`) : tous les membres le perdent."""


# Types de relation DataCite qui désignent l'œuvre principale par son DOI. La requête des candidats en tire son `CASE` et son filtre.
DATACITE_DIRECT_CONVERGENCE: dict[str, DoiTargetRule] = {
    "IsVersionOf": DoiTargetRule.DATACITE_VERSION_TO_CONCEPT,
    "IsVariantFormOf": DoiTargetRule.DATACITE_VARIANT_TO_PRIMARY,
}
# Pièce d'un package : la requête exige en plus que le parent soit un dataset présent en base.
DATACITE_PACKAGE_PIECE_RELATION = "IsPartOf"

# Fichier complémentaire figshare « Additional file [N] of T » : pièce de la collection figshare de titre T.
FIGSHARE_ITEM_DOI_PATTERN = r"^10\.6084/m9\.figshare\.[0-9]+$"
FIGSHARE_COLLECTION_DOI_PREFIX = "10.6084/m9.figshare.c."
# Préfixe du titre normalisé (`normalize_text`) d'un fichier complémentaire figshare.
FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN = r"^additional file( [0-9]+)? of "


def declares_same_work(
    case: DoiTargetRule, doc_type: str | None, own_doi: str | None, target_doi: str | None
) -> bool:
    """Vrai si la relation déclarée par un enregistrement source réunit son DOI `own_doi` et `target_doi` en une seule œuvre.

    Une pièce de dataset rejoint son parent, et deux DOI d'un même registrant forment une seule œuvre. Entre deux registrants, une copie de repository rejoint la forme publiée, sauf un enregistrement source `preprint`. Une version d'un autre registrant relie deux œuvres, comme un preprint arXiv et l'article publié.
    """
    if case is DoiTargetRule.DATACITE_PACKAGE_PIECE or same_registrant(own_doi, target_doi):
        return True
    return case is DoiTargetRule.DATACITE_VARIANT_TO_PRIMARY and doc_type != DocType.PREPRINT


class SecondaryFormDeclaration(NamedTuple):
    """Enregistrement source qui déclare son DOI forme secondaire de l'œuvre principale `target_doi`, présente en base, sous la règle `rule`."""

    id: int
    doc_type: str | None
    """Type après la correction unaire."""
    target_doi: str
    rule: DoiTargetRule


class DoiClusterMember(NamedTuple):
    """Membre d'un groupe d'enregistrements sources qui partagent un DOI."""

    id: int
    doc_type: str | None
    """Type après la correction unaire."""
    title_normalized: str | None
    confirmation_ids: Mapping[SourceIdentifierType, tuple[str, ...]] = {}
    """Valeurs des clés de confirmation (`CONFIRMATION_ID_TYPES`) de ses identifiants, par type."""
    own_ids: Mapping[SourceIdentifierType, tuple[str, ...]] = {}
    """Identifiants de rôle `primary` ou `derived`, par type : ils désignent l'enregistrement source lui-même."""
    source: str = ""
    author_names: frozenset[str] = frozenset()
    """Noms de famille normalisés de ses contributions sources individuelles."""
    owns_doi: bool = False
    """Le DOI du groupe est parmi `own_ids`. Le membre le garde."""


class DoiClusterDecision(NamedTuple):
    """Retrait du DOI d'un membre, et le cas qui le décide."""

    id: int
    case: DoiClusterCase


class DoiTarget(NamedTuple):
    """Cible du DOI d'une forme secondaire : le DOI de l'œuvre principale, et la règle qui relie les deux DOI."""

    doi: str
    target_doi: str
    rule: DoiTargetRule


class ConfirmationIdRemoval(NamedTuple):
    """Clés de confirmation retirées d'un membre du groupe."""

    id: int
    removed: dict[SourceIdentifierType, list[str]]
    """Valeurs partagées avec un membre de l'autre œuvre, par type."""
    case: DoiClusterCase


# Cas où des œuvres distinctes partagent un DOI : le membre qui le perd est une autre œuvre.
_DIVERGENCE_CASES: frozenset[DoiClusterCase] = frozenset(
    {
        DoiClusterCase.OUVRAGE_VS_CHAPITRE,
        DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS,
        DoiClusterCase.ACTES_VS_COMMUNICATION,
        DoiClusterCase.NUMERO_VS_ARTICLE,
        DoiClusterCase.DOI_D_UNE_AUTRE_OEUVRE,
    }
)

# Types de conteneur, et cas de retrait du DOI aux membres d'un autre titre que le conteneur.
_CONTAINER_CASES: dict[str, DoiClusterCase] = {
    DocType.PROCEEDINGS: DoiClusterCase.ACTES_VS_COMMUNICATION,
    DocType.JOURNAL_ISSUE: DoiClusterCase.NUMERO_VS_ARTICLE,
}

CLUSTER_CANDIDATE_DOC_TYPES: frozenset[str] = frozenset(
    {DocType.BOOK, DocType.BOOK_CHAPTER, *_CONTAINER_CASES}
)
"""Types dont la présence dans un groupe de même DOI le rend candidat au retrait du DOI."""


def _values_by_type(
    identifiers: Iterable[SourceIdentifier],
) -> dict[SourceIdentifierType, tuple[str, ...]]:
    out: dict[SourceIdentifierType, list[str]] = {}
    for identifier in identifiers:
        out.setdefault(identifier.id_type, []).append(identifier.value)
    return {id_type: tuple(values) for id_type, values in out.items()}


def confirmation_ids(
    identifiers: Iterable[SourceIdentifier],
) -> dict[SourceIdentifierType, tuple[str, ...]]:
    """Renvoie les valeurs des clés de confirmation (`CONFIRMATION_ID_TYPES`) parmi `identifiers`, par type."""
    return _values_by_type(i for i in identifiers if i.id_type in CONFIRMATION_ID_TYPES)


def own_ids(identifiers: Iterable[SourceIdentifier]) -> dict[SourceIdentifierType, tuple[str, ...]]:
    """Renvoie les valeurs des identifiants de rôle `primary` ou `derived` parmi `identifiers`, par type."""
    return _values_by_type(i for i in identifiers if i.role in STRONG_ROLES)


def confirmation_id_removals(
    group: list[DoiClusterMember], decisions: list[DoiClusterDecision]
) -> list[ConfirmationIdRemoval]:
    """Calcule les retraits de clés de confirmation quand des œuvres distinctes partagent un DOI (`_DIVERGENCE_CASES`).

    Une clé de confirmation partagée par un membre qui garde le DOI et un membre qui le perd réunirait encore les deux œuvres. Le membre qui ne la détient pas en propre (`own_ids`) la perd :

    - le membre qui garde le DOI, par exemple l'enregistrement source OpenAlex du volume d'actes qui recopie le dépôt HAL d'une communication. La clé reste en place quand un membre qui garde le DOI la détient en propre, ou vient d'une source autre qu'un agrégateur (`AGGREGATOR_SOURCES`). Une telle source décrit son propre document : le PMID d'un dépôt HAL est celui de l'article, même recopié par l'enregistrement source ScanR d'un volume de résumés ;
    - le membre qui perd le DOI, quand un membre qui garde le DOI détient la clé en propre.
    """
    losers = {d.id: d.case for d in decisions if d.case in _DIVERGENCE_CASES}
    if not losers:
        return []
    owned_by_keepers = {
        (id_type, value)
        for m in group
        if m.id not in losers
        for id_type, values in m.own_ids.items()
        for value in values
    }
    kept: dict[SourceIdentifierType, set[str]] = {}
    for m in group:
        if m.id in losers:
            continue
        held = [m.own_ids] if m.source in AGGREGATOR_SOURCES else [m.own_ids, m.confirmation_ids]
        for ids in held:
            for id_type, values in ids.items():
                kept.setdefault(id_type, set()).update(values)
    lost: dict[SourceIdentifierType, set[str]] = {}
    for m in group:
        if m.id in losers:
            for id_type, values in m.confirmation_ids.items():
                lost.setdefault(id_type, set()).update(
                    v for v in values if v not in kept.get(id_type, ())
                )
    case = next(iter(losers.values()))
    removals: list[ConfirmationIdRemoval] = []
    for m in group:
        if m.id in losers:
            removed = {
                id_type: copied
                for id_type, values in m.confirmation_ids.items()
                if (
                    copied := [
                        v
                        for v in values
                        if (id_type, v) in owned_by_keepers and v not in m.own_ids.get(id_type, ())
                    ]
                )
            }
            if removed:
                removals.append(ConfirmationIdRemoval(m.id, removed, losers[m.id]))
            continue
        removed = {
            id_type: shared
            for id_type, values in m.confirmation_ids.items()
            if (shared := [v for v in values if v in lost.get(id_type, ())])
        }
        if removed:
            removals.append(ConfirmationIdRemoval(m.id, removed, case))
    return removals


# Marqueurs de chapitre, retirés avant comparaison : une source saisit le numéro du chapitre (« chapitre 14 … »), une autre non.
_CHAPTER_TITLE_MARKERS = re.compile(
    r"\b(chapitre|chapter|chap|ch|section|sec|partie|part|vol|tome|pp|p)\b"
)


def _clean_title(title_normalized: str | None) -> str:
    """Retire d'un titre normalisé les chiffres et les marqueurs de chapitre, pour comparer des titres."""
    cleaned = re.sub(r"\d+", " ", title_normalized or "")
    cleaned = _CHAPTER_TITLE_MARKERS.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _same_title(a: str, b: str) -> bool:
    """Vrai si deux titres nettoyés désignent la même œuvre : égaux, ou l'un contenu dans l'autre (sous-titre tronqué)."""
    return a == b or a in b or b in a


def _group_has_distinct_chapters(titles: list[str | None]) -> bool:
    """Vrai si deux titres de chapitre, nettoyés, désignent des œuvres différentes."""
    cleaned = [c for c in (_clean_title(t) for t in titles) if c]
    return any(not _same_title(a, b) for a, b in combinations(cleaned, 2))


def _container_contents(
    group: list[DoiClusterMember], references: list[DoiClusterMember], container_type: str
) -> list[DoiClusterMember]:
    """Renvoie les membres titrés d'un groupe dont le titre diffère de celui de chaque conteneur de type `container_type`, cherché parmi `references`. Vide sans conteneur titré."""
    containers = [
        t
        for m in references
        if m.doc_type == container_type and (t := _clean_title(m.title_normalized))
    ]
    if not containers:
        return []
    return [
        m
        for m in group
        if m.doc_type != container_type
        and (t := _clean_title(m.title_normalized))
        and not any(_same_title(t, c) for c in containers)
    ]


_SHARED_TITLE_WORDS_MIN = 0.35
_TITLE_WORD_MIN_LENGTH = 3


def _shared_title_words(a: str | None, b: str | None) -> float | None:
    """Calcule la part des mots du plus court des deux titres présents dans l'autre, mots de 3 lettres ou plus. `None` si l'un des titres n'a aucun mot retenu."""
    words_a = {w for w in (a or "").split() if len(w) >= _TITLE_WORD_MIN_LENGTH}
    words_b = {w for w in (b or "").split() if len(w) >= _TITLE_WORD_MIN_LENGTH}
    if not words_a or not words_b:
        return None
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def distant_titles(a: str | None, b: str | None) -> bool:
    """Vrai si moins de 35 % des mots du plus court des deux titres normalisés sont présents dans l'autre (`_SHARED_TITLE_WORDS_MIN`).

    Seuls comptent les mots de 3 lettres ou plus : les mots grammaticaux et les restes de formules mathématiques sont ignorés. Un titre sans mot retenu n'est éloigné d'aucun autre.
    """
    shared = _shared_title_words(a, b)
    return shared is not None and shared < _SHARED_TITLE_WORDS_MIN


def _records_of_another_work(group: list[DoiClusterMember]) -> list[DoiClusterMember]:
    """Renvoie les membres dont le DOI est celui d'une autre œuvre.

    L'enregistrement source Crossref du DOI sert de référence. Un membre d'une autre source est retenu quand deux conditions sont réunies face à lui :
    - aucun nom de famille d'auteur commun ;
    - des titres éloignés (`distant_titles`).

    Seules les contributions sources individuelles comptent. Un membre ou un enregistrement source Crossref sans contribution source individuelle reste hors de la comparaison.
    """
    crossref = [m for m in group if m.source == Source.CROSSREF and m.author_names]
    if len(crossref) != 1:
        return []
    reference = crossref[0]
    return [
        m
        for m in group
        if m.source != Source.CROSSREF
        and m.author_names
        and not m.author_names & reference.author_names
        and distant_titles(m.title_normalized, reference.title_normalized)
    ]


def doi_target(declarations: Iterable[SecondaryFormDeclaration], *, doi: str) -> DoiTarget | None:
    """Renvoie la cible de `doi` quand un enregistrement source le déclare forme secondaire d'une autre forme de la même œuvre (cf. `declares_same_work`) : version → concept, variante → version publiée, fichier → dépôt parent."""
    declaration = next(
        (
            d
            for d in declarations
            if d.target_doi != doi and declares_same_work(d.rule, d.doc_type, doi, d.target_doi)
        ),
        None,
    )
    return DoiTarget(doi, declaration.target_doi, declaration.rule) if declaration else None


def version_targets(dois: Iterable[str], anchor_dois: Set[str]) -> list[DoiTarget]:
    """Renvoie la cible de chaque DOI à suffixe de version de `dois` (`doi_version`) : sa forme sans version quand c'est un DOI de `anchor_dois`, sinon la version de plus grand numéro parmi `dois`. La version la plus récente reste alors sans cible."""
    families: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for doi in set(dois):
        if (version := doi_version(doi)) is not None:
            families[version.unversioned].append((version.number, doi))
    targets: list[DoiTarget] = []
    for unversioned, versions in families.items():
        if unversioned in anchor_dois:
            targets.extend(
                DoiTarget(doi, unversioned, DoiTargetRule.DOI_VERSION_TO_UNVERSIONED)
                for _, doi in versions
            )
            continue
        latest = max(versions)[1]
        targets.extend(
            DoiTarget(doi, latest, DoiTargetRule.DOI_VERSION_TO_LATEST)
            for _, doi in versions
            if doi != latest
        )
    return sorted(targets)


def resolve_cluster_doi_corrections(
    group: list[DoiClusterMember],
    *,
    unresolved: bool = False,
    has_target: bool = False,
) -> list[DoiClusterDecision]:
    """Renvoie les membres d'un groupe d'enregistrements sources de même DOI qui perdent ce DOI, avec le cas qui le décide.

    Un membre qui détient le DOI en propre (`owns_doi`) le garde. S'il y en a, seuls ces membres désignent l'ouvrage ou le conteneur.

    - **DOI inconnu de doi.org** (`unresolved`) : tous les membres perdent le DOI. Prime sur les cas ci-dessous.
    - **DOI d'une forme secondaire** (`has_target`, cf. `doi_target`) : aucun membre ne perd le DOI. Prime sur les cas ci-dessous, réservés à la famille ouvrage/chapitre.
    - **Ouvrage + chapitre** : les `book_chapter` d'un autre titre que l'ouvrage perdent le DOI, celui de l'ouvrage. Un chapitre au titre de l'ouvrage est la même œuvre, typée autrement par sa source : il garde le DOI.
    - **Chapitres seuls, de titres différents, sans membre qui détient le DOI en propre** : tous les `book_chapter` perdent le DOI, celui de l'ouvrage absent.
    - **Volume d'actes + communications** : les membres dont le titre diffère de celui du volume (`proceedings`) perdent le DOI, quel que soit leur type. Les membres au titre du volume le gardent.
    - **Numéro de revue + articles** : même règle avec le numéro (`journal_issue`).
    - **DOI d'une autre œuvre** (`_records_of_another_work`) : un enregistrement source sans nom d'auteur commun avec l'enregistrement source Crossref du DOI, et de titre éloigné du sien, perd le DOI. S'ajoute aux cas précédents.
    - **Clé propre d'un membre qui perd le DOI** (`_co_owners_of_lost_keys`) : un membre qui détient aussi cette clé en propre perd le DOI.
    """
    if unresolved:
        return [DoiClusterDecision(m.id, DoiClusterCase.UNRESOLVED_DOI_TO_NULL) for m in group]
    if has_target:
        return []

    decisions = _divergence_decisions(group)
    decided = {d.id for d in decisions}
    decisions += [
        DoiClusterDecision(m.id, DoiClusterCase.DOI_D_UNE_AUTRE_OEUVRE)
        for m in _records_of_another_work(group)
        if m.id not in decided
    ]
    owners = {m.id for m in group if m.owns_doi}
    decisions = [d for d in decisions if d.id not in owners]
    return decisions + _co_owners_of_lost_keys(group, decisions)


def _divergence_decisions(group: list[DoiClusterMember]) -> list[DoiClusterDecision]:
    """Décide les retraits de la famille ouvrage/chapitre, à défaut ceux des conteneurs (`_CONTAINER_CASES`). Un membre étranger à deux conteneurs prend le cas du premier."""
    owners = [m for m in group if m.owns_doi]
    references = owners or group
    chapters = [m for m in group if m.doc_type == DocType.BOOK_CHAPTER]
    book_titles = [
        _clean_title(m.title_normalized) for m in references if m.doc_type == DocType.BOOK
    ]
    if book_titles and chapters:
        return [
            DoiClusterDecision(m.id, DoiClusterCase.OUVRAGE_VS_CHAPITRE)
            for m in chapters
            if not any(_same_title(_clean_title(m.title_normalized), t) for t in book_titles if t)
        ]
    if (
        chapters
        and not owners
        and _group_has_distinct_chapters([m.title_normalized for m in chapters])
    ):
        return [
            DoiClusterDecision(m.id, DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS) for m in chapters
        ]
    decisions: dict[int, DoiClusterCase] = {}
    for container_type, case in _CONTAINER_CASES.items():
        for m in _container_contents(group, references, container_type):
            decisions.setdefault(m.id, case)
    return [DoiClusterDecision(member_id, case) for member_id, case in decisions.items()]


def _co_owners_of_lost_keys(
    group: list[DoiClusterMember], decisions: list[DoiClusterDecision]
) -> list[DoiClusterDecision]:
    """Renvoie le retrait du DOI des membres qui le gardent sans le détenir en propre, et qui détiennent en propre une clé de confirmation détenue en propre par un membre qui perd le DOI. Ils décrivent l'œuvre de ce membre : ils perdent le DOI, détenu en `secondary`, plutôt que leur clé."""
    losers = {d.id: d.case for d in decisions if d.case in _DIVERGENCE_CASES}
    if not losers:
        return []
    lost_own_keys = {
        (id_type, value)
        for m in group
        if m.id in losers
        for id_type, values in m.own_ids.items()
        if id_type in CONFIRMATION_ID_TYPES
        for value in values
    }
    case = next(iter(losers.values()))
    return [
        DoiClusterDecision(m.id, case)
        for m in group
        if m.id not in losers
        and not m.owns_doi
        and any(
            (id_type, v) in lost_own_keys for id_type, values in m.own_ids.items() for v in values
        )
    ]
