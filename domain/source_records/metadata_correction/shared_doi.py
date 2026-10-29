"""Correction du DOI d'un groupe d'enregistrements partageant un même DOI.

Les corrections unaires (`rules`) décident d'un enregistrement seul. Ici on regarde le **groupe de `source_records` partageant un DOI** et on en déduit la cible du DOI, ou les membres qui le perdent. Deux familles opposées :

- **convergence (même œuvre)** : le DOI d'une forme secondaire DataCite, désignée par un `relatedIdentifiers`, a pour cible le DOI de l'œuvre principale présente en base (`DoiTarget`). Trois cas : version → concept (`IsVersionOf`) ; forme variante → forme principale (`IsVariantFormOf`) ; pièce d'un dataset → dataset parent (`IsPartOf` vers un dataset, forme du DOI indifférente). Un fichier complémentaire figshare, sans relation déclarée, est une pièce de la collection figshare de même titre. Les conditions de préfixe sont décrites par `meme_oeuvre_declaree` ; une relation qui relie deux œuvres va à la phase `relations`.
- **divergence (œuvres distinctes)** : un DOI partagé par des œuvres réellement distinctes (ouvrage/chapitre, chapitres de titres différents, volume d'actes/communication, dépôt HAL d'une autre œuvre), erroné sur le ou les mauvais côtés → nullage du DOI sur ces membres. Les membres qui gardent le DOI perdent aussi les clés de confirmation qu'ils partagent avec ceux qui le perdent (`confirmation_id_removals`).

Un DOI que doi.org ne connaît pas est nullé sur tous les membres du groupe, avant toute autre décision.

La décision est **agnostique de la source** : le caller applicatif regroupe par DOI (brut reconstruit) et persiste la cible du DOI et la décision de chaque membre. La famille de cas est extensible.

`DATACITE_DIRECT_CONVERGENCE` mappe la `relation_type` d'un `relatedIdentifiers` (vocabulaire DataCite, gardé en chaîne) au cas de correction ; la requête de candidats au clustering le consomme pour former son `CASE` et son filtre.
"""

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from itertools import combinations
from typing import NamedTuple

from domain.publications.doc_types import DocType
from domain.publications.identifiers import NNT, HALId, meme_registrant
from domain.source_records.identifiers import SourceIdentifier, SourceIdentifierType
from domain.source_records.keys import CONFIRMATION_ID_TYPES
from domain.sources.registry import Source
from domain.sources.scanr import extract_hal_id_from_scanr_id


class DoiClusterCase(StrEnum):
    """Cas de correction d'un groupe partageant un DOI. Inscrit dans `doi_targets.rule` pour une forme secondaire, dans `corrections.doi.corrected_by` pour un membre qui perd le DOI."""

    # Formes secondaires DataCite d'une œuvre présente en base.
    DATACITE_VERSION_TO_CONCEPT = "DATACITE_VERSION_TO_CONCEPT"  # version → concept (IsVersionOf)
    DATACITE_VARIANT_TO_PRIMARY = (
        "DATACITE_VARIANT_TO_PRIMARY"  # copie repository → version publiée (IsVariantFormOf)
    )
    DATACITE_PACKAGE_PIECE = "DATACITE_PACKAGE_PIECE"  # pièce d'un dataset → dataset parent présent (IsPartOf, ou fichier complémentaire figshare)

    # Ouvrage et chapitre partageant un DOI : le DOI appartient à l'ouvrage (`book`), le
    # `book_chapter` d'un autre titre le porte à tort → le chapitre le perd.
    OUVRAGE_VS_CHAPITRE = "OUVRAGE_VS_CHAPITRE"

    # Plusieurs `book_chapter` partageant un DOI mais de titres réellement différents : le DOI
    # est celui de l'ouvrage hôte (absent du groupe), recopié sur ses chapitres → tous le perdent.
    CHAPITRES_TITRES_DIFFERENTS = "CHAPITRES_TITRES_DIFFERENTS"

    # Volume d'actes (`proceedings`) et documents de titres différents partageant son DOI : ce
    # sont des communications du volume → elles perdent le DOI.
    ACTES_VS_COMMUNICATION = "ACTES_VS_COMMUNICATION"

    # Dépôt HAL dont le DOI est celui d'une autre œuvre (`_depots_hal_d_une_autre_oeuvre`) → le dépôt le perd.
    HAL_DOI_D_UNE_AUTRE_OEUVRE = "HAL_DOI_D_UNE_AUTRE_OEUVRE"

    # DOI que doi.org ne connaît pas (`failed_lookups`, source `doi_org`) → tous les membres le perdent.
    UNRESOLVED_DOI_TO_NULL = "UNRESOLVED_DOI_TO_NULL"


