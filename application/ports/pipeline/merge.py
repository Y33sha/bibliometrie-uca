"""Port : lectures/écritures pour les scripts de fusion cross-source.

Implémenté par `infrastructure.queries.merge.PgMergeQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class NntDuplicateRow(NamedTuple):
    """Doublon par NNT : groupe de publications partageant un même NNT cross-source."""

    nnt: str
    pub_ids: list[int]
    sources: list[str]


class OaScanrHalRow(NamedTuple):
    """`source_publications` OpenAlex/ScanR avec un `external_ids.hal_id` non null."""

    src_doc_id: int
    source: str
    src_id: str
    src_pub_id: int | None
    hal_id: str


class HalSourceRow(NamedTuple):
    """`source_publications` HAL : identifiant HAL + publication associée."""

    hal_doc_id: int
    halid: str
    hal_pub_id: int | None


class MergeQueries(Protocol):
    """Opérations SQL pour les scripts de fusion par NNT / hal_id."""

    def find_nnt_duplicates(self, conn: Connection) -> list[NntDuplicateRow]: ...

    def fetch_source_publications_with_hal_external_id(
        self, conn: Connection
    ) -> list[OaScanrHalRow]: ...

    def fetch_hal_source_publications(self, conn: Connection) -> list[HalSourceRow]: ...

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None: ...
