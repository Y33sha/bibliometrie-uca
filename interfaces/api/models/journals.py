"""Modèles Pydantic pour les revues (journals).

Les DTOs de retour des query services (`JournalOut`, `JournalListResponse`,
`JournalBasic`) vivent dans `application/ports/api/journals_queries.py`
(cf. chantier `CODE_typage-projections-strict` Phase 4).
"""

from pydantic import BaseModel


class JournalUpdate(BaseModel):
    title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    doi_prefix: str | None = None
    oa_model: str | None = None
    journal_type: str | None = None
    is_academic: bool | None = None
    is_predatory: bool | None = None
    is_in_doaj: bool | None = None
    apc_amount: float | None = None
    notes: str | None = None
