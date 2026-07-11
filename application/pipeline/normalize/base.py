"""Base class pour les normaliseurs de sources.

Capture le code commun aux normaliseurs :
- parsing CLI (--limit, --reset, --batch-size)
- commit périodique et rollback sur la connexion injectée (ouverte et fermée par l'appelant)
- --reset : UPDATE processed=FALSE
- comptage + chargement des work_ids à traiter
- boucle : un SAVEPOINT par work (une erreur isolée sans perdre le batch en cours), commit périodique
- logs de progression et bilan

L'accès au staging passe par le port `StagingQueries` (injecté par le composition root `run_pipeline`). Chaque source hérite et implémente `process_work()`.
"""

from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import ClassVar, NamedTuple

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.pipeline.logging_scope import scoped_logger
from application.ports.pipeline.staging import StagingQueries, StagingRow


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

    def on_error(self) -> None:  # noqa: B027 (hook optionnel)
        """Appelé après chaque rollback (SAVEPOINT ou complet).

        Les caches qui référencent des IDs générés dans la transaction annulée doivent être invalidés ici — sinon ils pointent vers des lignes qui n'existent plus, provoquant des violations de clé étrangère sur les works suivants. Exemple typique : `PgAddressLinker._cache`.
        """

    # ── Template method ────────────────────────────────────────

    def parse_args(self, argv: list[str] | None = None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description=f"Normalisation {self.SOURCE} → tables structurées"
        )
        parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
        parser.add_argument(
            "--reset", action="store_true", help="Remettre tous les works à processed=FALSE"
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=self.DEFAULT_BATCH_SIZE,
            help=f"Taille du commit batch (défaut: {self.DEFAULT_BATCH_SIZE})",
        )
        return parser.parse_args(argv)

    def _reset(self, conn: Connection) -> int:
        return self._staging.reset_processed_flag(conn, self.SOURCE)

    def _count_pending(self, conn: Connection) -> int:
        return self._staging.count_pending_staging(conn, self.SOURCE)

    def _iter_rows(self, conn: Connection, limit: int) -> Iterator[StagingRow]:
        """Itère les lignes à traiter par sous-lots de `FETCH_SUB_BATCH`."""
        work_ids = self._staging.fetch_pending_staging_ids(conn, self.SOURCE, limit=limit)
        for start in range(0, len(work_ids), self.FETCH_SUB_BATCH):
            batch_ids = work_ids[start : start + self.FETCH_SUB_BATCH]
            yield from self._staging.fetch_staging_by_ids(conn, batch_ids, source=self.SOURCE)

    def _process_one(self, conn: Connection, row: StagingRow) -> bool | None:
        """Enveloppe process_work dans un SAVEPOINT : un work en erreur est annulé sans abandonner le batch en cours."""
        try:
            with savepoint(
                conn,
                f"normalize_{self.SOURCE}_work",
                on_rollback_failure=self.conn.rollback,
            ):
                return self.process_work(conn, row)
        except Exception:
            self.on_error()
            raise

    def run(self, argv: list[str] | None = None) -> NormalizeStats:
        """Entry point : parse les arguments, pilote la boucle de normalisation."""
        args = self.parse_args(argv)
        self.conn.rollback()

        # Préfixe `[source]` sur les lignes de la boucle (progression, bilan) : dans un run multi-sources, chaque batch reste rattaché à sa source sans remonter au bandeau.
        slog = scoped_logger(self.logger, self.SOURCE)

        try:
            if args.reset:
                count = self._reset(self.conn)
                self.conn.commit()
                slog.info(f"Reset : {count} works remis à processed=FALSE")
                return NormalizeStats(0, 0, 0)

            total = self._count_pending(self.conn)
            slog.info(f"=== Normalisation : {total} works à traiter ===")
            if total == 0:
                slog.info("rien à traiter")
                return NormalizeStats(0, 0, 0)

            limit = min(args.limit or total, total)
            slog.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

            self.preload_caches(self.conn)

            processed = 0
            skipped = 0
            errors = 0

            for row in self._iter_rows(self.conn, limit):
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
                if done > 0 and done % args.batch_size == 0:
                    self.conn.commit()
                    parts = [f"{done}/{limit} traités"]
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
