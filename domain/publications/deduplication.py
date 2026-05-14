"""Règles pures de déduplication des publications.

Cascade de matching par identifiants (`decide_publication_match`) et résolution de conflit DOI chapter/book (`resolve_doi_conflict`). Tous les décideurs sont purs — le caller prefetch les lookups via le repo et applique les effets (création, fusion, clear_doi).

Asymétrie volontaire DOI vs autres clés (NNT, HAL_ID) : `resolve_doi_conflict` est DOI-spécifique parce que DOI est l'unique identifiant **canonique attribuable** à une publication (colonne propre `publications.doi` avec contrainte UNIQUE `lower(doi)`, règle chapter/book métier). Pour NNT/HAL_ID, le matching passe par `decide_publication_match` (cascade) et la résolution des conflits cross-source par les phases pipeline dédiées `merge_pubs_by_nnt` / `merge_pubs_by_hal_id`. L'attribution post-match d'un DOI à une pub matchée par autre clé se fait désormais via `refresh_from_sources` (premier non-null par `SOURCE_PRIORITY`).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

_CHAPTER_DOC_TYPES: frozenset[str] = frozenset({"book_chapter", "book-chapter", "chapter"})
_BOOK_DOC_TYPES: frozenset[str] = frozenset({"book"})


class DeduplicationKey(str, Enum):
    """Identifiants cross-source par lesquels une publication peut être dédupliquée.

    Conventionnellement ordre de priorité par défaut (DOI > NNT > HAL_ID), mais chaque cascade caller décide quelles clés elle consulte et dans quel ordre. Mixin `str` pour la sérialisation transparente.
    """

    DOI = "doi"
    NNT = "nnt"
    HAL_ID = "hal_id"


class MetadataDeduplicationCase(str, Enum):
    """Cas de déduplication par métadonnées (algorithme de décision, pas identifiant unique).

    Chaque cas correspond à une combinaison de critères qui rendent deux publications considérées comme la même. Un futur algorithme de dédup pourra ajouter de nouveaux cas (ex. `ARTICLE_TITLE_JOURNAL_YEAR`).
    """

    THESIS_TITLE_YEAR = "thesis_title_year"


@dataclass(frozen=True, slots=True)
class PublicationMatchDecision:
    """Décision rendue par `decide_publication_match`.

    `action='match'` : une publication existante a été identifiée. `publication_id` est posé, `matched_by` indique sur quelle clé.

    `action='create'` : aucun match, le caller doit créer. `publication_id` et `matched_by` sont None.
    """

    action: Literal["match", "create"]
    publication_id: int | None
    matched_by: DeduplicationKey | MetadataDeduplicationCase | None


def decide_publication_match(
    *,
    doi_merge_with_id: int | None = None,
    nnt_match_id: int | None = None,
    hal_id_match_id: int | None = None,
    metadata_match: tuple[int, MetadataDeduplicationCase] | None = None,
) -> PublicationMatchDecision:
    """Sélecteur de cascade pur : premier match non-None dans l'ordre de priorité gagne.

    Priorité par défaut : DOI > NNT > HAL_ID > metadata. Tous les paramètres sont optionnels (None par défaut) ; le caller passe ceux qu'il a pré-fetchés.

    Pour le DOI, le caller doit avoir préalablement appelé `resolve_doi_conflict` et passé `merge_with_id` (None si le conflit chapter/book a invalidé le match). `decide_publication_match` ne re-vérifie pas les invariants du DOI ; il fait confiance au merge_with_id pré-calculé.

    Le `metadata_match` est un tuple `(pub_id, case)` : l'id matché et le cas méta qui l'a produit.
    """
    if doi_merge_with_id is not None:
        return PublicationMatchDecision(
            action="match",
            publication_id=doi_merge_with_id,
            matched_by=DeduplicationKey.DOI,
        )
    if nnt_match_id is not None:
        return PublicationMatchDecision(
            action="match",
            publication_id=nnt_match_id,
            matched_by=DeduplicationKey.NNT,
        )
    if hal_id_match_id is not None:
        return PublicationMatchDecision(
            action="match",
            publication_id=hal_id_match_id,
            matched_by=DeduplicationKey.HAL_ID,
        )
    if metadata_match is not None:
        pub_id, case = metadata_match
        return PublicationMatchDecision(
            action="match",
            publication_id=pub_id,
            matched_by=case,
        )
    return PublicationMatchDecision(
        action="create",
        publication_id=None,
        matched_by=None,
    )


@dataclass(frozen=True, slots=True)
class DoiConflictResolution:
    """Décision pure pour un conflit DOI entre deux documents.

    - `accepted_doi` : DOI à utiliser pour le nouveau document (None =
      ne pas lui attribuer ce DOI).
    - `merge_with_id` : id de la publication existante à fusionner avec
      (None = pas de fusion).
    - `clear_existing_doi` : True si le DOI doit être retiré de la
      publication existante (effet de bord à appliquer par l'appelant).
    """

    accepted_doi: str | None
    merge_with_id: int | None
    clear_existing_doi: bool


def resolve_doi_conflict(
    new_doi: str,
    new_doc_type: str,
    new_title_normalized: str,
    existing_doc_type: str | None,
    existing_title_normalized: str | None,
    existing_id: int,
) -> DoiConflictResolution:
    """Règle pure : gère les conflits de DOI entre chapitres et ouvrages.

    Quand un DOI existe déjà sur une publication d'un type incompatible
    (chapitre vs ouvrage), le DOI est retiré de l'un ou des deux côtés
    au lieu de fusionner. Dans tous les autres cas, les types sont
    considérés compatibles et on fusionne.
    """
    ex_type = existing_doc_type or ""

    # Chapitre vs ouvrage : le DOI est celui de l'ouvrage, pas du chapitre
    if new_doc_type in _CHAPTER_DOC_TYPES and ex_type in _BOOK_DOC_TYPES:
        return DoiConflictResolution(
            accepted_doi=None, merge_with_id=None, clear_existing_doi=False
        )

    if new_doc_type in _BOOK_DOC_TYPES and ex_type in _CHAPTER_DOC_TYPES:
        return DoiConflictResolution(
            accepted_doi=new_doi, merge_with_id=None, clear_existing_doi=True
        )

    # Deux chapitres avec titres différents : DOI erroné des deux côtés
    if new_doc_type in _CHAPTER_DOC_TYPES and ex_type in _CHAPTER_DOC_TYPES:
        ex_title = existing_title_normalized or ""
        if new_title_normalized != ex_title:
            return DoiConflictResolution(
                accepted_doi=None, merge_with_id=None, clear_existing_doi=True
            )
        return DoiConflictResolution(
            accepted_doi=new_doi, merge_with_id=existing_id, clear_existing_doi=False
        )

    # Cas normal : même DOI, types compatibles → fusion
    return DoiConflictResolution(
        accepted_doi=new_doi, merge_with_id=existing_id, clear_existing_doi=False
    )
