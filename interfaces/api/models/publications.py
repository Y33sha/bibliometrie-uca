"""Modèles Pydantic propres au routeur des publications."""

from application.ports.model import Model


class DocTypeOut(Model):
    """Type de document et ses libellés français."""

    value: str
    label: str
    plural_label: str


class DocTypeFamilyOut(Model):
    """Famille de types de document, ses types dans l'ordre d'affichage."""

    key: str
    label: str
    types: list[DocTypeOut]


class PublicationMergeRequest(Model):
    """Publication à fusionner avec celle désignée par le chemin."""

    other_id: int


class PublicationMergeResult(Model):
    """Résultat d'une fusion manuelle, ou de son aperçu."""

    publication_id: int
    """Publication issue de la fusion."""
    conflicts: int
    """Nombre de contributions laissées sans personne : leurs contributions sources désignaient deux personnes."""
