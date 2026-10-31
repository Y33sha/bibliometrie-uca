"""Normalisation d'une source, du staging vers `source_records`, `source_contributions` et `addresses`.

Chaque source hérite de `SourceNormalizer` (`pipeline/ingestion/<source>/normalize.py`) et fournit l'analyse d'une ligne de `staging`, sans I/O : document lu, éditeur, conteneurs, enregistrement source, bloc auteurs et contributions sources. Le patron fait les écritures et la boucle : chargement des lignes à traiter, un SAVEPOINT par enregistrement source (une erreur isolée garde le lot en cours), commit périodique, progression et bilan. Les stores sont injectés à la construction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import ClassVar, NamedTuple

from sqlalchemy import Connection

from domain.publications.metadata import has_minimal_publication_metadata, is_overlong_title
from domain.serials.containers import ContainerDescription, determine_container_type
from domain.source_records.biblio import with_journal
from domain.types import JsonValue
from infrastructure.db.savepoint import rollback_unless_invalidated, savepoint
from pipeline.ingestion.common.embargoes import Embargo, EmbargoStore
from pipeline.ingestion.common.locations import LocationFacts, LocationStore, identifier_locations
from pipeline.ingestion.common.source_contribution_store import SourceContributionStore
from pipeline.ingestion.common.source_contributions import (
    AuthorBlock,
    AuthorRecord,
    sync_source_contributions,
)
from pipeline.ingestion.common.source_records import SourceRecordStore, SourceRecordUpsert
from pipeline.ingestion.common.staging import StagingRow, StagingStore
from pipeline.runtime.observability.log_format import (
    BRANCH_CONTINUATION,
    quantity,
    source_branch,
)
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.publishing.containers import ContainerStores
from pipeline.transformation.publishing.find_or_create import (
    Containers,
    find_or_create_containers,
    find_or_create_publisher,
)
from pipeline.transformation.publishing.publishers.store import PublisherStore

type Document = Mapping[str, JsonValue]
"""Document décrit par la source, lu dans une ligne de `staging`."""


class PublisherFacts(NamedTuple):
    """Éditeur d'un document, tel que la source le nomme, et son identifiant OpenAlex s'il est connu."""

    name: str
    openalex_id: str | None = None


class NormalizeStats(NamedTuple):
    """Bilan d'une normalisation de source."""

    processed: int
    """Documents normalisés."""
    skipped: int
    """Lignes vides sautées."""
    errors: int
    """Documents en erreur ou refusés."""


