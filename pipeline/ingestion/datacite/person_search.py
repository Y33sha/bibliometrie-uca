"""Interrogation de DataCite par ORCID : nœud `extract_by_person.datacite`.

Interroge `GET /dois` sur les ORCID des créateurs (`creators.nameIdentifiers.nameIdentifier`), par lots, sur la plage d'années de l'extraction. Les ORCID sont ceux des personnes RH, confirmés ou authentifiés. Un document que plusieurs lots ramènent est écrit une fois par run.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.persons.identifiers import PersonIdentifierType, orcid_uri
from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    SourceExtractor,
    scoped_logger,
    stage_document,
)
from pipeline.ingestion.common.person_search import searched_identifiers
from pipeline.ingestion.datacite.fields import record_doi
from pipeline.ingestion.datacite.harvest import DataciteClient
from pipeline.ingestion.http.circuit_breaker import SourceUnavailableError
from pipeline.runtime.config import get_years
from pipeline.runtime.observability.libelles import forme
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression

# ORCID par requête.
BATCH_SIZE = 10
# Documents par page.
_PAGE_SIZE = 200


@dataclass(frozen=True)
class DatacitePersonConfig:
    """ORCID interrogés."""

    orcids: list[str]


def build_orcid_query(orcids: list[str], first_year: int, last_year: int) -> str:
    """Requête `query` DataCite : DOI publiés de `first_year` à `last_year` dont un créateur a l'un des ORCID."""
    clauses = " OR ".join(f'"{orcid_uri(orcid)}"' for orcid in orcids)
    return (
        f"publicationYear:[{first_year} TO {last_year}] "
        f"AND creators.nameIdentifiers.nameIdentifier:({clauses})"
    )


def _skipped(remaining: int) -> str:
    return f"{forme(remaining, 'lot')} {forme(remaining, 'sauté')}"


class DatacitePersonExtractor(SourceExtractor[DatacitePersonConfig, DataciteClient]):
    """DOI DataCite des personnes RH, cherchés par ORCID. Une erreur sur un lot est journalisée, et l'extraction passe au suivant."""

    SOURCE = "datacite"

    def load_config(self, conn: Connection) -> DatacitePersonConfig:
        orcids = searched_identifiers(conn, PersonIdentifierType.ORCID)
        if not orcids:
            raise ExtractionConfigError("aucun ORCID de personne RH confirmé ou authentifié")
        return DatacitePersonConfig(orcids=orcids)

    def extract_all(self, args: argparse.Namespace, config: DatacitePersonConfig) -> PhaseMetrics:
        years = [args.year] if args.year else get_years(self.conn, start_year=args.start_year)
        batches = [
            config.orcids[i : i + BATCH_SIZE] for i in range(0, len(config.orcids), BATCH_SIZE)
        ]
        seen: set[str] = set()

        def extrait(avancement: Progression) -> PhaseMetrics:
            metrics = PhaseMetrics()
            for i, batch in enumerate(batches):
                if self._stop_on_tripped(_skipped(len(batches) - i)):
                    break
                label = f"lot {i + 1}"
                try:
                    self._extract_batch(
                        build_orcid_query(batch, min(years), max(years)), label, seen, metrics
                    )
                except SourceUnavailableError:
                    self._warn_stopped(_skipped(len(batches) - i))
                    break
                except Exception as e:
                    scoped_logger(self.logger, self.SOURCE, label).error(
                        "erreur : %s — passage au suivant", e
                    )
                avancement.avance(1)
            return metrics

        return self._extrait_d_un_tenant(len(batches), extrait)

    def _extract_batch(self, query: str, label: str, seen: set[str], metrics: PhaseMetrics) -> None:
        """Écrit les documents d'un lot d'ORCID, page après page. Un document sans DOI, ou déjà écrit dans le run, est ignoré."""
        next_url: str | None = None
        while True:
            page = self._client.fetch_page(query, next_url, label, page_size=_PAGE_SIZE)
            for record in page.records:
                doi = record_doi(record)
                if doi and doi not in seen:
                    seen.add(doi)
                    stage_document(
                        self.conn,
                        metrics,
                        source=self.SOURCE,
                        source_id=doi,
                        doi=doi,
                        raw_data=record,
                        entry_mode=StagingEntryMode.PERSON_IDENTIFIER,
                    )
            self.conn.commit()
            next_url = page.next_url
            if next_url is None or self._breaker_tripped():
                return
