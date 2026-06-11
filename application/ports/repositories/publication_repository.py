"""Port PublicationRepository — contrat d'accès à l'agrégat Publication.

Implémenté par infrastructure/repositories/publication_repository.py.
"""

from typing import Protocol

from domain.publications.publication import Publication
from domain.source_publications.views import SourcePublicationWithJournalView


class PublicationRepository(Protocol):
    """Contrat d'accès à l'agrégat Publication (tables publications,
    source_publications et distinct_publications)."""

    # ── Chargement / persistance de l'aggregate ────────────────────

    def find_by_id(self, pub_id: int) -> Publication | None: ...

    def save(self, pub: Publication) -> None: ...

    # ── Recherches ─────────────────────────────────────────────────

    def find_ids_by_journal_id(self, journal_id: int) -> list[int]:
        """Ids des publications rattachées à ce journal. Utilisé pour requalifier le stock quand un input éditable du journal (ex. `journal_type`) change."""
        ...

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None: ...

    def update_sources(self, pub_id: int) -> None: ...

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_publications(self, pub_id: int) -> list[SourcePublicationWithJournalView]: ...

    # ── Création ───────────────────────────────────────────────────

    def create(
        self,
        *,
        title: str,
        title_normalized: str,
        doc_type: str,
        pub_year: int,
        doi: str | None,
        oa_status: str,
        journal_id: int | None,
        container_title: str | None,
        language: str | None,
    ) -> int: ...

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_into(self, target_id: int, source_id: int) -> None: ...

    # ── Suppression ────────────────────────────────────────────────

    def delete(self, pub_id: int) -> None: ...

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(
        self,
        pub_id_a: int,
        pub_id_b: int,
    ) -> tuple[int, int] | None: ...

    def are_distinct(self, pub_id_a: int, pub_id_b: int) -> bool:
        """True si la paire est inscrite dans `distinct_publications`."""
        ...
