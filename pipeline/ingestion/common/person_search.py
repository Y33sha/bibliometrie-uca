"""Moissonnage d'une source par l'identifiant des personnes RH, identifiant confirmé ou authentifié : socle commun des tâches `harvest_by_person`.

Chaque source interroge des lots de personnes, page après page, sur la plage d'années de l'extraction. Une requête réunit tous les identifiants des personnes du lot, dans les types que la source accepte (`PERSON_SEARCH_IDENTIFIERS`). Un document que plusieurs lots ramènent est écrit une fois par run. Une erreur sur un lot est journalisée, et le moissonnage passe au suivant.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import Connection, text

from domain.persons.identifiers import PERSON_IDENTIFIER_LABELS, PersonIdentifierType
from domain.sources.registry import PROFILES, SEARCHED_IDENTIFIER_STATUSES, Source
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.runtime.observability.log_format import inflect, quantity
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress

# Identifiants d'une personne ou d'un lot de personnes, par type.
type Identifiers = Mapping[PersonIdentifierType, list[str]]


def searched_persons(
    conn: Connection, id_types: Collection[PersonIdentifierType]
) -> list[Identifiers]:
    """Identifiants des personnes RH dans les types `id_types`, aux statuts `SEARCHED_IDENTIFIER_STATUSES`, par personne. Une personne sans identifiant de ces types est absente."""
    rows = conn.execute(
        text("""
            SELECT pi.person_id, pi.id_type::text AS id_type, pi.id_value
            FROM person_identifiers pi
            WHERE pi.id_type::text = ANY(:id_types)
              AND pi.status::text = ANY(:statuses)
              AND EXISTS (SELECT 1 FROM hr_records r WHERE r.person_id = pi.person_id)
            ORDER BY pi.person_id, pi.id_type, pi.id_value
        """),
        {"id_types": sorted(id_types), "statuses": sorted(SEARCHED_IDENTIFIER_STATUSES)},
    )
    persons: dict[int, dict[PersonIdentifierType, list[str]]] = {}
    for r in rows:
        persons.setdefault(r.person_id, {}).setdefault(PersonIdentifierType(r.id_type), []).append(
            r.id_value
        )
    return list(persons.values())


def merge_identifiers(persons: list[Identifiers]) -> dict[PersonIdentifierType, list[str]]:
    """Identifiants d'un lot de personnes, par type, sans doublon."""
    merged: dict[PersonIdentifierType, list[str]] = {}
    for person in persons:
        for id_type, values in person.items():
            merged.setdefault(id_type, []).extend(
                v for v in values if v not in merged.get(id_type, [])
            )
    return merged


@dataclass(frozen=True)
class PersonSearchConfig:
    """Personnes interrogées."""

    persons: list[Identifiers]


@dataclass(frozen=True)
class PersonSearchPage:
    """Une page de résultats : ses documents, et le jeton de la page suivante (`None` en fin de résultats)."""

    records: list[Mapping[str, JsonValue]]
    next_token: str | None


class PersonSearchHarvester[ClientT](SourceHarvester[PersonSearchConfig, ClientT]):
    """Documents des personnes RH, cherchés par lots de personnes."""

    # Personnes par requête.
    BATCH_SIZE: ClassVar[int] = 10

    @property
    def id_types(self) -> frozenset[PersonIdentifierType]:
        """Types d'identifiant que la source accepte."""
        return PROFILES[Source(self.SOURCE)].person_identifiers

    @abstractmethod
    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,
    ) -> PersonSearchPage:
        """Une page des documents d'un des `identifiers`, parus entre les deux années de `years` : la première quand `next_token` est `None`."""

    @abstractmethod
    def record_key(self, record: Mapping[str, JsonValue]) -> tuple[str, str | None] | None:
        """Identifiant de la ligne de `staging` et DOI normalisé d'un document, ou `None` pour un document sans identifiant."""

    def authors_truncated(self, record: Mapping[str, JsonValue]) -> bool:  # noqa: ARG002
        """Vrai si la source a tronqué la liste d'auteurs du document."""
        return False

    def load_config(self, conn: Connection) -> PersonSearchConfig:
        persons = searched_persons(conn, self.id_types)
        if not persons:
            raise HarvestConfigError("aucune personne RH à identifiant confirmé ou authentifié")
        return PersonSearchConfig(persons=persons)

    def harvest_all(self, window: HarvestWindow, config: PersonSearchConfig) -> PhaseMetrics:
        all_years = self._years(window)
        years = (min(all_years), max(all_years))
        persons = config.persons
        batches = [
            persons[i : i + self.BATCH_SIZE] for i in range(0, len(persons), self.BATCH_SIZE)
        ]
        seen: set[str] = set()

        def harvest_step(progress: Progress) -> PhaseMetrics:
            metrics = PhaseMetrics()
            for i, batch in enumerate(batches):
                remaining = len(persons) - i * self.BATCH_SIZE
                skipped = f"{quantity(remaining, 'personne')} {inflect(remaining, 'sautée')}"
                label = f"lot {i + 1}"
                try:
                    self._extract_batch(merge_identifiers(batch), years, label, seen, metrics)
                except SourceUnavailableError:
                    self._warn_stopped(skipped)
                    break
                except Exception as e:
                    scoped_logger(self.logger, self.SOURCE, label).error(
                        "erreur : %s — passage au suivant", e
                    )
                progress.advance(len(batch))
            return metrics

        labels = ", ".join(
            PERSON_IDENTIFIER_LABELS[t] for t in PersonIdentifierType if t in self.id_types
        )
        return self._harvest_at_once(len(persons), harvest_step, by=labels)

    def _extract_batch(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        label: str,
        seen: set[str],
        metrics: PhaseMetrics,
    ) -> None:
        """Écrit les documents d'un lot, page après page. Un document sans identifiant, ou déjà écrit dans le run, est ignoré."""
        next_token: str | None = None
        while True:
            page = self.fetch_page(identifiers, years, next_token, label)
            for record in page.records:
                key = self.record_key(record)
                if key and key[0] not in seen:
                    source_id, doi = key
                    seen.add(source_id)
                    stage_document(
                        self.conn,
                        metrics,
                        source=self.SOURCE,
                        source_id=source_id,
                        doi=doi,
                        raw_data=record,
                        authors_truncated=self.authors_truncated(record),
                        entry_mode=StagingEntryMode.PERSON_IDENTIFIER,
                    )
            self.conn.commit()
            next_token = page.next_token
            if next_token is None:
                return
