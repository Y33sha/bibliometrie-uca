"""DTOs Pydantic pour le router /api/doc-types.

Cas particulier : pas de Protocol port — la route est statique
(sérialise `domain.publications.doc_types.DOC_TYPE_LABELS_FR`). Les
DTOs vivent quand même ici par cohérence avec les autres DTOs API
(zone où l'override mypy autorise le `Any` propagé par BaseModel).
"""

from pydantic import BaseModel


class DocTypeLabel(BaseModel):
    value: str
    singular: str
    plural: str


class DocTypeListResponse(BaseModel):
    items: list[DocTypeLabel]
