"""Port : lectures pour la passe de fusion par métadonnées (thèse / proceedings).

Implémenté par `infrastructure.queries.pipeline.metadata_merge.PgMetadataMergeQueries`.

Transpose en fusion pub↔pub les règles `MetadataDeduplicationCase` qui, à
l'époque du matching, rattachaient un `source_publication` entrant à une
publication existante. Les critères (auteur primary thèse, nombre d'auteurs)
réutilisent les mêmes lectures que le matching.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class MetadataMergeCandidatePair(NamedTuple):
    """Paire de publications (id_a < id_b) candidates à la fusion par métadonnées :
    même `title_normalized`, même `pub_year`, même famille de doc_type."""

    id_a: int
    id_b: int
    doc_type_a: str
    doc_type_b: str
    title_normalized: str


class MetadataMergeQueries(Protocol):
    """Lectures pour `merge_pubs_by_metadata`."""

    def find_metadata_merge_candidate_pairs(
        self, conn: Connection
    ) -> list[MetadataMergeCandidatePair]: ...

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_max_source_authorship_count_per_publication(
        self, conn: Connection, publication_id: int
    ) -> int: ...
