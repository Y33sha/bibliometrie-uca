"""Correction du DOI d'un groupe d'enregistrements partageant un même DOI.

Les corrections unaires (`rules`) décident d'un enregistrement seul. Ici on regarde le **groupe de `source_records` partageant un DOI** et on en déduit le DOI effectif de chaque membre. Deux familles opposées :

- **convergence (même œuvre)** : une forme secondaire DataCite converge sur le DOI de l'œuvre principale, exposé par un `relatedIdentifiers` → substitution du DOI. Trois cas : version → concept (`IsVersionOf`) ; forme variante → forme principale (`IsVariantFormOf`) ; pièce d'un dataset → dataset parent (`IsPartOf` vers un DOI présent en base comme dataset, forme du DOI indifférente). Un fichier complémentaire figshare, sans relation déclarée, rejoint la collection figshare de même titre. Les conditions de préfixe sont décrites par `meme_oeuvre_declaree` ; une relation qui relie deux œuvres va à la phase `relations`.
- **divergence (œuvres distinctes)** : un DOI partagé par des œuvres réellement distinctes (ouvrage/chapitre, chapitres de titres différents, volume d'actes/communication, dépôt HAL d'une autre œuvre), erroné sur le ou les mauvais côtés → nullage du DOI sur ces membres. Les membres qui gardent le DOI perdent aussi les clés de confirmation qu'ils partagent avec ceux qui le perdent (`confirmation_id_removals`).

Un DOI que doi.org ne connaît pas est nullé sur tous les membres du groupe, avant toute autre décision.

La décision est **agnostique de la source** : le caller applicatif regroupe par DOI (brut reconstruit) et persiste la cible de chaque membre. La famille de cas est extensible.

`CONVERGENCE_CASES` liste les cas de convergence, où l'agrégation canonique relègue le membre en fin de priorité, pour que le titre vienne de l'enregistrement canonique. `DATACITE_DIRECT_CONVERGENCE` mappe la `relation_type` d'un `relatedIdentifiers` (vocabulaire DataCite, gardé en chaîne) au cas de correction ; la requête de candidats au clustering le consomme pour former son `CASE` et son filtre.
"""

import re
from collections.abc import Mapping
from enum import StrEnum
from itertools import combinations
from typing import NamedTuple

from domain.publications.doc_types import DocType
from domain.publications.identifiers import NNT, HALId, meme_registrant
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.keys import CONFIRMATION_ID_TYPES
from domain.sources.registry import Source
from domain.sources.scanr import extract_hal_id_from_scanr_id
from domain.types import JsonValue


class DoiClusterCase(StrEnum):
    """Cas de correction du DOI d'un membre d'un groupe partageant un DOI. Inscrit dans `corrections.doi.corrected_by`."""

    # Formes secondaires DataCite → convergence sur l'œuvre canonique.
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


# Cas de convergence (cf. docstring du module) : substitution du DOI du membre par celui de l'œuvre canonique.
CONVERGENCE_CASES: frozenset[str] = frozenset(
    {
        DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
        DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
        DoiClusterCase.DATACITE_PACKAGE_PIECE,
    }
)


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
    """Un membre d'un groupe de `source_records` partageant un DOI : son id, son `doc_type` **canonique** (corrigé par la passe unaire) et son `title_normalized` (matérialisé). `canonical_doi` est le DOI de l'œuvre canonique vers laquelle converger, présent si ce membre (typiquement une `source_record` `datacite`) est une **forme secondaire** déclarant la relation ; `same_work_case` porte alors le `DoiClusterCase` correspondant (version/variante/pièce de package)."""

    id: int
    doc_type: str | None
    title_normalized: str | None
    canonical_doi: str | None = None
    same_work_case: DoiClusterCase | None = None
    # Valeurs des clés de confirmation (`CONFIRMATION_ID_TYPES`) de ses identifiants externes, par type.
    confirmation_ids: Mapping[str, tuple[str, ...]] = {}
    # Identifiants propres de l'enregistrement source, par type : le `hal_id` d'un enregistrement source HAL, le NNT d'un enregistrement source theses.fr.
    own_ids: Mapping[str, tuple[str, ...]] = {}
    source: str = ""
    # Noms de famille normalisés de ses contributions sources individuelles.
    author_names: frozenset[str] = frozenset()


class DoiClusterDecision(NamedTuple):
    """Cible de correction du DOI d'un membre : `target_doi` (`None` = nullage, sinon le DOI substitué) et le cas qui l'a produite."""

    id: int
    target_doi: str | None
    case: DoiClusterCase


class ConfirmationIdRemoval(NamedTuple):
    """Identifiants externes retirés d'un membre qui garde le DOI partagé : par type, les valeurs qu'il partage avec un membre qui perd le DOI."""

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


def confirmation_ids(external_ids: Mapping[str, JsonValue]) -> dict[str, tuple[str, ...]]:
    """Valeurs des clés de confirmation d'un `external_ids`, par type."""
    out: dict[str, tuple[str, ...]] = {}
    for id_type in CONFIRMATION_ID_TYPES:
        value = external_ids.get(id_type)
        values = value if isinstance(value, list) else [value]
        if kept := tuple(v for v in values if isinstance(v, str)):
            out[id_type.value] = kept
    return out


