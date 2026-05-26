"""Sub-step de la phase pipeline `publishers_journals` — enrichit les
revues à partir de l'API DOAJ.

Pour chaque revue avec au moins un ISSN (et un dernier import DOAJ
absent ou plus vieux que ``stale_days`` jours) :

1. Essaie successivement ``issn``, ``eissn``, ``issnl`` (les valeurs
   vides et doublons sont sautés) via le ``DoajFetcher`` injecté.
2. Sur succès : passe le record API au ``DoajShapeMapper`` injecté
   pour obtenir un payload au format CSV (cf.
   `infrastructure/sources/doaj` pour le choix non-orthodoxe assumé)
   et écrit ``doaj_payload`` + ``doaj_imported_at`` + ``is_in_doaj=TRUE``.
3. Sur 404 (tous les ISSN testés) : écrit ``doaj_payload=NULL`` +
   ``doaj_imported_at=now()`` + ``is_in_doaj=FALSE``. Le timestamp est
   posé même sans payload pour que la revue sorte de la file de stale
   et ne soit pas retentée à chaque pipeline.

Pas de reset global : un journal qui sort de DOAJ ne sera détecté
qu'à son prochain refetch (≤ ``stale_days``).

Le fetcher et le mapper concrets vivent dans
``infrastructure/sources/doaj/``; ils sont injectés par la composition
root pour respecter l'étanchéité DDD.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.journal_repository import JournalRepository

type DoajFetcher = Callable[[str], dict[str, Any] | None]
"""Signature : ``(issn) → record API ou None (pas dans DOAJ / erreur)``."""

type DoajShapeMapper = Callable[[dict[str, Any]], dict[str, str]]
"""Signature : ``(record API) → dict aux clés CSV à stocker en JSONB``."""

COMMIT_EVERY = 50
DEFAULT_STALE_DAYS = 30


def _candidate_issns(issn: str | None, eissn: str | None, issnl: str | None) -> list[str]:
    """Ordre stable de tentative, sans doublons ni vides."""
    out: list[str] = []
    for v in (issn, eissn, issnl):
        if v and v not in out:
            out.append(v)
    return out


def run_enrich_journals_from_doaj(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    journal_repo: JournalRepository,
    fetcher: DoajFetcher,
    mapper: DoajShapeMapper,
    stale_days: int = DEFAULT_STALE_DAYS,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.15,
) -> None:
    try:
        candidates = queries.fetch_journals_needing_doaj_fetch(
            conn, stale_days=stale_days, limit=limit or None
        )
        total = len(candidates)
        logger.info(
            "%d revues candidates (au moins un ISSN, stale > %d jours).",
            total,
            stale_days,
        )

        if total == 0:
            logger.info("Rien à faire.")
            return

        in_doaj = 0
        not_in_doaj = 0
        no_issn = 0  # candidats avec ISSN nul après filtrage (improbable)

        for i, (journal_id, issn, eissn, issnl) in enumerate(candidates, 1):
            attempts = _candidate_issns(issn, eissn, issnl)
            if not attempts:
                no_issn += 1
                continue

            record: dict[str, Any] | None = None
            for tried in attempts:
                record = fetcher(tried)
                time.sleep(rate_delay)
                if record is not None:
                    break

            now = datetime.now(UTC)
            if record is None:
                if not dry_run:
                    journal_repo.update_journal_doaj(
                        journal_id,
                        payload=None,
                        imported_at=now,
                        is_in_doaj=False,
                    )
                not_in_doaj += 1
            else:
                payload = mapper(record)
                if not dry_run:
                    journal_repo.update_journal_doaj(
                        journal_id,
                        payload=payload,
                        imported_at=now,
                        is_in_doaj=True,
                    )
                in_doaj += 1

            if not dry_run and i % COMMIT_EVERY == 0:
                conn.commit()
                logger.info(
                    "  %d/%d traités, %d dans DOAJ, %d 404",
                    i,
                    total,
                    in_doaj,
                    not_in_doaj,
                )

        if not dry_run:
            conn.commit()

        logger.info(
            "Terminé : %d/%d revues mises à jour (%d dans DOAJ, %d 404, %d sans ISSN).",
            in_doaj + not_in_doaj,
            total,
            in_doaj,
            not_in_doaj,
            no_issn,
        )

    except KeyboardInterrupt:
        if not dry_run:
            conn.commit()
        logger.warning("Interruption — données déjà traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
