"""Port : lectures/écritures pour les scripts de fusion cross-source.

Implémenté par `infrastructure.queries.pipeline.merge.PgMergeQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class NntDuplicateRow(NamedTuple):
    """Doublon par NNT : groupe de publications partageant un même NNT cross-source."""

    nnt: str
    pub_ids: list[int]
    sources: list[str]


class PmidDuplicateRow(NamedTuple):
    """Doublon par PMID : groupe de publications partageant un même PMID cross-source."""

    pmid: str
    pub_ids: list[int]
    sources: list[str]


class DoiDuplicateRow(NamedTuple):
    """Doublon par DOI : groupe de publications partageant un même `lower(doi)`.

    Le DOI vit sur la colonne `publications.doi` (pas dans `external_ids`), d'où
    l'absence de `sources` (information portée par les `source_publications`)."""

    doi: str
    pub_ids: list[int]


class OaScanrHalRow(NamedTuple):
    """`source_publications` OpenAlex/ScanR avec ≥1 `external_ids.hal_id` (liste)."""

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
    """Opérations SQL pour les scripts de fusion par NNT / PMID / DOI / hal_id."""

    def find_nnt_duplicates(self, conn: Connection) -> list[NntDuplicateRow]: ...

    def find_pmid_duplicates(self, conn: Connection) -> list[PmidDuplicateRow]: ...

    def find_doi_duplicates(self, conn: Connection) -> list[DoiDuplicateRow]: ...

    def fetch_source_publications_with_hal_external_id(
        self, conn: Connection
    ) -> list[OaScanrHalRow]: ...

    def fetch_hal_source_publications(self, conn: Connection) -> list[HalSourceRow]: ...
