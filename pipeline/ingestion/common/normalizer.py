"""Normalisation d'une source, du staging vers `source_publications`, `source_authorships` et `addresses`.

Chaque source hérite de `SourceNormalizer` (`pipeline/ingestion/<source>/normalize.py`). Le patron fait la boucle : chargement des lignes à traiter, un SAVEPOINT par notice (une erreur isolée ne perd pas le lot en cours), commit périodique, progression et bilan. Les requêtes sur `staging`, `source_publications` et les signatures sont injectées à la construction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import ClassVar, NamedTuple

from sqlalchemy import Connection

from domain.publications.metadata import has_minimal_publication_metadata
from infrastructure.db.savepoint import rollback_unless_invalidated, savepoint
from pipeline.ingestion.common.signature_queries import AuthorshipsBatchQueries
from pipeline.ingestion.common.source_publications import SourcePublicationQueries
from pipeline.ingestion.common.staging import StagingQueries, StagingRow
from pipeline.runtime.observability.libelles import (
    SUITE_DE_BRANCHE,
    accord,
    branche_de_source,
)
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.progression import progression
from pipeline.transformation.publishing.containers import ContainerGatewayQueries
from pipeline.transformation.publishing.publishers.store import PublisherStore


class NormalizeStats(NamedTuple):
    """Bilan d'une normalisation de source : works normalisés, ignorés (rien à écrire / non pertinents), en erreur."""

    processed: int
    skipped: int
    errors: int


