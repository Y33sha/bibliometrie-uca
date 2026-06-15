"""Port : lectures pour les scripts d'enrichissement pipeline.

Implémenté par `infrastructure.queries.pipeline.enrich.PgEnrichQueries`. Consommé
par les phases `oa_status` (Unpaywall) et `publishers_journals`
(sub-step `enrich_journals_from_openalex`).
"""

from datetime import datetime
from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class JournalIssnRow(NamedTuple):
    """Un journal indexable par ISSN à l'import du dump DOAJ : son `id` et ses
    trois formes d'ISSN (au moins une non-nulle)."""

    id: int
    issn: str | None
    eissn: str | None
    issnl: str | None


class EnrichQueries(Protocol):
    """Opérations SQL pour les scripts d'enrichissement pipeline."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int = 30
    ) -> list[tuple[int, str, str | None]]: ...

    def fetch_journals_of_unknown_type(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]: ...

    def fetch_publishers_needing_enrichment(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]: ...

    def fetch_publishers_needing_publisher_type_from_ror(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]: ...

    def fetch_publishers_needing_country_from_crossref(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, int]]: ...

    def fetch_journal_issn_index(self, conn: Connection) -> list[JournalIssnRow]:
        """`JournalIssnRow` de tous les journaux ayant au moins un ISSN — pour
        indexer ISSN → journal_id à l'import du dump DOAJ."""
        ...

    def reset_is_in_doaj(self, conn: Connection) -> int:
        """`UPDATE journals SET is_in_doaj = FALSE WHERE is_in_doaj` (le dump DOAJ
        fait autorité, on re-pose les TRUE ensuite). Retourne le rowcount."""
        ...

    def doaj_last_import_at(self, conn: Connection) -> datetime | None:
        """`max(journals.doaj_imported_at)` — date du dernier import DOAJ, pour la
        staleness (None si jamais importé)."""
        ...