class SourceNormalizer(ABC):
    """Normalisation d'une source : la sous-classe analyse une ligne de `staging`, le patron écrit.

    Une sous-classe définit `SOURCE`, `minimal_metadata`, `source_record`, `author_block` et `author_records`. `parse`, `publisher`, `container_facts`, `locations`, `embargo`, `preload_caches` et `cleanup` ont un comportement par défaut.
    """

    SOURCE: ClassVar[str] = ""
    DEFAULT_BATCH_SIZE: ClassVar[int] = 500
    FETCH_SUB_BATCH: ClassVar[int] = 50
    """Lignes de `staging` chargées par sous-lot. En mémoire, un payload JSONB désérialisé occupe 3 à 5 fois sa taille brute."""

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_store: StagingStore,
        record_store: SourceRecordStore,
        container_stores: ContainerStores,
        publisher_store: PublisherStore,
        contribution_store: SourceContributionStore,
        location_store: LocationStore,
        embargo_store: EmbargoStore,
    ) -> None:
        self.conn = conn
        self.logger = logger
        self._staging = staging_store
        self._record_store = record_store
        self._container_stores = container_stores
        self._publisher_store = publisher_store
        self._contribution_store = contribution_store
        self._location_store = location_store
        self._embargo_store = embargo_store

    @abstractmethod
    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        """Renvoie le titre et l'année du document, lus dans son payload."""

    def parse(self, row: StagingRow) -> Document | None:
        """Renvoie le document décrit par la ligne, ou `None` pour un document refusé. N'écrit rien."""
        return row.raw_data

    def publisher(self, doc: Document) -> PublisherFacts | None:  # noqa: ARG002
        """Renvoie l'éditeur du document, ou `None`."""
        return None

    def container_facts(self, doc: Document) -> ContainerDescription | None:  # noqa: ARG002
        """Renvoie la revue, ou la monographie et la collection, contenant le document. `None` : sans conteneur."""
        return None

    def locations(self, doc: Document) -> list[LocationFacts]:  # noqa: ARG002
        """Renvoie les localisations du document."""
        return []

    def embargo(self, doc: Document) -> Embargo | None:  # noqa: ARG002
        """Renvoie l'embargo déclaré par la source, ou `None`."""
        return None

    @abstractmethod
    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        """Construit l'enregistrement source du document, rattaché à ses conteneurs."""

    @abstractmethod
    def author_block(self, doc: Document) -> AuthorBlock:
        """Renvoie la partie du document contenant ses auteurs. Son empreinte décide de la synchronisation des contributions sources."""

    @abstractmethod
    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        """Renvoie les contributions sources lues dans le bloc auteurs."""

    def normalize_record(self, row: StagingRow) -> bool:
        """Normalise un document à métadonnées minimales et marque sa ligne traitée. Renvoie vrai, ou faux sans rien écrire pour un document refusé.

        Écrit dans l'ordre l'éditeur, les conteneurs, l'enregistrement source rattaché à son éditeur, ses localisations, son embargo et ses contributions sources.
        """
        doc = self.parse(row)
        if doc is None:
            return False
        publisher = self.publisher(doc)
        publisher_id = (
            find_or_create_publisher(
                publisher.name, openalex_id=publisher.openalex_id, repo=self._publisher_store
            )
            if publisher
            else None
        )
        facts = self.container_facts(doc)
        series, volume = determine_container_type(facts) if facts is not None else (None, None)
        containers = (
            find_or_create_containers(
                series, volume, publisher_id=publisher_id, stores=self._container_stores
            )
            if series or volume
            else Containers(None, None)
        )
        record = self.source_record(row, doc, containers)
        record = replace(
            record, publisher_id=publisher_id, biblio=with_journal(record.biblio, series)
        )
        source_record_id = self._record_store.upsert_source_record(record)
        self._location_store.replace_locations(
            source_record_id, [*self.locations(doc), *identifier_locations(record.identifiers)]
        )
        self._embargo_store.replace_embargo(source_record_id, self.embargo(doc))
        sync_source_contributions(
            self._contribution_store,
            self.SOURCE,
            source_record_id,
            self.author_block(doc),
            self.author_records,
        )
        self._staging.mark_done(row.id)
        return True

    def process_work(self, row: StagingRow) -> bool | None:
        """Traite une ligne de `staging`. Renvoie vrai pour un document normalisé, `None` pour une ligne vide, sautée, et faux pour un document refusé.

        Un document sans titre, sans année, au titre trop long (`is_overlong_title`) ou refusé par la source ne fonde aucune publication (`_reject`).
        """
        if not row.raw_data:
            self._staging.mark_done(row.id)
            return None
        title, publication_year = self.minimal_metadata(row)
        if not has_minimal_publication_metadata(title, publication_year) or is_overlong_title(
            title
        ):
            return self._reject(row)
        result = self.normalize_record(row)
        if result is False:
            return self._reject(row)
        return result

    def _reject(self, row: StagingRow) -> bool:
        """Écarte un document refusé : son enregistrement source est supprimé, sa ligne marquée traitée. Renvoie faux, compté comme document incomplet."""
        self._staging.discard_source_record(row.id)
        self._staging.mark_done(row.id)
        return False

    def preload_caches(self) -> None:  # noqa: B027 (hook optionnel)
        """Charge les caches de la source, avant la boucle sur les lignes."""

    def cleanup(self) -> None:  # noqa: B027 (hook optionnel)
        """Libère les caches en mémoire, après le dernier commit."""

    def _count_pending(self) -> int:
        return self._staging.count_pending_staging(self.SOURCE)

    def _iter_rows(self) -> Iterator[StagingRow]:
        """Itère toutes les lignes à traiter par sous-lots de `FETCH_SUB_BATCH`."""
        work_ids = self._staging.fetch_pending_staging_ids(self.SOURCE)
        for start in range(0, len(work_ids), self.FETCH_SUB_BATCH):
            batch_ids = work_ids[start : start + self.FETCH_SUB_BATCH]
            yield from self._staging.fetch_staging_by_ids(batch_ids)

    def _process_one(self, row: StagingRow) -> bool | None:
        """Traite une ligne dans un SAVEPOINT : une ligne en erreur est annulée, et le lot en cours continue."""
        with savepoint(self.conn, on_rollback_failure=self.conn.rollback):
            return self.process_work(row)

    def _summarize_incomplete(self, identifiers: list[str]) -> None:
        """Récapitule sous la barre de la source les documents laissés de côté.

        Le trait vertical se prolonge d'une ligne à l'autre : le récapitulatif appartient à la branche de sa source. Ces lignes passent par le journal nu ; le préfixe de la source romprait l'alignement.
        """
        if not identifiers:
            return
        self.logger.info(
            "%s%s aux métadonnées incomplètes ou non conformes",
            BRANCH_CONTINUATION,
            quantity(len(identifiers), "document"),
        )
        for identifier in identifiers:
            self.logger.info("%s%s", BRANCH_CONTINUATION, identifier)

    def run(self) -> NormalizeStats:
        """Normalise les lignes à traiter, avec un commit tous les `DEFAULT_BATCH_SIZE` enregistrements, et renvoie le bilan."""
        self.conn.rollback()

        # Préfixe `[source]` sur les lignes de la boucle (progression, bilan) : dans un run multi-sources, chaque batch reste rattaché à sa source sans remonter au bandeau.
        slog = scoped_logger(self.logger, self.SOURCE)

        try:
            total = self._count_pending()
            if total == 0:
                return NormalizeStats(0, 0, 0)

            self.preload_caches()

            processed = 0
            skipped = 0
            errors = 0
            # Documents laissés de côté par `process_work` faute de métadonnées exploitables : récapitulés sous la barre en fin de boucle.
            incomplete: list[str] = []

            with track_progress(total, source_branch(self.SOURCE), slog) as progress:
                for row in self._iter_rows():
                    progress.advance()
                    try:
                        result = self._process_one(row)
                    except Exception as e:
                        slog.error(f"Erreur sur {row.source_id}: {e}")
                        errors += 1
                        continue

                    if result is True:
                        processed += 1
                    elif result is None:
                        skipped += 1
                    else:
                        errors += 1
                        incomplete.append(row.source_id)

                    done = processed + skipped
                    if done > 0 and done % self.DEFAULT_BATCH_SIZE == 0:
                        self.conn.commit()

            self.conn.commit()
            self.cleanup()

            self._summarize_incomplete(incomplete)
            return NormalizeStats(processed, skipped, errors)

        except KeyboardInterrupt:
            # Ctrl+C interrompt souvent un `conn.execute()` : la transaction est alors avortée, et `commit()` lèverait `PendingRollbackError`.
            # Le rollback jette le lot en cours ; les lots déjà commités restent.
            # L'exception remonte à `run_pipeline.main()`, qui écrit le rapport partiel et sort en 130. Sans elle, le pipeline enchaînerait sur la source suivante.
            rollback_unless_invalidated(self.conn)
            slog.warning("Interruption — batches déjà committés conservés.")
            raise
        except Exception as e:
            rollback_unless_invalidated(self.conn)
            slog.error(f"Erreur fatale : {e}")
            raise
