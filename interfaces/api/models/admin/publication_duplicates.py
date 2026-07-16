"""Modèles Pydantic (router-only) pour la déduplication de publications (admin).

Les modèles que rend le query service vivent auprès de leur port, dans `application/ports/api/publication_duplicates_queries.py`. Ici : les corps des requêtes POST (`MergePublications`, `MarkDistinctPublications`) et la réponse que le router compose après une fusion (`PublicationMergeResponse`).
"""

from pydantic import BaseModel


class MergePublications(BaseModel):
    # Paire symétrique : la direction de fusion n'a aucun effet durable côté
    # publications (les métadonnées canoniques sont re-dérivées des sources),
    # contrairement aux personnes. Le router choisit la cible (plus petit id).
    pub_id_a: int
    pub_id_b: int


class MarkDistinctPublications(BaseModel):
    pub_id_a: int
    pub_id_b: int


class PublicationMergeResponse(BaseModel):
    ok: bool
    target_id: int
    source_id: int
