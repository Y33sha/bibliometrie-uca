"""Port PublicationRepository — contrat d'accès à l'agrégat Publication.

Implémenté par infrastructure/repositories/publication_repository.py.
"""

from dataclasses import dataclass
from typing import Protocol

from domain.publications.publication import Publication
from domain.source_publications.views import SourcePublicationWithJournalView


@dataclass(frozen=True, slots=True)
class PubByDoi:
    """Projection de lecture retournée par `find_by_doi`.

    Porte les champs nécessaires à `resolve_doi_conflict` (arbitrage
    chapter/book) sans hydrater l'agrégat complet.
    """

    id: int
    doc_type: str | None
    title_normalized: str | None


class PublicationRepository(Protocol):
    """Contrat d'accès à l'agrégat Publication (tables publications,
    source_publications et distinct_publications)."""

    # ── Chargement / persistance de l'aggregate ────────────────────

    def find_by_id(self, pub_id: int) -> Publication | None: ...

    def save(self, pub: Publication) -> None: ...

    # ── Recherches (projections de lecture) ────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None: ...

    def find_by_nnt(self, nnt: str) -> int | None: ...

    def find_by_hal_id(self, hal_id: str) -> int | None: ...

    def find_by_pmid(self, pmid: str) -> int | None: ...

    def find_ids_by_journal_id(self, journal_id: int) -> list[int]:
        """Ids des publications rattachées à ce journal. Utilisé pour requalifier le stock quand un input éditable du journal (ex. `journal_type`) change."""
        ...

    def find_thesis_by_title(
        self,
        title_normalized: str,
        pub_year: int,
    ) -> list[int]: ...

    def find_proceedings_by_title_year(
        self,
        title_normalized: str,
        pub_year: int,
    ) -> list[tuple[int, str | None]]:
        """Cherche des proceedings par titre normalisé long (>30 car.) + année.

        Retourne `(pub_id, doi)` pour chaque candidate, le DOI permettant au
        caller de filtrer les conflits sans réhydrater l'agrégat.
        """
        ...

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None: ...

    def update_sources(self, pub_id: int) -> None: ...

    # ── Accès bas niveau au DOI ────────────────────────────────────

    def get_doi(self, pub_id: int) -> str | None: ...

    def set_doi(self, pub_id: int, doi: str) -> None: ...

    def clear_doi(self, pub_id: int) -> None: ...

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
