"""Modèles Pydantic du router de déduplication des publications : corps des requêtes entrantes. La fusion rend le `MergeResponse` partagé."""

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