class SourceNormalizer(ABC):
    """Template method pour la normalisation source → tables structurées.

    Points d'override :
    - `SOURCE` : identifiant source (obligatoire, ex: "hal", "openalex")
    - `DEFAULT_BATCH_SIZE` : taille de commit (défaut 500)
    - `FETCH_SUB_BATCH` : taille des sous-lots de fetch staging (défaut 50)
    - `minimal_metadata(row)` : abstrait, titre et année de la notice
    - `normalize_record(conn, row) -> bool | None` : abstrait, logique métier d'une notice complète
    - `preload_caches(conn)` : pré-chargement optionnel
    - `cleanup()` : libération des caches après commit final
    """

    SOURCE: ClassVar[str] = ""
    DEFAULT_BATCH_SIZE: ClassVar[int] = 500
    # Taille des sous-lots de fetch staging : charger tous les staging d'un coup fait exploser la RAM côté Python (JSONB désérialisés, overhead ~3-5× la taille brute).
    FETCH_SUB_BATCH: ClassVar[int] = 50

    def __init__(
        self, conn: Connection, logger: logging.Logger, staging_queries: StagingQueries
    ) -> None:
        self.conn = conn
        self.logger = logger
        self._staging = staging_queries

    # ── Hooks métier ────────────────────────────────────────────

    @abstractmethod
    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        """Titre et année de la notice, lus dans son payload."""

    @abstractmethod
    def normalize_record(self, conn: Connection, row: StagingRow) -> bool | None:
        """Normalise une notice qui porte les métadonnées minimales et marque sa ligne traitée. Retourne True (ok), None (skip) ou False (notice refusée, sans rien écrire)."""

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        """Traite une ligne staging. Retourne True (ok), None (skip), False (notice refusée).

        Une notice vide est sautée. Une notice sans titre ou sans année, ou refusée par la source (`normalize_record` rend False), ne fonde aucune publication (`_reject`).
        """
        if not row.raw_data:
            self._staging.mark_done(conn, row.id)
            return None
        title, pub_year = self.minimal_metadata(row)
        if not has_minimal_publication_metadata(title, pub_year):
            return self._reject(conn, row)
        result = self.normalize_record(conn, row)
        if result is False:
            return self._reject(conn, row)
        return result

    def _reject(self, conn: Connection, row: StagingRow) -> bool:
        """Écarte une notice refusée : l'enregistrement qu'elle avait produit est supprimé, sa ligne marquée traitée. Rend False, compté comme notice incomplète."""
        self._staging.discard_source_publication(conn, row.id)
        self._staging.mark_done(conn, row.id)
        return False

    def preload_caches(self, conn: Connection) -> None:  # noqa: B027 (hook optionnel)
        """Pré-chargement optionnel, avant la boucle sur les notices."""

    def cleanup(self) -> None:  # noqa: B027 (hook optionnel)
        """Libération des caches in-memory."""

    # ── Template method ────────────────────────────────────────

    def _count_pending(self, conn: Connection) -> int:
        return self._staging.count_pending_staging(conn, self.SOURCE)

    def _iter_rows(self, conn: Connection) -> Iterator[StagingRow]:
        """Itère toutes les lignes à traiter par sous-lots de `FETCH_SUB_BATCH`."""
        work_ids = self._staging.fetch_pending_staging_ids(conn, self.SOURCE)
        for start in range(0, len(work_ids), self.FETCH_SUB_BATCH):
            batch_ids = work_ids[start : start + self.FETCH_SUB_BATCH]
            yield from self._staging.fetch_staging_by_ids(conn, batch_ids)

    def _process_one(self, conn: Connection, row: StagingRow) -> bool | None:
        """Enveloppe process_work dans un SAVEPOINT : un work en erreur est annulé sans abandonner le batch en cours."""
        with savepoint(conn, on_rollback_failure=self.conn.rollback):
            return self.process_work(conn, row)

    def _recapitule_incomplets(self, identifiants: list[str]) -> None:
        """Récapitule sous la barre de la source les documents qu'elle a laissés de côté.

        Le trait vertical se prolonge d'une ligne à l'autre : le récapitulatif appartient à la branche de sa source, et la liste des sources reste d'un seul tenant. Le logger nu porte ces lignes, celui de la source les préfixerait de son nom et romprait l'alignement.
        """
        if not identifiants:
            return
        self.logger.info(
            "%s%s aux métadonnées incomplètes",
            SUITE_DE_BRANCHE,
            accord(len(identifiants), "document"),
        )
        for identifiant in identifiants:
            self.logger.info("%s%s", SUITE_DE_BRANCHE, identifiant)

    def run(self) -> NormalizeStats:
        """Entry point : pilote la boucle de normalisation."""
        self.conn.rollback()

        # Préfixe `[source]` sur les lignes de la boucle (progression, bilan) : dans un run multi-sources, chaque batch reste rattaché à sa source sans remonter au bandeau.
        slog = scoped_logger(self.logger, self.SOURCE)

        try:
            total = self._count_pending(self.conn)
            if total == 0:
                return NormalizeStats(0, 0, 0)

            self.preload_caches(self.conn)

            processed = 0
            skipped = 0
            errors = 0
            # Documents que `process_work` laisse de côté faute de métadonnées exploitables :
            # récapitulés sous la barre plutôt qu'écrits un par un au fil de la boucle.
            incomplets: list[str] = []

            with progression(total, branche_de_source(self.SOURCE), slog) as avancement:
                for row in self._iter_rows(self.conn):
                    avancement.avance()
                    try:
                        result = self._process_one(self.conn, row)
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
                        incomplets.append(row.source_id)

                    done = processed + skipped
                    if done > 0 and done % self.DEFAULT_BATCH_SIZE == 0:
                        self.conn.commit()

            self.conn.commit()
            self.cleanup()

            self._recapitule_incomplets(incomplets)
            return NormalizeStats(processed, skipped, errors)

        except KeyboardInterrupt:
            # Ctrl+C frappe souvent en plein `conn.execute()` : la transaction est alors avortée et `commit()` lèverait `PendingRollbackError`.
            # On rollback (le batch en cours, incomplet, est jeté ; les batches committés tous les `batch_size` sont durables) puis on re-raise pour laisser `run_pipeline.main()` faire l'arrêt propre (rapport partiel + exit 130).
            # Sans le `raise`, la phase « réussirait » et le pipeline enchaînerait sur la source suivante.
            rollback_unless_invalidated(self.conn)
            slog.warning("Interruption — batches déjà committés conservés.")
            raise
        except Exception as e:
            rollback_unless_invalidated(self.conn)
            slog.error(f"Erreur fatale : {e}")
            raise


class BibliographicNormalizer(SourceNormalizer):
    """Normaliseur d'une source bibliographique : `SourceNormalizer` doté des repositories conteneur (revue et monographie) / éditeur."""

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: SourcePublicationQueries,
        container_repo: ContainerGatewayQueries,
        publisher_store: PublisherStore,
        authorship_queries: AuthorshipsBatchQueries,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._container_repo = container_repo
        self._publisher_repo = publisher_store
        self._authorship_queries = authorship_queries
