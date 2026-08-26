"""Enrichissement (cosmétique) du `country` des éditeurs depuis l'API OpenAlex Publishers.

Maintenance hors pipeline, lancée à la demande par `interfaces/cli/maintenance/enrich_publishers.py`. Politique « NULL only » : le pays n'est écrit que là où la base n'en porte pas, si bien qu'une valeur saisie à la main est préservée et que deux exécutions successives donnent le même résultat.

Le fetch OpenAlex et le circuit-breaker de source sont injectés — le HTTP vit dans `infrastructure/sources/openalex/publisher_enrichment.py`, avec ses retries et son backoff. Cet orchestrateur ne consulte que l'état du breaker, pour s'arrêter quand la source est à bout de budget et reporter le reste à l'exécution suivante.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import NamedTuple

from sqlalchemy import Connection

from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.repositories.publisher_repository import PublisherRepository

BATCH_SIZE = 50

FetchPublishersBatch = Callable[[list[str]], dict[str, str | None]]
"""Signature du fetch injecté : `(openalex_ids) -> {short_id: pays}`. Le pays vaut `None` quand la source n'en donne pas ; un éditeur sur lequel elle ne répond rien est absent du dictionnaire."""


class _BatchOutcome(NamedTuple):
    """Compteurs agrégés du traitement d'un batch d'éditeurs."""

    updated: int
    with_country: int
    no_response: int
    countries: Counter[str]


def _enrich_batch(
    id_map: dict[str, int],
    countries_by_id: dict[str, str | None],
    *,
    publisher_repo: PublisherRepository,
    dry_run: bool,
) -> _BatchOutcome:
    """Applique le pays OpenAlex aux éditeurs d'un batch, en « NULL only ».

    `id_map` associe openalex_id → publisher_id. Un éditeur sur lequel la source n'a rien répondu, ou disparu de la base, compte comme `no_response` ; un éditeur au `country` déjà renseigné est ignoré.
    """
    updated = with_country = no_response = 0
    countries: Counter[str] = Counter()
    for oa_id, publisher_id in id_map.items():
        if oa_id not in countries_by_id:
            no_response += 1
            continue
        country = countries_by_id[oa_id]
        current = publisher_repo.find_by_id(publisher_id)
        if current is None:
            no_response += 1
            continue
        if country and current.country is None:
            with_country += 1
            countries[country] += 1
            current.country = country
            if not dry_run:
                publisher_repo.save(current)
            updated += 1
    return _BatchOutcome(updated, with_country, no_response, countries)


def run_enrich_publishers_from_openalex(
    conn: Connection,
    logger: logging.Logger,
    *,
    publisher_repo: PublisherRepository,
    fetch_batch: FetchPublishersBatch,
    breaker: CircuitBreaker,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.1,
) -> None:
    try:
        publishers = publisher_repo.find_needing_country_enrichment(limit=limit or None)
        total = len(publishers)
        logger.info(f"{total} publishers à enrichir (avec openalex_id, manque country).")

        if total == 0:
            logger.info("Rien à faire.")
            return

        updated = with_country = no_response = processed = 0
        country_counter: Counter[str] = Counter()

        for i in range(0, total, BATCH_SIZE):
            if breaker.tripped:
                if not dry_run:
                    conn.commit()
                logger.warning(
                    "⚡ Coupe-circuit OpenAlex : enrichissement éditeurs interrompu à %d/%d. "
                    "Reste retenté à la prochaine exécution.",
                    processed,
                    total,
                )
                return

            id_map = {row[1]: row[0] for row in publishers[i : i + BATCH_SIZE]}
            countries_by_id = fetch_batch(list(id_map))
            time.sleep(rate_delay)

            outcome = _enrich_batch(
                id_map, countries_by_id, publisher_repo=publisher_repo, dry_run=dry_run
            )
            updated += outcome.updated
            with_country += outcome.with_country
            no_response += outcome.no_response
            country_counter += outcome.countries
            processed += len(id_map)

            if not dry_run:
                conn.commit()

            logger.info(f"  {min(i + BATCH_SIZE, total)}/{total} — {with_country} countries écrits")

        if not dry_run:
            conn.commit()

        logger.info(
            f"Terminé : {updated}/{total} publishers mis à jour "
            f"({with_country} countries, {no_response} sans réponse)."
        )
        if country_counter:
            distrib = ", ".join(f"{c}={n}" for c, n in country_counter.most_common(10))
            logger.info(f"Top 10 countries posés : {distrib}")

    except KeyboardInterrupt:
        # Ctrl+C peut frapper en plein execute (transaction avortée → `commit()`
        # lèverait `PendingRollbackError`) : on rollback le batch en cours et on
        # re-raise pour laisser l'appelant (CLI maintenance) s'arrêter proprement.
        conn.rollback()
        logger.warning("Interruption — batches déjà committés conservés.")
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
