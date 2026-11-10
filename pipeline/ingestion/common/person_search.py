"""Moissonnage d'une source par l'identifiant des personnes RH, identifiant confirmé ou authentifié : socle commun des tâches `harvest_by_person`.

Chaque source est interrogée par lots de personnes, page après page, sur la plage d'années du moissonnage. Les lots réunissent les personnes qui copublient (`person_batches`). Une requête réunit tous les identifiants des personnes du lot, dans les types acceptés par la source (`PERSON_SEARCH_IDENTIFIERS`). Les lots partent en parallèle, dans la limite de requêtes simultanées de la source (`MAX_CONCURRENT`). Un document ramené par plusieurs lots est écrit une fois par run. Une erreur sur un lot est journalisée, et le moissonnage passe au suivant.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import Connection, text

from domain.persons.identifiers import (
    HUMAN_ATTRIBUTION_STATUSES,
    PERSON_IDENTIFIER_LABELS,
    PersonIdentifierType,
)
from domain.sources.registry import PROFILES, Source
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.http.circuit_breaker import SourceUnavailableError, trip_source
from pipeline.ingestion.api_params import MAX_CONCURRENT
from pipeline.ingestion.common.concurrent_pages import paginate_concurrently
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_page,
)
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.common.person_batches import compose_batches, read_batching_inputs
from pipeline.ingestion.payload_readers import payload_reader
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress

# Identifiants d'une personne ou d'un lot de personnes, par type.
type Identifiers = Mapping[PersonIdentifierType, list[str]]


def searched_persons(
    conn: Connection, id_types: Collection[PersonIdentifierType]
) -> dict[int, Identifiers]:
    """Renvoie, par identifiant de personne RH, ses identifiants des types `id_types` aux statuts `HUMAN_ATTRIBUTION_STATUSES`. Une personne sans identifiant de ces types est absente."""
    rows = conn.execute(
        text("""
            SELECT pi.person_id, pi.id_type::text AS id_type, pi.id_value
            FROM person_identifiers pi
            WHERE pi.id_type::text = ANY(:id_types)
              AND pi.status::text = ANY(:statuses)
              AND EXISTS (SELECT 1 FROM hr_records r WHERE r.person_id = pi.person_id)
            ORDER BY pi.person_id, pi.id_type, pi.id_value
        """),
        {"id_types": sorted(id_types), "statuses": sorted(HUMAN_ATTRIBUTION_STATUSES)},
    )
    persons: dict[int, dict[PersonIdentifierType, list[str]]] = {}
    for r in rows:
        persons.setdefault(r.person_id, {}).setdefault(PersonIdentifierType(r.id_type), []).append(
            r.id_value
        )
    return dict(persons)


def merge_identifiers(persons: list[Identifiers]) -> dict[PersonIdentifierType, list[str]]:
    """Fusionne les identifiants d'un lot de personnes, par type, sans doublon."""
    merged: dict[PersonIdentifierType, list[str]] = {}
    for person in persons:
        for id_type, values in person.items():
            merged.setdefault(id_type, []).extend(
                v for v in values if v not in merged.get(id_type, [])
            )
    return merged


class PersonSearchHarvester[ClientT](SourceHarvester[ClientT]):
    """Documents des personnes RH, cherchés par lots de personnes."""

    BATCH_SIZE: ClassVar[int] = 10
    """Personnes par requête."""

    @property
    def id_types(self) -> frozenset[PersonIdentifierType]:
        """Types d'identifiant acceptés par la source."""
        return PROFILES[Source(self.SOURCE)].person_identifiers

    @abstractmethod
    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,
    ) -> Page:
        """Renvoie une page des documents d'un des `identifiers`, parus entre les deux années de `years`. Renvoie la première page quand `next_token` est `None`."""

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        persons = searched_persons(self.conn, self.id_types)
        if not persons:
            raise HarvestConfigError("aucune personne RH à identifiant confirmé ou authentifié")
        all_years = self._years(window)
        years = (min(all_years), max(all_years))
        publications, units = read_batching_inputs(self.conn, persons, years)
        batches = [
            _Batch(f"lot {i + 1}", len(batch), merge_identifiers([persons[p] for p in batch]))
            for i, batch in enumerate(
                compose_batches(persons, publications, units, self.BATCH_SIZE)
            )
        ]
        reader = payload_reader(Source(self.SOURCE))
        seen: set[str] = set()

        def keep(record: Mapping[str, JsonValue]) -> bool:
            """Écarte un document sans identifiant, ou déjà écrit dans le run."""
            identity = reader.identify(record)
            if identity is None or identity.source_id in seen:
                return False
            seen.add(identity.source_id)
            return True

        def harvest_step(progress: Progress) -> PhaseMetrics:
            metrics = PhaseMetrics()

            def on_page(batch: _Batch, page: Page) -> None:
                try:
                    stage_page(
                        self.conn,
                        metrics,
                        self.SOURCE,
                        page,
                        keep=keep,
                        entry_mode=StagingEntryMode.PERSON_IDENTIFIER,
                    )
                except Exception as e:
                    self.conn.rollback()
                    scoped_logger(self.logger, self.SOURCE, batch.label).error(
                        "erreur d'écriture : %s — page sautée", e
                    )

            def on_end(batch: _Batch, error: Exception | None) -> None:
                if error is not None and not isinstance(error, SourceUnavailableError):
                    scoped_logger(self.logger, self.SOURCE, batch.label).error(
                        "erreur : %s — passage au suivant", error
                    )
                progress.advance(batch.persons)

            try:
                paginate_concurrently(
                    batches,
                    lambda batch, token: self.fetch_page(
                        batch.identifiers, years, token, batch.label
                    ),
                    max_concurrent=MAX_CONCURRENT[self.SOURCE],
                    on_page=on_page,
                    on_end=on_end,
                )
            except SourceUnavailableError:
                trip_source()
            return metrics

        labels = ", ".join(
            PERSON_IDENTIFIER_LABELS[t] for t in PersonIdentifierType if t in self.id_types
        )
        return self._harvest_at_once(len(persons), harvest_step, by=labels)


@dataclass(frozen=True, slots=True)
class _Batch:
    """Lot de personnes interrogé en une requête paginée."""

    label: str
    persons: int
    """Nombre de personnes du lot."""
    identifiers: Identifiers
