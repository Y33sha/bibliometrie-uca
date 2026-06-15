"""Règles pures de déduplication des publications.

Cascade de matching par identifiants (`decide_publication_match`). Décideur pur — le caller prefetch les lookups via le repo et applique les effets (création, fusion). Un DOI qui pointe une publication existante est un match positif comme les autres clés ; les conflits chapitre/ouvrage (DOI de l'ouvrage porté par erreur par un chapitre) sont neutralisés **a priori** par la correction relationnelle (`metadata_correction` cluster), qui nulle le DOI erroné sur la `source_publication` avant le matching — il n'y a donc plus d'arbitrage DOI à la création.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class DeduplicationKey(StrEnum):
    """Identifiants cross-source par lesquels une publication peut être dédupliquée.

    L'enum ne fixe pas de priorité : l'ordre de la cascade est défini dans `decide_publication_match` (DOI > NNT > HAL_ID > PMID > metadata). `StrEnum` (PEP 663) garde la valeur sérialisable telle quelle.
    """

    DOI = "doi"
    NNT = "nnt"
    HAL_ID = "hal_id"
    PMID = "pmid"


class MetadataDeduplicationCase(StrEnum):
    """Cas de déduplication par métadonnées : combinaisons explicites de critères qui rendent deux publications considérées comme la même (pas un score, pas d'identifiant unique partagé).

    Chaque membre énonce sa règle métier dans le commentaire qui le précède. L'implémentation concrète (prefetch + matching) vit dans `application/pipeline/publications/metadata_deduplication_rules.py`, fonction `match_<nom_du_cas>`.
    """

    # Thèse : même `title_normalized`, même `pub_year`, compatibilité de
    # l'auteur primary (helper `thesis_authors_compatible`). Si l'auteur du
    # `source_publication` courant est inconnu, le candidat est accepté
    # sans vérification.
    # Implémentation : `match_thesis_by_title_year`.
    THESIS_TITLE_YEAR = "thesis_title_year"

    # Proceedings : `doc_type = 'proceedings'`, même `title_normalized`
    # (longueur > 30 pour exclure les titres pauvres type « Foreword »),
    # même `pub_year`, même nombre d'auteurs non-excluded (count direct
    # sur le SP courant comparé au `MAX` par source sur les SP de la pub
    # canonique candidate), et au moins un des deux DOI null (la
    # contrainte UNIQUE sur `lower(doi)` exclut l'égalité, donc deux DOI
    # non-nuls = différents = conflit).
    # Implémentation : `match_proceedings_by_title_year_authorcount`.
    PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT = "proceedings_title_year_authorcount"


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
    pmid_match_id: int | None = None,
    metadata_match: tuple[int, MetadataDeduplicationCase] | None = None,
) -> PublicationMatchDecision:
    """Sélecteur de cascade pur : premier match non-None dans l'ordre de priorité gagne.

    Priorité par défaut : DOI > NNT > HAL_ID > PMID > metadata. Tous les paramètres sont optionnels (None par défaut) ; le caller passe ceux qu'il a pré-fetchés.

    Pour le DOI, le caller passe `doi_merge_with_id` = l'id de la publication portant ce DOI (None si aucune). Pas d'arbitrage chapitre/ouvrage ici : il est traité en amont par la correction relationnelle qui nulle le DOI erroné sur la SP.

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
    if pmid_match_id is not None:
        return PublicationMatchDecision(
            action="match",
            publication_id=pmid_match_id,
            matched_by=DeduplicationKey.PMID,
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
