"""Modèles Pydantic propres au routeur des publications."""

from pydantic import BaseModel


class DocTypeOut(BaseModel):
    """Type de document et ses libellés français."""

    value: str
    label: str
    plural_label: str


class DocTypeFamilyOut(BaseModel):
    """Famille de types de document, ses types dans l'ordre d'affichage."""

    key: str
    label: str
    types: list[DocTypeOut]


class PublicationMergeRequest(BaseModel):
    """Publication à fusionner avec celle désignée par le chemin."""

    other_id: int


class PublicationMergeResult(BaseModel):
    """Résultat d'une fusion manuelle, ou de son aperçu. `publication_id` : publication issue de la fusion. `conflicts` : contributions dont les contributions sources désignaient deux personnes, laissées sans personne."""

    publication_id: int
    conflicts: int
