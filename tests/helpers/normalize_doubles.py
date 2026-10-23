"""Doublures des requêtes d'écriture, communes aux tests des normaliseurs.

Un normalizer verse ses documents dans `source_records`, écrit leurs contributions sources, et marque sa ligne de staging traitée — les mêmes gestes quelle que soit la source qu'il lit. Ce qui varie d'une source à l'autre, c'est le format lu, non ce qui est écrit : ces doublures valent donc pour toutes, et chaque module de test n'y ajoute que ce qui lui est propre.
"""

from pipeline.ingestion.common.source_contribution_store import StoredSourceContributionRow
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.common.staging import StagingRow


def staging_row(
    staging_id: int = 1,
    source_id: str = "src-1",
    doi: str | None = None,
    raw: dict | None = None,
) -> StagingRow:
    """Ligne de staging à traiter, identifiée par `staging_id` chez la source."""
    return StagingRow(id=staging_id, source_id=source_id, doi=doi, raw_data=raw or {})


class FakeSourceRecordStore:
    """`SourceRecordStore` : retient les documents versés."""

    def __init__(self) -> None:
        self.upserted_documents: list[SourceRecordUpsert] = []

    def upsert_source_record(self, row: SourceRecordUpsert) -> int:
        self.upserted_documents.append(row)
        return 999


class FakeStagingStore:
    """`StagingStore` : retient les lignes marquées traitées."""

    def __init__(self) -> None:
        self.marked_done: list[int] = []

    def mark_done(self, staging_id: int) -> None:
        self.marked_done.append(staging_id)


class FakeSourceContributionStore:
    """`SourceContributionStore` : retient les contributions sources insérées, et les restitue comme contributions sources en base.

    `synced_for` retient les documents dont les contributions sources sont synchronisées. Les adresses ne sont pas retenues : leurs lectures rendent des tables vides.
    """

    def __init__(self) -> None:
        self.synced_for: list[int] = []
        self.upserted_batches: list[list] = []
        self._rows: list[StoredSourceContributionRow] = []

    def fetch_stored_source_contributions(self, source_record_id: int) -> list:
        return list(self._rows)

    def delete_source_contributions(self, ids) -> None: ...

    def update_source_contributions_batch(self, values) -> None: ...

    def delete_source_contribution_addresses(self, ids) -> None: ...

    def delete_source_contribution_rors(self, ids) -> None: ...

    def delete_source_contribution_hal_structures(self, ids) -> None: ...

    def fetch_authors_hash(self, source_record_id: int) -> None:
        return None

    def set_authors_hash(self, source_record_id: int, authors_hash: str) -> None:
        self.synced_for.append(source_record_id)

    def upsert_source_contributions_batch(self, values) -> None:
        self.upserted_batches.append(list(values))
        for v in values:
            self._rows.append(
                StoredSourceContributionRow(
                    100 + len(self._rows),
                    v["author_position"],
                    v["last_name_normalized"],
                    v["first_name_normalized"],
                    v["identifiers"],
                    v["content_hash"],
                    v["collective"],
                    v["roles"],
                )
            )

    def mark_publication_for_grouping(self, source_record_id: int) -> None: ...

    def set_author_counts(
        self, source_record_id: int, author_count: int, distinct: int
    ) -> None: ...

    def upsert_addresses_batch(self, values) -> None: ...

    def fetch_address_ids_by_normalized_text(self, normalized_texts) -> dict[str, int]:
        return {}

    def insert_address_country_candidates(self, method, rows) -> None: ...

    def insert_source_contribution_addresses_batch(self, values) -> None: ...

    def insert_source_contribution_rors_batch(self, values) -> None: ...

    def insert_source_contribution_hal_structures_batch(self, values) -> None: ...
