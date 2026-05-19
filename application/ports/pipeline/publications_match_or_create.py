"""Port : SQL de la phase publications (`match_or_create_publications`).

Implémenté par `infrastructure.queries.publications.match_or_create.PgPublicationsMatchOrCreateQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class SourcePublicationRow(NamedTuple):
    """Projection SQL pour la phase match_or_create.

    Colonnes de `source_publications` consommées par `process_document` plus la colonne dérivée `in_perimeter` (TRUE ssi au moins un `source_authorship` rattaché est in_perimeter), utilisée pour gater la création d'une publication canonique.
    """

    id: int
    source: str
    source_id: str
    doi: str | None
    title: str
    pub_year: int | None
    doc_type: str | None
    journal_id: int | None
    oa_status: str | None
    language: str | None
    container_title: str | None
    external_ids: dict[str, object] | None
    in_perimeter: bool


class PublicationsMatchOrCreateQueries(Protocol):
    """Opérations SQL pour le rattachement (match ou création) des `source_publications` aux `publications` canoniques."""

    def fetch_orphan_source_publications(self, conn: Connection) -> list[SourcePublicationRow]: ...

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None: ...

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_thesis_primary_author_from_source_publication(
        self, conn: Connection, source_publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_stale_publication_ids(self, conn: Connection) -> list[int]: ...