# Convergence directe : le `relatedIdentifiers` pointe le DOI de l'œuvre canonique, pris tel quel.
DATACITE_DIRECT_CONVERGENCE: dict[str, DoiClusterCase] = {
    "IsVersionOf": DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
    "IsVariantFormOf": DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
}
# Pièce d'un package : la requête exige en plus que le parent soit un dataset présent en base.
DATACITE_PACKAGE_PIECE_RELATION = "IsPartOf"

# Fichier complémentaire figshare « Additional file [N] of T » : pièce de la collection figshare de titre T.
FIGSHARE_ITEM_DOI_PATTERN = r"^10\.6084/m9\.figshare\.[0-9]+$"
FIGSHARE_COLLECTION_DOI_PREFIX = "10.6084/m9.figshare.c."
# Préfixe du titre normalisé (`normalize_text`) d'un fichier complémentaire figshare.
FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN = r"^additional file( [0-9]+)? of "


def meme_oeuvre_declaree(
    case: DoiClusterCase, doc_type: str | None, own_doi: str | None, target_doi: str | None
) -> bool:
    """Vrai si la relation déclarée par un enregistrement source réunit son DOI `own_doi` et `target_doi` en une seule œuvre.

    Une pièce de dataset rejoint son parent, et deux DOI d'un même registrant forment une seule œuvre. Entre deux registrants, une copie de repository rejoint la forme publiée, sauf un enregistrement source `preprint`. Une version d'un autre registrant relie deux œuvres, comme un preprint arXiv et l'article publié.
    """
    if case is DoiClusterCase.DATACITE_PACKAGE_PIECE or meme_registrant(own_doi, target_doi):
        return True
    return case is DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY and doc_type != DocType.PREPRINT


class DoiClusterMember(NamedTuple):
    """Un membre d'un groupe de `source_records` partageant un DOI : son id, son `doc_type` corrigé par la passe unaire et son `title_normalized` (matérialisé). `canonical_doi` est le DOI de l'œuvre principale, présente en base, quand ce membre (typiquement une `source_record` `datacite`) en est une **forme secondaire** ; `same_work_case` donne alors le `DoiClusterCase` correspondant (version/variante/pièce de package)."""

    id: int
    doc_type: str | None
    title_normalized: str | None
    canonical_doi: str | None = None
    same_work_case: DoiClusterCase | None = None
    # Valeurs des clés de confirmation (`CONFIRMATION_ID_TYPES`) de ses identifiants, par type.
    confirmation_ids: Mapping[str, tuple[str, ...]] = {}
    # Identifiants propres de l'enregistrement source, par type : le `hal_id` d'un enregistrement source HAL, le NNT d'un enregistrement source theses.fr.
    own_ids: Mapping[str, tuple[str, ...]] = {}
    source: str = ""
    # Noms de famille normalisés de ses contributions sources individuelles.
    author_names: frozenset[str] = frozenset()


class DoiClusterDecision(NamedTuple):
    """Retrait du DOI d'un membre, et le cas qui le décide."""

    id: int
    case: DoiClusterCase


class DoiTarget(NamedTuple):
    """Cible du DOI d'une forme secondaire : le DOI de l'œuvre principale, et le cas qui relie les deux DOI."""

    doi: str
    target_doi: str
    case: DoiClusterCase


class ConfirmationIdRemoval(NamedTuple):
    """Identifiants retirés d'un membre qui garde le DOI partagé : par type, les valeurs qu'il partage avec un membre qui perd le DOI."""

    id: int
    removed: dict[str, list[str]]
    case: DoiClusterCase


