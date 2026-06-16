"""Règles pures de déduplication des publications.

Cascade de matching par identifiants (`decide_publication_match`). Décideur pur — le caller prefetch les lookups via le repo et applique les effets (création, fusion). Un DOI qui pointe une publication existante est un match positif comme les autres clés ; les conflits chapitre/ouvrage (DOI de l'ouvrage porté par erreur par un chapitre) sont neutralisés **a priori** par la correction relationnelle (`metadata_correction` cluster), qui nulle le DOI erroné sur la `source_publication` avant le matching — il n'y a donc plus d'arbitrage DOI à la création.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class DeduplicationKey(StrEnum):
    """Clés de confirmation cross-source par lesquelles une publication peut être dédupliquée.

    L'enum ne fixe pas de priorité : l'ordre de la cascade est défini dans `decide_publication_match` (DOI > NNT > HAL_ID > PMID > THESIS_META). `StrEnum` (PEP 663) garde la valeur sérialisable telle quelle. `THESIS_META` est le **token** composite thèse `(title_normalized, pub_year)` : assez sélectif pour valoir identité par égalité (cf. `domain.source_publications.keys`), au même titre que les identifiants.
    """

    DOI = "doi"
    NNT = "nnt"
    HAL_ID = "hal_id"
    PMID = "pmid"
    THESIS_META = "thesis_meta"


@dataclass(frozen=True, slots=True)
class PublicationMatchDecision:
    """Décision rendue par `decide_publication_match`.

    `action='match'` : une publication existante a été identifiée. `publication_id` est posé, `matched_by` indique sur quelle clé.

    `action='create'` : aucun match, le caller doit créer. `publication_id` et `matched_by` sont None.
    """

    action: Literal["match", "create"]
    publication_id: int | None
    matched_by: DeduplicationKey | None


def decide_publication_match(
    *,
    doi_merge_with_id: int | None = None,
    nnt_match_id: int | None = None,
    hal_id_match_id: int | None = None,
    pmid_match_id: int | None = None,
    thesis_meta_match_id: int | None = None,
) -> PublicationMatchDecision:
    """Sélecteur de cascade pur : premier match non-None dans l'ordre de priorité gagne.

    Priorité par défaut : DOI > NNT > HAL_ID > PMID > THESIS_META. Tous les paramètres sont optionnels (None par défaut) ; le caller passe ceux qu'il a pré-fetchés.

    Pour le DOI, le caller passe `doi_merge_with_id` = l'id de la publication portant ce DOI (None si aucune). Pas d'arbitrage chapitre/ouvrage ici : il est traité en amont par la correction relationnelle qui nulle le DOI erroné sur la SP. `thesis_meta_match_id` = l'id d'une thèse existante de même titre+année (lookup `find_thesis_by_title`, sans garde — le couple titre+année est identifiant pour une thèse).
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
    if pmid_match_id is not None:
        return PublicationMatchDecision(
            action="match",
            publication_id=pmid_match_id,
            matched_by=DeduplicationKey.PMID,
        )
    if thesis_meta_match_id is not None:
        return PublicationMatchDecision(
            action="match",
            publication_id=thesis_meta_match_id,
            matched_by=DeduplicationKey.THESIS_META,
        )
    return PublicationMatchDecision(
        action="create",
        publication_id=None,
        matched_by=None,
    )
