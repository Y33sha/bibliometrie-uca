"""Doublures des requêtes d'écriture, communes aux tests des normaliseurs.

Un normalizer verse ses documents dans `source_publications`, écrit leurs signatures, et marque sa ligne de staging traitée — les mêmes gestes quelle que soit la source qu'il lit. Ce qui varie d'une source à l'autre, c'est le format lu, non ce qui est écrit : ces doublures valent donc pour toutes, et chaque module de test n'y ajoute que ce qui lui est propre.
"""

from pipeline.ingestion.common.signature_queries import StoredSourceAuthorship
from pipeline.ingestion.common.source_publications import SourcePublicationUpsert
from pipeline.ingestion.common.staging import StagingRow


def staging_row(
    staging_id: int = 1,
    source_id: str = "src-1",
    doi: str | None = None,
    raw: dict | None = None,
) -> StagingRow:
    """Ligne de staging à traiter, identifiée par `staging_id` chez la source."""
    return StagingRow(id=staging_id, source_id=source_id, doi=doi, raw_data=raw or {})


class FakeSourcePublicationQueries:
    """`SourcePublicationQueries` : retient les documents versés."""

    def __init__(self) -> None:
        self.upserted_documents: list[SourcePublicationUpsert] = []

    def upsert_source_publication(self, conn, row: SourcePublicationUpsert) -> int:
        self.upserted_documents.append(row)
        return 999


class FakeStagingQueries:
    """`StagingQueries` : retient les lignes marquées traitées."""

    def __init__(self) -> None:
        self.marked_done: list[int] = []

    def mark_done(self, conn, staging_id: int) -> None:
        self.marked_done.append(staging_id)


class FakeAuthorshipsBatchQueries:
    """`AuthorshipsBatchQueries` : retient les signatures insérées, et les restitue comme signatures en base.

    `synced_for` retient les documents dont les signatures sont synchronisées. Les adresses ne sont pas retenues : leurs lectures rendent des tables vides.
    """

    def __init__(self) -> None:
        self.synced_for: list[int] = []
        self.upserted_batches: list[list] = []
        self._rows: list[StoredSourceAuthorship] = []

    def fetch_stored_source_authorships(self, conn, source_publication_id: int) -> list:
        return list(self._rows)

    def delete_source_authorships(self, conn, ids) -> None: ...

    def update_source_authorships_batch(self, conn, values) -> None: ...

    def delete_source_authorship_addresses(self, conn, ids) -> None: ...

    def delete_source_authorship_rors(self, conn, ids) -> None: ...

    def delete_source_authorship_hal_structures(self, conn, ids) -> None: ...

    def fetch_authors_hash(self, conn, source_publication_id: int) -> None:
        return None

    def set_authors_hash(self, conn, source_publication_id: int, authors_hash: str) -> None:
        self.synced_for.append(source_publication_id)

    def upsert_source_authorships_batch(self, conn, values) -> None:
        self.upserted_batches.append(list(values))
        for v in values:
            self._rows.append(
                StoredSourceAuthorship(
                    100 + len(self._rows),
                    v["author_position"],
                    v["last_name_normalized"],
                    v["first_name_normalized"],
                    v["person_identifiers"],
                    v["content_hash"],
                )
            )

    def upsert_addresses_batch(self, conn, values) -> None: ...

    def fetch_address_ids_by_raw_text(self, conn, raw_texts) -> dict[str, int]:
        return {}

    def apply_address_countries_batch(self, conn, values) -> None: ...

    def apply_address_suggested_countries_batch(self, conn, values) -> None: ...

    def insert_source_authorship_addresses_batch(self, conn, values) -> None: ...

    def insert_source_authorship_rors_batch(self, conn, values) -> None: ...

    def insert_source_authorship_hal_structures_batch(self, conn, values) -> None: ...