def source_record_own_ids(source: str, source_id: str) -> dict[str, tuple[str, ...]]:
    """Identifiants propres d'un enregistrement source, par type : le dépôt HAL d'un enregistrement source HAL ou d'un enregistrement source ScanR issu de HAL, le NNT d'un enregistrement source theses.fr."""
    if source == Source.HAL:
        hal_id = HALId.try_parse(source_id)
    elif source == Source.SCANR:
        hal_id = HALId.try_parse(extract_hal_id_from_scanr_id(source_id) or "")
    elif source == Source.THESES:
        nnt = NNT.try_parse(source_id)
        return {ExternalIdType.NNT.value: (str(nnt),)} if nnt else {}
    else:
        return {}
    return {ExternalIdType.HAL_ID.value: (str(hal_id),)} if hal_id else {}


def confirmation_id_removals(
    group: list[DoiClusterMember], decisions: list[DoiClusterDecision]
) -> list[ConfirmationIdRemoval]:
    """Retraits d'identifiants externes après une divergence (`DIVERGENCE_CASES`).

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
    """Vrai si la relation déclarée par `member` désigne la même œuvre que le DOI partagé (cf. `meme_oeuvre_declaree`)."""
    if member.same_work_case is None or member.canonical_doi is None:
        return False
    return meme_oeuvre_declaree(
        member.same_work_case, member.doc_type, shared_doi, member.canonical_doi
    )


def resolve_cluster_doi_corrections(
    group: list[DoiClusterMember], *, shared_doi: str, unresolved: bool = False
) -> list[DoiClusterDecision]:
    """Pour un groupe de `source_records` partageant `shared_doi`, renvoie les corrections `(source_record_id, target_doi, cas)`. Pur, déterministe, sans effet de bord, agnostique de la source — c'est le caller qui forme le groupe par DOI.

    - **DOI inconnu de doi.org** (`unresolved`) : tous les membres perdent le DOI. Prime sur les cas ci-dessous.
    - **Même œuvre DataCite** (un membre porte un `canonical_doi`, cf. `_meme_oeuvre`) : tous les membres convergent sur l'œuvre principale (`target_doi = canonical_doi`), avec le cas porté par ce membre (version → concept, variante → version publiée, fichier → dépôt parent). Prime sur les cas ci-dessous, réservés à la famille ouvrage/chapitre.
    - **Ouvrage + chapitre** : les `book_chapter` d'un autre titre que l'ouvrage perdent le DOI (`target_doi = None`, celui de l'ouvrage). Un chapitre au titre de l'ouvrage est la même œuvre, typée autrement par sa source : il garde le DOI.
    - **Chapitres seuls, titres réellement différents** : tous les `book_chapter` perdent le DOI (celui de l'ouvrage hôte absent). Détection par nettoyage + containment + égalité stricte (`_group_has_distinct_chapters`), sans similarité floue. Les faux positifs résiduels (coquilles) relèvent d'une correction admin.
    - **Volume d'actes + communications** : les membres dont le titre diffère de celui du volume (`proceedings`) perdent le DOI, quel que soit leur type. Les membres au titre du volume le gardent.
    - **Dépôt HAL d'une autre œuvre** (`_depots_hal_d_une_autre_oeuvre`) : un dépôt HAL sans nom d'auteur commun avec l'enregistrement source Crossref du DOI, et dont le titre partage moins de 35 % de ses mots avec elle, perd le DOI. S'ajoute aux cas précédents.

    Hors de ces cas, un membre partageant le DOI par accident ne reçoit aucune décision.

    Différé : thèse/article (souvent un mistype → correction de `doc_type`, pas du DOI)."""
    if unresolved:
        return [
            DoiClusterDecision(m.id, None, DoiClusterCase.UNRESOLVED_DOI_TO_NULL) for m in group
        ]
    canonical = next((m for m in group if _meme_oeuvre(m, shared_doi)), None)
    if canonical is not None:
        assert canonical.canonical_doi is not None and canonical.same_work_case is not None
        case = canonical.same_work_case
        return [DoiClusterDecision(m.id, canonical.canonical_doi, case) for m in group]

    decisions = _divergence_decisions(group)
    decided = {d.id for d in decisions}
    return decisions + [
        DoiClusterDecision(m.id, None, DoiClusterCase.HAL_DOI_D_UNE_AUTRE_OEUVRE)
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
            DoiClusterDecision(m.id, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE)
            for m in chapters
            if not any(_same_title(_clean_title(m.title_normalized), t) for t in book_titles if t)
        ]
    if (
        chapters
        and not has_book
        and _group_has_distinct_chapters([m.title_normalized for m in chapters])
    ):
        return [
            DoiClusterDecision(m.id, None, DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS)
            for m in chapters
        ]
    return [
        DoiClusterDecision(m.id, None, DoiClusterCase.ACTES_VS_COMMUNICATION)
        for m in _volume_communications(group)
    ]