# Cas où des œuvres distinctes partagent un DOI : le membre qui le perd est une autre œuvre.
DIVERGENCE_CASES: frozenset[DoiClusterCase] = frozenset(
    {
        DoiClusterCase.OUVRAGE_VS_CHAPITRE,
        DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS,
        DoiClusterCase.ACTES_VS_COMMUNICATION,
        DoiClusterCase.HAL_DOI_D_UNE_AUTRE_OEUVRE,
    }
)


def confirmation_ids(identifiers: Iterable[SourceIdentifier]) -> dict[str, tuple[str, ...]]:
    """Valeurs des clés de confirmation (`CONFIRMATION_ID_TYPES`) parmi `identifiers`, par type."""
    out: dict[str, list[str]] = {}
    for identifier in identifiers:
        if identifier.id_type in CONFIRMATION_ID_TYPES:
            out.setdefault(identifier.id_type.value, []).append(identifier.value)
    return {id_type: tuple(values) for id_type, values in out.items()}


def source_record_own_ids(source: str, source_id: str) -> dict[str, tuple[str, ...]]:
    """Identifiants propres d'un enregistrement source, par type : le dépôt HAL d'un enregistrement source HAL ou d'un enregistrement source ScanR issu de HAL, le NNT d'un enregistrement source theses.fr."""
    if source == Source.HAL:
        hal_id = HALId.try_parse(source_id)
    elif source == Source.SCANR:
        hal_id = HALId.try_parse(extract_hal_id_from_scanr_id(source_id) or "")
    elif source == Source.THESES:
        nnt = NNT.try_parse(source_id)
        return {SourceIdentifierType.NNT.value: (str(nnt),)} if nnt else {}
    else:
        return {}
    return {SourceIdentifierType.HAL_ID.value: (str(hal_id),)} if hal_id else {}


def confirmation_id_removals(
    group: list[DoiClusterMember], decisions: list[DoiClusterDecision]
) -> list[ConfirmationIdRemoval]:
    """Retraits d'identifiants après une divergence (`DIVERGENCE_CASES`).

    Une clé de confirmation partagée avec un membre qui perd le DOI appartient à cette autre œuvre : le membre qui garde le DOI la perd. Sans quoi la clé réunirait encore les deux œuvres, par exemple le dépôt HAL d'une communication que l'enregistrement source OpenAlex du volume d'actes recopie. Une valeur propre à un membre qui garde le DOI (`own_ids`) reste en place.
    """
    losers = {d.id: d.case for d in decisions if d.case in DIVERGENCE_CASES}
    if not losers:
        return []
    kept_own: dict[str, set[str]] = {}
    for m in group:
        if m.id not in losers:
            for id_type, values in m.own_ids.items():
                kept_own.setdefault(id_type, set()).update(values)
    lost: dict[str, set[str]] = {}
    for m in group:
        if m.id in losers:
            for id_type, values in m.confirmation_ids.items():
                lost.setdefault(id_type, set()).update(
                    v for v in values if v not in kept_own.get(id_type, ())
                )
    case = next(iter(losers.values()))
    removals: list[ConfirmationIdRemoval] = []
    for m in group:
        if m.id in losers:
            continue
        removed = {
            id_type: shared
            for id_type, values in m.confirmation_ids.items()
            if (shared := [v for v in values if v in lost.get(id_type, ())])
        }
        if removed:
            removals.append(ConfirmationIdRemoval(m.id, removed, case))
    return removals


# Marqueurs structurels de titre de chapitre, retirés avant comparaison : un chapitre est
# fréquemment saisi avec son numéro (« chapitre 14 … ») par une source et sans par une autre.
_CHAPTER_TITLE_MARKERS = re.compile(
    r"\b(chapitre|chapter|chap|ch|section|sec|partie|part|vol|tome|pp|p)\b"
)


def _clean_title(title_normalized: str | None) -> str:
    """Retire le bruit structurel d'un titre normalisé (chiffres = numéros de chapitre/page, mots-marqueurs) et re-collapse les espaces, pour comparer des titres à leur résidu. Déterministe (égalité stricte, aucune similarité floue)."""
    cleaned = re.sub(r"\d+", " ", title_normalized or "")
    cleaned = _CHAPTER_TITLE_MARKERS.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _same_title(a: str, b: str) -> bool:
    """Deux résidus de titre désignent la même œuvre : égaux, ou l'un contenu dans l'autre (troncature de sous-titre)."""
    return a == b or a in b or b in a


