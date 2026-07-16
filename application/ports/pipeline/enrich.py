"""Port : lectures pour les scripts d'enrichissement pipeline.

Implémenté par `infrastructure.queries.pipeline.enrich.PgEnrichQueries`. Consommé par la phase `oa_status` (vérification Unpaywall), par les sous-étapes journaux de la phase `publishers_journals` (typage OpenAlex, import du dump DOAJ), et par l'orchestrateur `run_pipeline`, qui y lit la date du dernier import DOAJ.
"""

from datetime import datetime
from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class JournalIssnRow(NamedTuple):
    """Un journal indexable par ISSN à l'import du dump DOAJ : son `id` et ses trois formes d'ISSN (au moins une non-nulle)."""

    id: int
    issn: str | None
    eissn: str | None
    issnl: str | None


class PublicationOaCheck(NamedTuple):
    """Une publication à (re)vérifier sur Unpaywall : son `id`, son `doi`, son statut OA courant, et `has_open_deposit` — vrai si une archive ouverte en détient le fichier (HAL `green`). Ce dépôt interdit à Unpaywall de refermer le statut (garde-fou de la phase oa_status)."""

    id: int
    doi: str
    oa_status: str | None
    has_open_deposit: bool


class EnrichQueries(Protocol):
    """Lectures de deux enrichissements distincts : la file de vérification Unpaywall des publications, et le typage puis l'indexation DOAJ des revues."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int = 30
    ) -> list[PublicationOaCheck]:
        """Publications à (re)vérifier sur Unpaywall : jamais vérifiées, ou portant un statut changeable (hors `STABLE_OA_STATUSES`) vérifié il y a plus de `staleness_days` jours. Triées jamais-vérifiées d'abord, puis les plus périmées ; `limit` cape le run, le reliquat s'écoulant sur les suivants."""
        ...

    def count_stale_publications(self, conn: Connection, *, staleness_days: int = 30) -> int:
        """Nombre de publications avec DOI à (re)vérifier (même prédicat que `fetch_publications_with_doi`, sans cap) — le backlog de staleness OA, avant plafonnement du run."""
        ...

    def count_publications_by_oa_status(self, conn: Connection) -> dict[str, int]:
        """Répartition des publications par statut OA (`oa_status` → nombre)."""
        ...

    def fetch_journals_of_unknown_type(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des revues au `journal_type` indéterminé qui portent un `openalex_id`, à typer via OpenAlex. Le type étant stable par revue, une revue typée sort de la file. `limit` cape le run."""
        ...

    def fetch_journal_issn_index(self, conn: Connection) -> list[JournalIssnRow]:
        """`JournalIssnRow` de tous les journaux ayant au moins un ISSN — pour indexer ISSN → journal_id à l'import du dump DOAJ."""
        ...

    def reset_is_in_doaj(self, conn: Connection) -> int:
        """`UPDATE journals SET is_in_doaj = FALSE WHERE is_in_doaj` (le dump DOAJ fait autorité, on re-pose les TRUE ensuite). Retourne le rowcount."""
        ...

    def doaj_last_import_at(self, conn: Connection) -> datetime | None:
        """`max(journals.doaj_imported_at)` — date du dernier import DOAJ, pour la staleness (None si jamais importé)."""
        ...
