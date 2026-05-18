"""Modèles Pydantic (router-only) pour la déduplication de publications (admin).

Les DTOs de retour du query service (`PubDedupDetail`, `PubDuplicatePair`, `PubDuplicateNextResponse`, et les sous-types) vivent dans `application/ports/api/publication_duplicates_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4). Reste ici la réponse construite par le router après merge.
"""

from pydantic import BaseModel


class PubMergeResponse(BaseModel):
    ok: bool
    target_id: int
    source_id: int
