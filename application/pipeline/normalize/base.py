"""Base class pour les normaliseurs de sources.

Capture le code commun aux normaliseurs :
- commit périodique et rollback sur la connexion injectée (ouverte et fermée par l'appelant)
- comptage + chargement des work_ids à traiter
- boucle : un SAVEPOINT par work (une erreur isolée sans perdre le batch en cours), commit périodique
- logs de progression et bilan

L'accès au staging passe par le port `StagingQueries` (injecté par le composition root `run_pipeline`). Chaque source hérite et implémente `process_work()`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import ClassVar, NamedTuple

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.pipeline.logging_scope import scoped_logger
from application.ports.pipeline.normalize.staging import StagingQueries, StagingRow


class NormalizeStats(NamedTuple):
    """Bilan d'une normalisation de source : works normalisés, ignorés (rien à écrire / non pertinents), en erreur."""

    processed: int
    skipped: int
    errors: int


class SourceNormalizer(ABC):
    """Template method pour la normalisation source → tables structurées.

    Le port `StagingQueries` retourne `list[StagingRow]` pour toutes les sources.

    Points d'override :
    - `SOURCE` : identifiant source (obligatoire, ex: "hal", "openalex")
    - `DEFAULT_BATCH_SIZE` : taille de commit (défaut 500)
    - `FETCH_SUB_BATCH` : taille des sous-lots de fetch staging (défaut 50)
    - `process_work(conn, row) -> bool | None` : abstrait, logique métier
    - `preload_caches(conn)` : pré-chargement optionnel
    - `summary_stats(conn) -> list[str]` : lignes de log additionnelles
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
    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        """Traite une ligne staging. Retourne True (ok), None (skip), False (erreur)."""

    def preload_caches(self, conn: Connection) -> None:  # noqa: B027 (hook optionnel)
        """Pré-chargement optionnel (ex: struct_cache pour HAL)."""

    def summary_stats(self, conn: Connection) -> list[str]:
        """Lignes additionnelles à logger en fin de run."""
        return []

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

    def run(self) -> NormalizeStats:
        """Entry point : pilote la boucle de normalisation."""
        self.conn.rollback()

        # Préfixe `[source]` sur les lignes de la boucle (progression, bilan) : dans un run multi-sources, chaque batch reste rattaché à sa source sans remonter au bandeau.
        slog = scoped_logger(self.logger, self.SOURCE)

        try:
            total = self._count_pending(self.conn)
            slog.info(f"=== Normalisation : {total} works à traiter ===")
            if total == 0:
                slog.info("rien à traiter")
                return NormalizeStats(0, 0, 0)

            slog.info(f"Traitement de {total} works (batch size: {self.DEFAULT_BATCH_SIZE})")

            self.preload_caches(self.conn)

            processed = 0
            skipped = 0
            errors = 0

            for row in self._iter_rows(self.conn):
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

                done = processed + skipped
                if done > 0 and done % self.DEFAULT_BATCH_SIZE == 0:
                    self.conn.commit()
                    parts = [f"{done}/{total} traités"]
                    if skipped:
                        parts.append(f"{skipped} ignorés")
                    if errors:
                        parts.append(f"{errors} erreurs")
                    slog.info(f"  {', '.join(parts)}")

            self.conn.commit()
            self.cleanup()

            slog.info("\n=== Normalisation terminée ===")
            slog.info(f"Traités avec succès : {processed}")
            if skipped:
                slog.info(f"Ignorés : {skipped}")
            slog.info(f"Erreurs : {errors}")
            for line in self.summary_stats(self.conn):
                slog.info(line)

            return NormalizeStats(processed, skipped, errors)

        except KeyboardInterrupt:
            # Ctrl+C frappe souvent en plein `conn.execute()` : la transaction est alors avortée et `commit()` lèverait `PendingRollbackError`.
            # On rollback (le batch en cours, incomplet, est jeté ; les batches committés tous les `batch_size` sont durables) puis on re-raise pour laisser `run_pipeline.main()` faire l'arrêt propre (rapport partiel + exit 130).
            # Sans le `raise`, la phase « réussirait » et le pipeline enchaînerait sur la source suivante.
            self.conn.rollback()
            slog.warning("Interruption — batches déjà committés conservés.")
            raise
        except Exception as e:
            self.conn.rollback()
            slog.error(f"Erreur fatale : {e}")
            raise
