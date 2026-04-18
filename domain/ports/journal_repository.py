"""Port JournalRepository — contrat d'accès aux agrégats Journal et Publisher.

Implémenté par infrastructure/repositories/journal_repository.py.
Un seul port pour les deux tables car leurs opérations (notamment les
fusions éditeur↔journal) sont trop couplées pour être séparées.
"""

from typing import Protocol


class JournalRepository(Protocol):
    """Contrat d'accès aux agrégats Journal et Publisher."""

    # ── publisher_name_forms ───────────────────────────────────────

    def add_publisher_name_form(
        self,
        publisher_id: int,
        form_normalized: str,
    ) -> None: ...

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None: ...

    # ── publishers ─────────────────────────────────────────────────

    def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def set_publisher_openalex_id_if_missing(
        self,
        publisher_id: int,
        openalex_id: str,
    ) -> None: ...

    def create_publisher(
        self,
        *,
        name: str,
        name_normalized: str,
        openalex_id: str | None,
    ) -> int: ...

    # ── journal_name_forms ─────────────────────────────────────────

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None: ...

    def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None: ...

    # ── journals ───────────────────────────────────────────────────

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def find_journal_by_issn_any(self, issn_value: str) -> int | None: ...

    def enrich_journal(
        self,
        journal_id: int,
        *,
        issn: str | None = None,
        eissn: str | None = None,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: str | None = None,
    ) -> None: ...

    def create_journal(
        self,
        *,
        title: str,
        title_normalized: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: str | None,
    ) -> int: ...

    # ── Updates génériques ─────────────────────────────────────────

    def journal_exists(self, journal_id: int) -> bool: ...

    def publisher_exists(self, publisher_id: int) -> bool: ...

    def update_journal_fields(self, journal_id: int, fields: dict) -> None: ...

    def update_publisher_fields(self, publisher_id: int, fields: dict) -> None: ...

    # ── APC / DOAJ ─────────────────────────────────────────────────

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
        is_in_doaj: bool | None = None,
    ) -> None: ...

    def reset_journal_apc(self) -> int: ...

    # ── Fusion ─────────────────────────────────────────────────────

    def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[dict]: ...

    def merge_publisher_into(self, target_id: int, source_id: int) -> None: ...

    def merge_journal_into(self, target_id: int, source_id: int) -> None: ...
