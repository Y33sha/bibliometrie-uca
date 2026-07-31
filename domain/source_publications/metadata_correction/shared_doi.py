"""Correction du DOI d'un groupe d'enregistrements partageant un même DOI.

Les corrections unaires (`rules`) décident d'un enregistrement seul. Ici on regarde le **groupe de `source_publications` partageant un DOI** et on en déduit le DOI effectif de chaque membre. Deux familles opposées :

- **convergence (même œuvre)** : une forme secondaire DataCite converge sur le DOI de l'œuvre canonique, exposé par un `relatedIdentifiers` → substitution `doi = canonique`. Trois cas : version → concept (`IsVersionOf`) ; forme variante, ex. copie repository → version publiée (`IsVariantFormOf`) ; pièce d'un dataset → dataset parent (`IsPartOf` vers un DOI présent en base comme dataset, forme du DOI indifférente).
- **divergence (œuvres distinctes)** : un DOI partagé par des œuvres réellement distinctes (ouvrage/chapitre, chapitres de titres différents), erroné sur le ou les mauvais côtés → nullage du DOI sur ces membres.

La décision est **agnostique de la source** : le caller applicatif regroupe par DOI (brut reconstruit) et persiste la cible de chaque membre. La famille de cas est extensible.

`CONVERGENCE_CASES` liste les cas de convergence, où l'agrégation canonique relègue le membre en fin de priorité, pour que le titre vienne de l'enregistrement canonique. `DATACITE_DIRECT_CONVERGENCE` mappe la `relation_type` d'un `relatedIdentifiers` (vocabulaire DataCite, gardé en chaîne) au cas de correction ; la requête de candidats au clustering le consomme pour former son `CASE` et son filtre.
"""

import re
from enum import StrEnum
from itertools import combinations
from typing import NamedTuple

from domain.publications.doc_types import DocType


class DoiClusterCase(StrEnum):
    """Cas de correction du DOI d'un membre d'un groupe partageant un DOI. Inscrit dans `raw_metadata.doi.corrected_by`."""

    # Formes secondaires DataCite → convergence sur l'œuvre canonique.
    DATACITE_VERSION_TO_CONCEPT = "DATACITE_VERSION_TO_CONCEPT"  # version → concept (IsVersionOf)
    DATACITE_VARIANT_TO_PRIMARY = (
        "DATACITE_VARIANT_TO_PRIMARY"  # copie repository → version publiée (IsVariantFormOf)
    )
    DATACITE_PACKAGE_PIECE = (
        "DATACITE_PACKAGE_PIECE"  # pièce d'un dataset → dataset parent présent (IsPartOf)
    )

    # Ouvrage et chapitre partageant un DOI : le DOI appartient à l'ouvrage (`book`), le
    # `book_chapter` le porte à tort → le chapitre le perd.
    OUVRAGE_VS_CHAPITRE = "OUVRAGE_VS_CHAPITRE"

    # Plusieurs `book_chapter` partageant un DOI mais de titres réellement différents : le DOI
    # est celui de l'ouvrage hôte (absent du groupe), recopié sur ses chapitres → tous le perdent.
    CHAPITRES_TITRES_DIFFERENTS = "CHAPITRES_TITRES_DIFFERENTS"


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


class DoiClusterMember(NamedTuple):
    """Un membre d'un groupe de `source_publications` partageant un DOI : son id, son `doc_type` **canonique** (corrigé par la passe unaire) et son `title_normalized` (matérialisé). `canonical_doi` est le DOI de l'œuvre canonique vers laquelle converger, présent si ce membre (typiquement une `source_publication` `datacite`) est une **forme secondaire** déclarant la relation ; `same_work_case` porte alors le `DoiClusterCase` correspondant (version/variante/pièce de package)."""

    id: int
    doc_type: str | None
    title_normalized: str | None
    canonical_doi: str | None = None
    same_work_case: DoiClusterCase | None = None


class DoiClusterDecision(NamedTuple):
    """Cible de correction du DOI d'un membre : `target_doi` (`None` = nullage, sinon le DOI substitué) et le cas qui l'a produite."""

    id: int
    target_doi: str | None
    case: DoiClusterCase


# Marqueurs structurels de titre de chapitre, retirés avant comparaison : un chapitre est
# fréquemment saisi avec son numéro (« chapitre 14 … ») par une source et sans par une autre.
_CHAPTER_TITLE_MARKERS = re.compile(
    r"\b(chapitre|chapter|chap|ch|section|sec|partie|part|vol|tome|pp|p)\b"
)


def _clean_chapter_title(title_normalized: str | None) -> str:
    """Retire le bruit structurel d'un titre normalisé (chiffres = numéros de chapitre/page, mots-marqueurs) et re-collapse les espaces, pour comparer des **chapitres** au résidu de leur titre. Déterministe (identité stricte, aucune similarité floue)."""
    cleaned = re.sub(r"\d+", " ", title_normalized or "")
    cleaned = _CHAPTER_TITLE_MARKERS.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _group_has_distinct_chapters(titles: list[str | None]) -> bool:
    """True si le groupe contient deux chapitres **réellement distincts** : après nettoyage, une paire de titres ni égaux ni l'un contenu dans l'autre (la containment couvre les troncatures de sous-titre). Identité stricte sur le résidu, sans seuil flou."""
    cleaned = [c for c in (_clean_chapter_title(t) for t in titles) if c]
    return any(a != b and a not in b and b not in a for a, b in combinations(cleaned, 2))


def resolve_cluster_doi_corrections(
    group: list[DoiClusterMember],
) -> list[DoiClusterDecision]:
    """Pour un groupe de `source_publications` partageant un DOI, renvoie les corrections `(sp_id, target_doi, cas)`. Pur, déterministe, sans effet de bord, agnostique de la source — c'est le caller qui forme le groupe par DOI.

    - **Même œuvre DataCite** (un membre porte un `canonical_doi`) : tous les membres convergent sur l'œuvre canonique (`target_doi = canonical_doi`), avec le cas porté par ce membre (version → concept, variante → version publiée, fichier → dépôt parent). Prime sur les cas ci-dessous, réservés à la famille ouvrage/chapitre.
    - **Ouvrage + chapitre** : les `book_chapter` perdent le DOI (`target_doi = None`, celui de l'ouvrage). Signal = le mix de `doc_type`, sans comparaison de titre.
    - **Chapitres seuls, titres réellement différents** : tous les `book_chapter` perdent le DOI (celui de l'ouvrage hôte absent). Détection par nettoyage + containment + identité stricte (`_group_has_distinct_chapters`), sans similarité floue. Les faux positifs résiduels (coquilles) relèvent d'une correction admin.

    Les membres hors famille ouvrage (article partageant le DOI par accident) ne reçoivent aucune décision : la détection ouvrage/chapitre raisonne sur le sous-ensemble book/chapter.

    Différé : thèse/article (souvent un mistype → correction de `doc_type`, pas du DOI)."""
    canonical = next((m for m in group if m.canonical_doi), None)
    if canonical is not None and canonical.same_work_case is not None:
        case = canonical.same_work_case
        return [DoiClusterDecision(m.id, canonical.canonical_doi, case) for m in group]

    book_family = [m for m in group if m.doc_type in (DocType.BOOK, DocType.BOOK_CHAPTER)]
    chapters = [m for m in book_family if m.doc_type == DocType.BOOK_CHAPTER]
    has_book = any(m.doc_type == DocType.BOOK for m in book_family)
    if has_book and chapters:
        return [
            DoiClusterDecision(m.id, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE) for m in chapters
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
    return []
