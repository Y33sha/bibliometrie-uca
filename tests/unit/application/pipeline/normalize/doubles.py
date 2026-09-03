"""Doublures des ports d'écriture, communes aux tests des normalizers.

Un normalizer verse ses documents dans `source_publications`, écrit leurs signatures, et marque sa ligne de staging traitée — les mêmes gestes quelle que soit la source qu'il lit. Ce qui varie d'une source à l'autre, c'est le format lu, non ce qui est écrit : ces doublures valent donc pour toutes, et chaque module de test n'y ajoute que ce qui lui est propre.
"""

from application.ports.pipeline.normalize.source_publications import SourcePublicationRow
from application.ports.pipeline.normalize.staging import StagingRow


def staging_row(
    staging_id: int = 1,
    source_id: str = "src-1",
    doi: str | None = None,
    raw: dict | None = None,
) -> StagingRow:
    """Ligne de staging à traiter, identifiée par `staging_id` chez la source."""
    return StagingRow(id=staging_id, source_id=source_id, doi=doi, raw_data=raw or {})


class FakeSourcePublicationQueries:
    """Port `SourcePublicationQueries` : retient les documents versés."""

    def __init__(self) -> None:
        self.upserted_documents: list[SourcePublicationRow] = []

    def upsert_source_publication(self, conn, row: SourcePublicationRow) -> int:
        self.upserted_documents.append(row)
        return 999


class FakeStagingQueries:
    """Port `StagingQueries` : retient les lignes marquées traitées."""

    def __init__(self) -> None:
        self.marked_done: list[int] = []

    def mark_done(self, conn, staging_id: int) -> None:
        self.marked_done.append(staging_id)


class FakeAuthorshipsBatchQueries:
    """Port `AuthorshipsBatchQueries` : retient les documents dont les signatures sont réécrites.

    Le writer partagé efface les signatures du document avant de les réécrire, puis relit les identifiants posés pour y rattacher les adresses. Rien n'étant écrit ici, ces relectures rendent des tables vides.
    """

    def __init__(self) -> None:
        self.cleared_for: list[int] = []
        self.upserted_batches: list[list] = []

    def clear_source_authorships_for_publication(self, conn, source_publication_id: int) -> None:
        self.cleared_for.append(source_publication_id)

    def upsert_source_authorships_batch(self, conn, values) -> None:
        self.upserted_batches.append(list(values))

    def fetch_source_authorship_ids_by_position(self, conn, **kw) -> dict[int, int]:
        return {}

    def upsert_addresses_batch(self, conn, values) -> None: ...

    def fetch_address_ids_by_raw_text(self, conn, raw_texts) -> dict[str, int]:
        return {}

    def apply_address_countries_batch(self, conn, values) -> None: ...

    def apply_address_suggested_countries_batch(self, conn, values) -> None: ...

    def insert_source_authorship_addresses_batch(self, conn, values) -> None: ...
