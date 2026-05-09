"""Base class pour les normaliseurs de sources.

Capture le boilerplate commun aux 6 normalizers existants :
- parsing CLI (--limit, --reset, --batch-size)
- gestion du cycle connexion (open, commit, close)
- --reset : UPDATE processed=FALSE
- comptage + chargement des work_ids à traiter
- boucle avec `try/rollback/continue` + commit périodique
- logs de progression et summary

L'accès au staging passe par le port `StagingQueries` (injecté par le
point d'entrée CLI dans `interfaces/cli/pipeline/`). Chaque source hérite
et implémente `process_work()`.

Dispatche sur le type de `self.conn` :
- mode legacy psycopg : `cur = self.conn.cursor(...)`, transmis à
  `process_work(cur, row)`. `USE_DICT_CURSOR` choisit `dict_row` ou
  `tuple_row`.
- mode cible SA : `process_work(self.conn, row)` (Connection SA Core,
  les query services dispatchent en interne sur le type).
Le dispatch disparaît quand les 6 normalizers sont migrés en SA.
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from psycopg.rows import dict_row, tuple_row
from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.ports.staging import StagingQueries


class SourceNormalizer(ABC):
    """Template method pour la normalisation source → tables structurées.

    Override points :
    - `SOURCE` : identifiant source (obligatoire, ex: "hal", "openalex")
    - `DEFAULT_BATCH_SIZE` : taille de commit (défaut 500)
    - `USE_DICT_CURSOR` : `True` = row_factory=dict_row (défaut), `False` = tuple cursor.
      Ignoré en mode SA (les rows SA supportent attribut + position).
    - `USE_SAVEPOINT` : `True` pour encadrer chaque `process_work` dans un SAVEPOINT
    - `FETCH_SUB_BATCH` : si défini, charge les ids puis fetch par sous-lots de cette taille
    - `FETCH_COLUMNS` : colonnes du SELECT (défaut "id, source_id, doi, raw_data")
    - `process_work(conn_or_cur, row) -> bool | None` : abstract, logique métier
    - `preload_caches(conn_or_cur)` : pré-chargement optionnel
    - `post_process(conn_or_cur)` : nettoyage post-traitement optionnel
    - `summary_stats(conn_or_cur) -> list[str]` : lignes log additionnelles
    - `cleanup()` : libération des caches après commit final
    """

    SOURCE: ClassVar[str] = ""
    DEFAULT_BATCH_SIZE: ClassVar[int] = 500
    USE_DICT_CURSOR: ClassVar[bool] = True
    USE_SAVEPOINT: ClassVar[bool] = False
    FETCH_SUB_BATCH: ClassVar[int | None] = None
    FETCH_COLUMNS: ClassVar[str] = "id, source_id, doi, raw_data"

    def __init__(self, conn: Any, logger: Any, staging_queries: StagingQueries) -> None:
        self.conn = conn
        self.logger = logger
        self._staging = staging_queries
        self._sa_mode = isinstance(conn, Connection)

    # ── Hooks métier ────────────────────────────────────────────

    @abstractmethod
    def process_work(self, conn_or_cur: Any, row: Any) -> bool | None:
        """Traite une ligne staging. Retourne True (ok), None (skip), False (erreur)."""

    def preload_caches(self, conn_or_cur: Any) -> None:  # noqa: B027 (hook optionnel)
        """Pré-chargement optionnel (ex: struct_cache pour HAL)."""

    def post_process(self, conn_or_cur: Any) -> None:  # noqa: B027 (hook optionnel)
        """Nettoyage post-traitement (ex: suppression des doublons pour HAL)."""

    def summary_stats(self, conn_or_cur: Any) -> list[str]:
        """Lignes additionnelles à logger en fin de run."""
        return []

    def cleanup(self) -> None:  # noqa: B027 (hook optionnel)
        """Libération des caches in-memory."""

    def on_error(self) -> None:  # noqa: B027 (hook optionnel)
        """Appelé après chaque rollback (SAVEPOINT ou complet).

        Les caches qui référencent des IDs générés dans la transaction
        rollbackée doivent être invalidés ici — sinon ils pointent vers
        des lignes qui n'existent plus, provoquant des FK violations sur
        les works suivants. Exemple typique : `PgAddressLinker._cache`.
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

    def _make_cursor(self) -> Any:
        """Renvoie soit un curseur psycopg (mode legacy), soit `self.conn` lui-même
        (mode SA — les query services prennent une Connection)."""
        if self._sa_mode:
            return self.conn
        if self.USE_DICT_CURSOR:
            return self.conn.cursor(row_factory=dict_row)
        return self.conn.cursor(row_factory=tuple_row)

    def _reset(self, conn_or_cur: Any) -> int:
        return self._staging.reset_processed_flag(conn_or_cur, self.SOURCE)

    def _count_pending(self, conn_or_cur: Any) -> int:
        return self._staging.count_pending_staging(conn_or_cur, self.SOURCE)

    def _iter_rows(self, conn_or_cur: Any, limit: int) -> Any:
        """Itère les lignes à traiter. Peut faire un fetch en un coup ou par sous-lots."""
        if self.FETCH_SUB_BATCH is None:
            yield from self._staging.fetch_pending_staging(
                conn_or_cur, self.SOURCE, columns=self.FETCH_COLUMNS, limit=limit
            )
            return

        work_ids = self._staging.fetch_pending_staging_ids(conn_or_cur, self.SOURCE, limit=limit)
        for start in range(0, len(work_ids), self.FETCH_SUB_BATCH):
            batch_ids = work_ids[start : start + self.FETCH_SUB_BATCH]
            yield from self._staging.fetch_staging_by_ids(
                conn_or_cur, batch_ids, columns=self.FETCH_COLUMNS
            )

    def _process_one(self, conn_or_cur: Any, row: Any) -> bool | None:
        """Enveloppe process_work avec SAVEPOINT optionnel."""
        if not self.USE_SAVEPOINT:
            return self.process_work(conn_or_cur, row)
        try:
            with savepoint(
                conn_or_cur,
                f"normalize_{self.SOURCE}_work",
                on_rollback_failure=self.conn.rollback,
            ):
                return self.process_work(conn_or_cur, row)
        except Exception:
            self.on_error()
            raise

    def run(self, argv: list[str] | None = None) -> None:
        """Entry point : parse args, drive the normalization loop."""
        args = self.parse_args(argv)
        self.conn.rollback()
        if not self._sa_mode:
            self.conn.autocommit = False

        try:
            cur = self._make_cursor()

            if args.reset:
                count = self._reset(cur)
                self.conn.commit()
                self.logger.info(f"Reset : {count} works remis à processed=FALSE")
                return

            total = self._count_pending(cur)
            self.logger.info(f"=== Normalisation {self.SOURCE} : {total} works à traiter ===")
            if total == 0:
                self.logger.info("Rien à faire.")
                return

            limit = min(args.limit or total, total)
            self.logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

            self.preload_caches(cur)

            processed = 0
            skipped = 0
            errors = 0

            for row in self._iter_rows(cur, limit):
                try:
                    result = self._process_one(cur, row)
                except Exception:
                    if not self.USE_SAVEPOINT:
                        self.conn.rollback()
                        self.on_error()
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
                    self.logger.info(f"  {', '.join(parts)}")

            self.conn.commit()
            self.post_process(cur)
            self.conn.commit()
            self.cleanup()

            self.logger.info("\n=== Terminé ===")
            self.logger.info(f"Traités avec succès : {processed}")
            if skipped:
                self.logger.info(f"Ignorés : {skipped}")
            self.logger.info(f"Erreurs : {errors}")
            for line in self.summary_stats(cur):
                self.logger.info(line)

        except KeyboardInterrupt:
            self.conn.commit()
            self.logger.warning("Interruption — données déjà traitées conservées.")
        except Exception as e:
            self.conn.rollback()
            self.logger.error(f"Erreur fatale : {e}")
            raise
        finally:
            self.conn.close()
