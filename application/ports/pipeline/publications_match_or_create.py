"""Port : SQL de la phase publications (`match_or_create_publications`).

Implémenté par `infrastructure.queries.pipeline.publications_match_or_create.PgPublicationsMatchOrCreateQueries`.
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
    urls: list[str] | None
    in_perimeter: bool


class PublicationsMatchOrCreateQueries(Protocol):
    """Opérations SQL pour le rattachement (match ou création) des `source_publications` aux `publications` canoniques."""

    def fetch_orphan_in_perimeter_source_publications(
        self, conn: Connection
    ) -> list[SourcePublicationRow]:
        """Phase A : orphelins avec ≥1 source_authorship in_perimeter.

        Seuls candidats à la création d'une publication canonique. Traités
        un par un via la cascade Python `decide_publication_match`.
        """

    def bulk_link_orphans_by_doi(self, conn: Connection) -> int:
        """Phase B step 1/4 : rattache les orphelins par DOI."""

    def bulk_link_orphans_by_nnt(self, conn: Connection) -> int:
        """Phase B step 2/4 : rattache les orphelins par NNT
        (stocké sur `source_publications.external_ids`)."""

    def bulk_link_orphans_by_hal_id(self, conn: Connection) -> int:
        """Phase B step 3/4 : rattache les orphelins par hal_id
        (deux donor paths : SP HAL native via `source_id`, OU SP
        cross-source via `external_ids->>'hal_id'`)."""

    def bulk_link_orphans_by_pmid(self, conn: Connection) -> int:
        """Phase B step 4/4 : rattache les orphelins par PMID
        (stocké sur `source_publications.external_ids`)."""

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None: ...

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_thesis_primary_author_from_source_publication(
        self, conn: Connection, source_publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_source_authorship_count(self, conn: Connection, source_publication_id: int) -> int:
        """Compte les `source_authorships` d'un `source_publication`."""
        ...

    def fetch_max_source_authorship_count_per_publication(
        self, conn: Connection, publication_id: int
    ) -> int:
        """Pour une publication canonique, retourne le `MAX` du nombre de
        `source_authorships` par source (chaque source rapporte sa propre
        liste ; on retient la plus complète).
        """
        ...

    def fetch_stale_publication_ids(self, conn: Connection) -> list[int]: ...
