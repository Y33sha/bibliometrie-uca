"""Port : SQL de la phase publications (`create_publications`).

Implémenté par `infrastructure.queries.pipeline.publications_create.PgPublicationsCreateQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class SourcePublicationRow(NamedTuple):
    """Projection SQL pour la phase de création des publications.

    Colonnes de `source_publications` consommées par `process_document` pour
    créer la publication canonique.
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


class PublicationsCreateQueries(Protocol):
    """Opérations SQL pour la création des publications canoniques à partir des `source_publications`, et les lectures de critères des passes de fusion."""

    def fetch_orphan_source_publications(self, conn: Connection) -> list[SourcePublicationRow]:
        """Tous les orphelins (`publication_id IS NULL`).

        Chacun donne une publication canonique (modèle création⇒fusion) ;
        le dédoublonnage est délégué aux passes de fusion.
        """

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None: ...

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_max_source_authorship_count_per_publication(
        self, conn: Connection, publication_id: int
    ) -> int:
        """Pour une publication canonique, retourne le `MAX` du nombre de
        `source_authorships` par source (chaque source rapporte sa propre
        liste ; on retient la plus complète).
        """
        ...

    def fetch_stale_publication_ids(self, conn: Connection) -> list[int]: ...