def _group_has_distinct_chapters(titles: list[str | None]) -> bool:
    """True si le groupe contient deux chapitres **réellement distincts** : après nettoyage, une paire de titres qui ne désignent pas la même œuvre (`_same_title`). Égalité stricte sur le résidu, sans seuil flou."""
    cleaned = [c for c in (_clean_title(t) for t in titles) if c]
    return any(not _same_title(a, b) for a, b in combinations(cleaned, 2))


def _volume_communications(group: list[DoiClusterMember]) -> list[DoiClusterMember]:
    """Membres titrés d'un groupe à volume d'actes (`proceedings`) dont le titre diffère de celui de chaque volume. Vide sans volume titré."""
    volumes = [
        t
        for m in group
        if m.doc_type == DocType.PROCEEDINGS and (t := _clean_title(m.title_normalized))
    ]
    if not volumes:
        return []
    return [
        m
        for m in group
        if m.doc_type != DocType.PROCEEDINGS
        and (t := _clean_title(m.title_normalized))
        and not any(_same_title(t, v) for v in volumes)
    ]


SHARED_TITLE_WORDS_MIN = 0.35
_TITLE_WORD_MIN_LENGTH = 3


def _shared_title_words(a: str | None, b: str | None) -> float | None:
    """Part des mots du plus court des deux titres présents dans l'autre, mots de 3 lettres ou plus. `None` si l'un des titres n'a aucun mot retenu."""
    words_a = {w for w in (a or "").split() if len(w) >= _TITLE_WORD_MIN_LENGTH}
    words_b = {w for w in (b or "").split() if len(w) >= _TITLE_WORD_MIN_LENGTH}
    if not words_a or not words_b:
        return None
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def _depots_hal_d_une_autre_oeuvre(group: list[DoiClusterMember]) -> list[DoiClusterMember]:
    """Dépôts HAL dont le DOI est celui d'une autre œuvre.

    Un dépôt HAL du groupe est retenu quand deux conditions sont réunies face à l'enregistrement source Crossref du DOI :
    - aucun nom de famille d'auteur commun ;
    - moins de 35 % des mots du plus court des deux titres présents dans l'autre (`SHARED_TITLE_WORDS_MIN`).

    Les titres sont les titres normalisés, réduits aux mots de 3 lettres ou plus : les mots grammaticaux et les restes de formules mathématiques ne comptent pas. Seules les contributions sources individuelles comptent. Un dépôt ou un enregistrement source Crossref sans contribution source individuelle reste hors de la comparaison.
    """
    crossref = [m for m in group if m.source == Source.CROSSREF and m.author_names]
    if len(crossref) != 1:
        return []
    reference = crossref[0]
    return [
        m
        for m in group
        if m.source == Source.HAL
        and m.author_names
        and not m.author_names & reference.author_names
        and (shared := _shared_title_words(m.title_normalized, reference.title_normalized))
        is not None
        and shared < SHARED_TITLE_WORDS_MIN
    ]


def _meme_oeuvre(member: DoiClusterMember, shared_doi: str) -> bool:
    """Vrai si la relation déclarée par `member` désigne une autre forme de la même œuvre que le DOI partagé (cf. `meme_oeuvre_declaree`)."""
    if (
        member.same_work_case is None
        or member.canonical_doi is None
        or member.canonical_doi == shared_doi
    ):
        return False
    return meme_oeuvre_declaree(
        member.same_work_case, member.doc_type, shared_doi, member.canonical_doi
    )


def doi_target(
    group: list[DoiClusterMember], *, shared_doi: str, unresolved: bool = False
) -> DoiTarget | None:
    """Cible de `shared_doi` quand un membre du groupe le déclare forme secondaire de l'œuvre de son `canonical_doi` (cf. `_meme_oeuvre`) : version → concept, variante → version publiée, fichier → dépôt parent. Un DOI inconnu de doi.org (`unresolved`) n'a pas de cible."""
    if unresolved:
        return None
    canonical = next((m for m in group if _meme_oeuvre(m, shared_doi)), None)
    if canonical is None:
        return None
    assert canonical.canonical_doi is not None and canonical.same_work_case is not None
    return DoiTarget(shared_doi, canonical.canonical_doi, canonical.same_work_case)


