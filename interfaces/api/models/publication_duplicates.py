"""Modèles Pydantic du router de déduplication des publications : corps des requêtes entrantes. La fusion rend le `MergeResponse` partagé."""

from pydantic import BaseModel


class MergePublications(BaseModel):
    pub_id_a: int
    pub_id_b: int


class MarkDistinctPublications(BaseModel):
    pub_id_a: int
    pub_id_b: int
