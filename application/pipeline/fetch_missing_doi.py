"""Orchestrateur du fetch des DOI manquants dans une source cible.

Pour chaque DOI présent dans d'autres sources mais absent de la cible,
interroge l'API de la cible et insère le record dans staging.

Le comportement spécifique à chaque source (endpoint, auth, format de
requête/réponse, SQL d'insertion) est délégué à un adapter qui implémente
le protocole `FetchMissingDoiAdapter` défini ci-dessous.

Utilisé par la phase `fetch_missing_doi` du pipeline, une fois par source
cible (hal, openalex, wos, scanr).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Protocol

from infrastructure.sources.common import get_cross_import_dois


class FetchMissingDoiAdapter(Protocol):
    """Protocole source-spécifique utilisé par `run()`.

    Les attributs sont lus par l'orchestrateur pour paramétrer la boucle.
    Les méthodes encapsulent tout ce qui varie par source (HTTP, SQL).
    """

    source_key: str          # "hal" | "openalex" | "wos" | "scanr"
    rate_delay: float        # secondes de pause entre deux appels API
    batch_size: int          # 1 pour un appel par DOI, >1 pour un appel groupé

    def configure(self, cur: Any) -> None:
        """Lit la config (URLs, credentials) depuis la base avant la boucle."""

    def fetch(self, dois: list[str]) -> Iterable[dict]:
        """Interroge l'API pour un lot (1 à `batch_size` DOI). Retourne les
        records trouvés (vide si rien trouvé)."""

    def insert(self, conn: Any, record: dict) -> bool:
        """Insère le record dans staging. Retourne True si nouveau, False
        si déjà présent (ON CONFLICT DO NOTHING) ou non inséré."""


def run(
    conn: Any,
    adapter: FetchMissingDoiAdapter,
    log: logging.Logger,
    *,
    all_staged: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Boucle principale : missing DOIs → fetch → insert.

    Args:
        conn: connexion psycopg ouverte.
        adapter: instance source-spécifique.
        log: logger.
        all_staged: si False, ne considère que les DOI issus de rows
            `processed=FALSE` dans les autres sources.
        dry_run: compte et log sans fetch ni insert.
        limit: nombre max de DOI à traiter.

    Returns:
        Stats {dois, fetched, inserted}.
    """
    cur = conn.cursor()
    adapter.configure(cur)
    cur.close()

    dois = get_cross_import_dois(conn, adapter.source_key, all_staged=all_staged)
    log.info("%d DOI manquants pour %s", len(dois), adapter.source_key)

    if limit:
        dois = dois[:limit]
        log.info("Limité à %d DOI", len(dois))

    if dry_run:
        log.info("Dry-run — rien inséré.")
        return {"dois": len(dois), "fetched": 0, "inserted": 0}

    fetched = 0
    inserted = 0
    total = len(dois)

    for i in range(0, total, adapter.batch_size):
        batch = dois[i : i + adapter.batch_size]
        try:
            records = list(adapter.fetch(batch))
        except Exception as e:
            log.error("Erreur sur lot %d-%d : %s", i, i + len(batch), e)
            time.sleep(2)
            continue

        fetched += len(records)
        for record in records:
            try:
                if adapter.insert(conn, record):
                    inserted += 1
            except Exception as e:
                log.warning("Erreur insertion (%s) : %s", adapter.source_key, e)

        processed = min(i + adapter.batch_size, total)
        if processed % 100 == 0 or processed >= total:
            log.info(
                "  %d/%d — %d trouvés, %d insérés", processed, total, fetched, inserted
            )

        time.sleep(adapter.rate_delay)

    log.info(
        "Terminé %s : %d DOI, %d trouvés, %d insérés",
        adapter.source_key,
        total,
        fetched,
        inserted,
    )
    return {"dois": total, "fetched": fetched, "inserted": inserted}
