"""Moissonnage d'une source par l'identifiant des personnes RH, identifiant confirmé ou authentifié : socle commun des nœuds `extract_by_person`.

Chaque source interroge des lots d'identifiants, page après page, sur la plage d'années de l'extraction. Un document que plusieurs lots ramènent est écrit une fois par run. Une erreur sur un lot est journalisée, et le moissonnage passe au suivant.
"""

from __future__ import annotations

import argparse
from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import Connection, text

from domain.persons.identifiers import PersonIdentifierType
from domain.sources.person_search import SEARCHED_IDENTIFIER_STATUSES
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    SourceExtractor,
    scoped_logger,
    stage_document,
)
from pipeline.ingestion.http.circuit_breaker import SourceUnavailableError
from pipeline.runtime.config import get_years
from pipeline.runtime.observability.libelles import forme
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression


def searched_identifiers(conn: Connection, id_type: PersonIdentifierType) -> list[str]:
    """Valeurs distinctes des identifiants `id_type` des personnes RH, aux statuts `SEARCHED_IDENTIFIER_STATUSES`, triées."""
    rows = conn.execute(
        text("""
            SELECT DISTINCT pi.id_value
            FROM person_identifiers pi
            WHERE pi.id_type = :id_type
              AND pi.status::text = ANY(:statuses)
              AND EXISTS (SELECT 1 FROM persons_rh r WHERE r.person_id = pi.person_id)
            ORDER BY 1
        """),
        {"id_type": id_type.value, "statuses": sorted(SEARCHED_IDENTIFIER_STATUSES)},
    )
    return [r.id_value for r in rows]


@dataclass(frozen=True)
class PersonSearchConfig:
    """Identifiants interrogés."""

    identifiers: list[str]


@dataclass(frozen=True)
class PersonSearchPage:
    """Une page de résultats : ses documents, et le jeton de la page suivante (`None` en fin de résultats)."""

    records: list[Mapping[str, JsonValue]]
    next_token: str | None


class PersonSearchExtractor[ClientT](SourceExtractor[PersonSearchConfig, ClientT]):
    """Documents des personnes RH, cherchés par lots d'identifiants `ID_TYPE`."""

    ID_TYPE: ClassVar[PersonIdentifierType] = PersonIdentifierType.ORCID
    # Identifiants par requête.
    BATCH_SIZE: ClassVar[int] = 10

    @abstractmethod
    def fetch_page(
        self,
        identifiers: list[str],
        years: tuple[int, int],
        next_token: str | None,
        label: str,
    ) -> PersonSearchPage:
        """Une page des documents des `identifiers` parus entre les deux années de `years` : la première quand `next_token` est `None`."""

    @abstractmethod
    def record_doi(self, record: Mapping[str, JsonValue]) -> str | None:
        """DOI normalisé d'un document, identifiant de la ligne de `staging`."""

    def load_config(self, conn: Connection) -> PersonSearchConfig:
        identifiers = searched_identifiers(conn, self.ID_TYPE)
        if not identifiers:
            raise ExtractionConfigError(
                f"aucun identifiant {self.ID_TYPE} de personne RH confirmé ou authentifié"
            )
        return PersonSearchConfig(identifiers=identifiers)

    def extract_all(self, args: argparse.Namespace, config: PersonSearchConfig) -> PhaseMetrics:
        all_years = [args.year] if args.year else get_years(self.conn, start_year=args.start_year)
        years = (min(all_years), max(all_years))
        identifiers = config.identifiers
        batches = [
            identifiers[i : i + self.BATCH_SIZE]
            for i in range(0, len(identifiers), self.BATCH_SIZE)
        ]
        seen: set[str] = set()

        def extrait(avancement: Progression) -> PhaseMetrics:
            metrics = PhaseMetrics()
            for i, batch in enumerate(batches):
                skipped = self._skipped(len(identifiers) - i * self.BATCH_SIZE)
                if self._stop_on_tripped(skipped):
                    break
                label = f"lot {i + 1}"
                try:
                    self._extract_batch(batch, years, label, seen, metrics)
                except SourceUnavailableError:
                    self._warn_stopped(skipped)
                    break
                except Exception as e:
                    scoped_logger(self.logger, self.SOURCE, label).error(
                        "erreur : %s — passage au suivant", e
                    )
                avancement.avance(len(batch))
            return metrics

        return self._extrait_d_un_tenant(len(identifiers), extrait)

    def _skipped(self, remaining: int) -> str:
        return f"{remaining} {self.ID_TYPE.upper()} {forme(remaining, 'sauté')}"

    def _extract_batch(
        self,
        batch: list[str],
        years: tuple[int, int],
        label: str,
        seen: set[str],
        metrics: PhaseMetrics,
    ) -> None:
        """Écrit les documents d'un lot, page après page. Un document sans DOI, ou déjà écrit dans le run, est ignoré."""
        next_token: str | None = None
        while True:
            page = self.fetch_page(batch, years, next_token, label)
            for record in page.records:
                doi = self.record_doi(record)
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
            next_token = page.next_token
            if next_token is None or self._breaker_tripped():
                return
