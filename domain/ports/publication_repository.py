"""Port PublicationRepository — contrat d'accès à l'agrégat Publication.

Implémenté par infrastructure/repositories/publication_repository.py.
"""

from typing import Protocol

from domain.publication import (
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)


class PublicationRepository(Protocol):
    """Contrat d'accès à l'agrégat Publication (tables publications,
    source_publications et distinct_publications)."""

    # ── Recherches ─────────────────────────────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None: ...

    def find_by_nnt(self, nnt: str) -> PubByNnt | None: ...

    def find_by_title(
        self,
        title_normalized: str,
        pub_year: int,
        journal_id: int,
    ) -> PubByTitle | None: ...

    def find_thesis_by_title(
        self,
        title_normalized: str,
        pub_year: int,
    ) -> list[PubThesisCandidate]: ...

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None: ...

    def update_countries(self, pub_id: int, countries: list[str]) -> None: ...

    def update_sources(self, pub_id: int) -> None: ...

    # ── Accès bas niveau au DOI ────────────────────────────────────

    def get_doi(self, pub_id: int) -> str | None: ...

    def set_doi(self, pub_id: int, doi: str) -> None: ...

    def clear_doi(self, pub_id: int) -> None: ...

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_rows(self, pub_id: int) -> list[dict]: ...

    def update_aggregated(
        self,
        pub_id: int,
        *,
        doi: str | None,
        doc_type: str,
        pub_year: int | None,
        journal_id: int | None,
        oa_status: str | None,
        container_title: str | None,
        language: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        countries: list[str] | None,
        topics: dict | None,
        biblio: dict | None,
        meta: dict | None,
        is_retracted: bool,
    ) -> None: ...

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

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(
        self,
        pub_id_a: int,
        pub_id_b: int,
    ) -> tuple[int, int] | None: ...


class AsyncPublicationRepository(Protocol):
    """Variante async de PublicationRepository (§2.12).

    Implémentée par infrastructure/repositories/async_publication_repository.py.
    """

    # ── Recherches ─────────────────────────────────────────────────

    async def find_by_doi(self, doi: str) -> PubByDoi | None: ...

    async def find_by_nnt(self, nnt: str) -> PubByNnt | None: ...

    async def find_by_title(
        self,
        title_normalized: str,
        pub_year: int,
        journal_id: int,
    ) -> PubByTitle | None: ...

    async def find_thesis_by_title(
        self,
        title_normalized: str,
        pub_year: int,
    ) -> list[PubThesisCandidate]: ...

    # ── Écritures simples ──────────────────────────────────────────

    async def update_oa_status(self, pub_id: int, oa_status: str) -> None: ...

    async def update_countries(self, pub_id: int, countries: list[str]) -> None: ...

    async def update_sources(self, pub_id: int) -> None: ...

    # ── Accès bas niveau au DOI ────────────────────────────────────

    async def get_doi(self, pub_id: int) -> str | None: ...

    async def set_doi(self, pub_id: int, doi: str) -> None: ...

    async def clear_doi(self, pub_id: int) -> None: ...

    # ── Agrégation depuis source_publications ──────────────────────

    async def get_source_rows(self, pub_id: int) -> list[dict]: ...

    async def update_aggregated(
        self,
        pub_id: int,
        *,
        doi: str | None,
        doc_type: str,
        pub_year: int | None,
        journal_id: int | None,
        oa_status: str | None,
        container_title: str | None,
        language: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        countries: list[str] | None,
        topics: dict | None,
        biblio: dict | None,
        meta: dict | None,
        is_retracted: bool,
    ) -> None: ...

    # ── Création ───────────────────────────────────────────────────

    async def create(
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

    async def merge_into(self, target_id: int, source_id: int) -> None: ...

    # ── distinct_publications ──────────────────────────────────────

    async def mark_distinct(
        self,
        pub_id_a: int,
        pub_id_b: int,
    ) -> tuple[int, int] | None: ...
