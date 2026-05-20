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


class BulkLinkCounts(NamedTuple):
    """Compteurs retournés par `bulk_link_remaining_orphans` (phase B)."""

    by_doi: int
    by_nnt: int
    by_hal_id: int

    @property
    def total(self) -> int:
        return self.by_doi + self.by_nnt + self.by_hal_id


class PublicationsMatchOrCreateQueries(Protocol):
    """Opérations SQL pour le rattachement (match ou création) des `source_publications` aux `publications` canoniques."""

    def fetch_orphan_in_perimeter_source_publications(
        self, conn: Connection
    ) -> list[SourcePublicationRow]:
        """Phase A : orphelins avec ≥1 source_authorship in_perimeter.

        Seuls candidats à la création d'une publication canonique. Traités
        un par un via la cascade Python `decide_publication_match`.
        """

    def bulk_link_remaining_orphans(self, conn: Connection) -> BulkLinkCounts:
        """Phase B : rattache en bulk les orphelins restants (hors-périmètre).

        3 UPDATEs SQL set-based qui matchent par DOI, NNT, hal_id contre
        les publications canoniques. Pas de création (gated par
        `in_perimeter`). Bénéficie naturellement des publications créées
        en Phase A puisqu'elle tourne après.
        """

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
