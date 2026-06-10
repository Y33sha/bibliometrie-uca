"""Port : lecture des groupes de publications partageant une clé de fusion,
pour la passe de détection des publications distinctes.

Implémenté par
`infrastructure.queries.pipeline.distinct_publications.PgDistinctPublicationsQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class PublicationForDistinct(NamedTuple):
    """Publication réduite aux champs nécessaires à `detect_distinct_case`."""

    id: int
    doc_type: str | None
    title_normalized: str | None


class SharedKeyGroup(NamedTuple):
    """Groupe de publications partageant une même clé de fusion (ex. un DOI).

    `key` sert au logging ; `publications` est la liste des publications du
    groupe (≥ 2), dont on examine chaque paire.
    """

    key: str
    publications: list[PublicationForDistinct]


class DistinctPublicationsQueries(Protocol):
    """Lectures pour la passe `mark_distinct_publications`."""

    def find_publications_sharing_doi(self, conn: Connection) -> list[SharedKeyGroup]: ...
