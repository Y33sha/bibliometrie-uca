"""Modèles Pydantic (router-only) pour la déduplication de publications (admin).

Les DTOs de retour du query service (`PubDedupDetail`, `PubDuplicatePair`, `PubDuplicateNextResponse`, et les sous-types) vivent dans `application/ports/api/publication_duplicates_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4). Restent ici les bodies POST (`MergePublications`, `MarkDistinctPublications`) et la réponse construite par le router après merge (`PubMergeResponse`).
"""

from pydantic import BaseModel


class MergePublications(BaseModel):
    target_id: int
    source_id: int


class MarkDistinctPublications(BaseModel):
    pub_id_a: int
    pub_id_b: int


class PubMergeResponse(BaseModel):
    ok: bool
    target_id: int
    source_id: int