def resolve_cluster_doi_corrections(
    group: list[DoiClusterMember], *, shared_doi: str, unresolved: bool = False
) -> list[DoiClusterDecision]:
    """Pour un groupe de `source_records` partageant `shared_doi`, renvoie les membres qui perdent le DOI, avec le cas qui le décide. Pur, déterministe, sans effet de bord, agnostique de la source — c'est le caller qui forme le groupe par DOI.

    - **DOI inconnu de doi.org** (`unresolved`) : tous les membres perdent le DOI. Prime sur les cas ci-dessous.
    - **Même œuvre DataCite** (`doi_target`) : aucun membre ne perd le DOI. Prime sur les cas ci-dessous, réservés à la famille ouvrage/chapitre.
    - **Ouvrage + chapitre** : les `book_chapter` d'un autre titre que l'ouvrage perdent le DOI, celui de l'ouvrage. Un chapitre au titre de l'ouvrage est la même œuvre, typée autrement par sa source : il garde le DOI.
    - **Chapitres seuls, titres réellement différents** : tous les `book_chapter` perdent le DOI (celui de l'ouvrage hôte absent). Détection par nettoyage + containment + égalité stricte (`_group_has_distinct_chapters`), sans similarité floue. Les faux positifs résiduels (coquilles) relèvent d'une correction admin.
    - **Volume d'actes + communications** : les membres dont le titre diffère de celui du volume (`proceedings`) perdent le DOI, quel que soit leur type. Les membres au titre du volume le gardent.
    - **Dépôt HAL d'une autre œuvre** (`_depots_hal_d_une_autre_oeuvre`) : un dépôt HAL sans nom d'auteur commun avec l'enregistrement source Crossref du DOI, et dont le titre partage moins de 35 % de ses mots avec elle, perd le DOI. S'ajoute aux cas précédents.

    Hors de ces cas, un membre partageant le DOI par accident ne reçoit aucune décision.

    Différé : thèse/article (souvent un mistype → correction de `doc_type`, pas du DOI)."""
    if unresolved:
        return [DoiClusterDecision(m.id, DoiClusterCase.UNRESOLVED_DOI_TO_NULL) for m in group]
    if doi_target(group, shared_doi=shared_doi) is not None:
        return []

    decisions = _divergence_decisions(group)
    decided = {d.id for d in decisions}
    return decisions + [
        DoiClusterDecision(m.id, DoiClusterCase.HAL_DOI_D_UNE_AUTRE_OEUVRE)
        for m in _depots_hal_d_une_autre_oeuvre(group)
        if m.id not in decided
    ]


def _divergence_decisions(group: list[DoiClusterMember]) -> list[DoiClusterDecision]:
    """Décisions des familles ouvrage/chapitre et volume d'actes/communication."""
    book_family = [m for m in group if m.doc_type in (DocType.BOOK, DocType.BOOK_CHAPTER)]
    chapters = [m for m in book_family if m.doc_type == DocType.BOOK_CHAPTER]
    has_book = any(m.doc_type == DocType.BOOK for m in book_family)
    if has_book and chapters:
        book_titles = [
            _clean_title(m.title_normalized) for m in book_family if m.doc_type == DocType.BOOK
        ]
        return [
            DoiClusterDecision(m.id, DoiClusterCase.OUVRAGE_VS_CHAPITRE)
            for m in chapters
            if not any(_same_title(_clean_title(m.title_normalized), t) for t in book_titles if t)
        ]
    if (
        chapters
        and not has_book
        and _group_has_distinct_chapters([m.title_normalized for m in chapters])
    ):
        return [
            DoiClusterDecision(m.id, DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS) for m in chapters
        ]
    return [
        DoiClusterDecision(m.id, DoiClusterCase.ACTES_VS_COMMUNICATION)
        for m in _volume_communications(group)
    ]
