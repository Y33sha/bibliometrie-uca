"""Normalisation d'une source, du staging vers `source_records`, `source_contributions`, `addresses` et `subjects`.

Chaque source hérite de `SourceNormalizer` (`pipeline/ingestion/<source>/normalize.py`) et fournit l'analyse d'une ligne de `staging`, sans I/O : document lu, éditeur, conteneurs, enregistrement source, sujets, bloc auteurs et contributions sources. Le patron fait les écritures et la boucle : chargement des lignes à traiter, un SAVEPOINT par enregistrement source (une erreur isolée garde le lot en cours), commit périodique, progression et bilan. Les stores sont injectés à la construction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import ClassVar, NamedTuple

from sqlalchemy import Connection

from domain.documents.dates import PublicationDate
from domain.normalize import to_plain_text
from domain.platforms.registry import names_platform
from domain.publications.metadata import has_minimal_publication_metadata, is_overlong_title
from domain.serials.containers import (
    ContainerDescription,
    SeriesDescription,
    VolumeDescription,
    determine_container_type,
)
from domain.source_records.biblio import with_journal, with_monograph, with_publisher
from domain.subjects.subject import SubjectLink
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
from pipeline.ingestion.common.subjects import SourceRecordSubjectStore
from pipeline.runtime.observability.log_format import (
    BRANCH_CONTINUATION,
    quantity,
    source_branch,
)
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.progress import track_progress

type Document = Mapping[str, JsonValue]
"""Document décrit par la source, lu dans une ligne de `staging`."""


@dataclass(frozen=True, slots=True)
class PublisherFacts:
    """Éditeur d'un document, tel que la source le nomme, et son identifiant OpenAlex s'il est connu. La construction met le nom en texte brut (`to_plain_text`)."""

    name: str
    openalex_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", to_plain_text(self.name))


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

    Une sous-classe définit `SOURCE`, `minimal_metadata`, `source_record`, `author_block` et `author_records`. `parse`, `publisher`, `container_facts`, `locations`, `embargo`, `subjects`, `withholds_authors`, `preload_caches` et `cleanup` ont un comportement par défaut.
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
        contribution_store: SourceContributionStore,
        location_store: LocationStore,
        embargo_store: EmbargoStore,
        subject_store: SourceRecordSubjectStore,
    ) -> None:
        self.conn = conn
        self.logger = logger
        self._staging = staging_store
        self._record_store = record_store
        self._contribution_store = contribution_store
        self._location_store = location_store
        self._embargo_store = embargo_store
        self._subject_store = subject_store

    @abstractmethod
    def minimal_metadata(self, doc: Document) -> tuple[str | None, int | None]:
        """Renvoie le titre et l'année du document."""

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

    def subjects(self, doc: Document) -> list[SubjectLink]:  # noqa: ARG002
        """Renvoie les sujets donnés par la source."""
        return []

    def withholds_authors(self, record: SourceRecordUpsert) -> bool:  # noqa: ARG002
        """Vrai si l'enregistrement source s'écrit sans contributions sources."""
        return False

    @abstractmethod
    def publication_date(self, doc: Document) -> PublicationDate | None:
        """Renvoie la date de publication du document, avec sa précision, ou `None` sans année."""

    @abstractmethod
    def source_record(
        self, row: StagingRow, doc: Document, *, has_series: bool
    ) -> SourceRecordUpsert:
        """Construit l'enregistrement source du document.

        Args:
            has_series: le document décrit une série, qui sert au rattachement à sa revue.
        """

    @abstractmethod
    def author_block(self, doc: Document) -> AuthorBlock:
        """Renvoie la partie du document contenant ses auteurs. Son empreinte décide de la synchronisation des contributions sources."""

    @abstractmethod
    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        """Renvoie les contributions sources lues dans le bloc auteurs."""

    def series_and_volume(
        self, row: StagingRow, doc: Document
    ) -> tuple[SeriesDescription | None, VolumeDescription | None]:
        """Renvoie la série et le volume du document (`determine_container_type`). Une série qui désigne une plateforme est retirée (`names_platform`), d'après le DOI de la ligne de `staging`."""
        facts = self.container_facts(doc)
        if facts is None:
            return None, None
        if names_platform(
            (facts.journal_title, facts.collection_title),
            openalex_id=facts.openalex_id,
            doi=row.doi,
        ):
            facts = facts.without_series()
        return determine_container_type(facts)

    def normalize_record(self, row: StagingRow, doc: Document) -> None:
        """Normalise le document `doc`, lu dans la ligne `row`, à métadonnées minimales, et marque sa ligne traitée.

        Écrit dans l'ordre l'enregistrement source, ses localisations, son embargo, ses sujets et ses contributions sources. L'éditeur, la série et le volume décrits par la source s'écrivent dans `biblio` ; l'éditeur, la revue et la monographie se rattachent dans la phase `publishing`. Un enregistrement source retenu par `withholds_authors` perd ses contributions sources.
        """
        publisher = self.publisher(doc)
        series, volume = self.series_and_volume(row, doc)
        record = self.source_record(row, doc, has_series=series is not None)
        biblio = with_publisher(
            record.biblio,
            publisher.name if publisher else None,
            publisher.openalex_id if publisher else None,
        )
        record = replace(
            record,
            publication_date=self.publication_date(doc),
            biblio=with_monograph(with_journal(biblio, series), volume),
        )
        source_record_id = self._record_store.upsert_source_record(record)
        self._location_store.replace_locations(
            source_record_id, [*self.locations(doc), *identifier_locations(record.identifiers)]
        )
        self._embargo_store.replace_embargo(source_record_id, self.embargo(doc))
        self._subject_store.replace_subjects(source_record_id, self.subjects(doc))
        if self.withholds_authors(record):
            self._contribution_store.withhold_source_contributions([source_record_id])
        else:
            sync_source_contributions(
                self._contribution_store,
                self.SOURCE,
                source_record_id,
                self.author_block(doc),
                self.author_records,
            )
        self._staging.clear_payload(row)

    def process_work(self, row: StagingRow) -> bool | None:
        """Traite une ligne de `staging`. Renvoie vrai pour un document normalisé, `None` pour une ligne vide, sautée, et faux pour un document refusé.

        Un document sans titre, sans année, au titre trop long (`is_overlong_title`) ou refusé par la source ne fonde aucune publication (`_reject`).
        """
        if not row.raw_data:
            return None
        doc = self.parse(row)
        if doc is None:
            return self._reject(row)
        title, publication_year = self.minimal_metadata(doc)
        if not has_minimal_publication_metadata(title, publication_year) or is_overlong_title(
            title
        ):
            return self._reject(row)
        self.normalize_record(row, doc)
        return True

    def _reject(self, row: StagingRow) -> bool:
        """Écarte un document refusé : son enregistrement source est supprimé, son payload vidé. Renvoie faux, compté comme document incomplet."""
        self._staging.discard_source_record(row.id)
        self._staging.clear_payload(row)
        return False

    def preload_caches(self) -> None:  # noqa: B027 (hook optionnel)
        """Charge les caches de la source, avant la boucle sur les lignes."""

    def cleanup(self) -> None:  # noqa: B027 (hook optionnel)
        """Libère les caches en mémoire, après le dernier commit."""

    def _iter_rows(self, work_ids: list[int]) -> Iterator[StagingRow]:
        """Itère les lignes `work_ids` par sous-lots de `FETCH_SUB_BATCH`."""
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
        """Normalise les lignes en file, avec un commit tous les `DEFAULT_BATCH_SIZE` enregistrements, et renvoie le bilan.

        Chaque commit retire de la file les lignes traitées depuis le précédent. Une ligne en erreur reste en file pour le run suivant.
        """
        self.conn.rollback()

        # Préfixe `[source]` sur les lignes de la boucle (progression, bilan) : dans un run multi-sources, chaque batch reste rattaché à sa source sans remonter au bandeau.
        slog = scoped_logger(self.logger, self.SOURCE)

        try:
            work_ids = self._staging.snapshot_pending(self.SOURCE)
            if not work_ids:
                return NormalizeStats(0, 0, 0)

            self.preload_caches()

            processed = 0
            skipped = 0
            errors = 0
            # Documents laissés de côté par `process_work` faute de métadonnées exploitables : récapitulés sous la barre en fin de boucle.
            incomplete: list[str] = []
            # Lignes traitées depuis le dernier commit, à retirer de la file avec lui.
            done_ids: list[int] = []

            def commit() -> None:
                self._staging.forget_normalized(done_ids)
                self.conn.commit()
                done_ids.clear()

            with track_progress(len(work_ids), source_branch(self.SOURCE), slog) as progress:
                for row in self._iter_rows(work_ids):
                    progress.advance()
                    try:
                        result = self._process_one(row)
                    except Exception as e:
                        slog.error(f"Erreur sur {row.source_id}: {e}")
                        errors += 1
                        continue

                    done_ids.append(row.id)
                    if result is True:
                        processed += 1
                    elif result is None:
                        skipped += 1
                    else:
                        errors += 1
                        incomplete.append(row.source_id)

                    done = processed + skipped
                    if done > 0 and done % self.DEFAULT_BATCH_SIZE == 0:
                        commit()

            commit()
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
