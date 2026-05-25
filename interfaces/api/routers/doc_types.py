"""Router /api/doc-types — expose la liste canonique des doc_types et leurs libellés FR.

Source de vérité : `domain.publications.doc_types.DOC_TYPE_LABELS_FR`.
Lecture statique (pas de port), publique (pas d'auth).
"""

import logging

from fastapi import APIRouter

from application.ports.api.doc_types_queries import DocTypeLabel, DocTypeListResponse
from domain.publications.doc_types import DOC_TYPE_LABELS_FR

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/doc-types", response_model=DocTypeListResponse)
def list_doc_types() -> DocTypeListResponse:
    """Liste les valeurs de l'enum `doc_type` avec leurs libellés FR (singulier, pluriel)."""
    items = [
        DocTypeLabel(value=value, singular=singular, plural=plural)
        for value, (singular, plural) in sorted(DOC_TYPE_LABELS_FR.items())
    ]
    return DocTypeListResponse(items=items)
