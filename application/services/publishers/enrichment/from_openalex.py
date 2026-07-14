"""
Orchestrateur d'enrichissement éditeurs (maintenance, hors pipeline) à
partir de l'API OpenAlex Publishers.

Met à jour `country` quand la valeur DB est NULL, depuis
`country_codes[0]` : un éditeur peut opérer dans plusieurs pays côté
OpenAlex, on prend le premier, qui correspond généralement au siège
social.

L'API Publishers filtre par `ids.openalex:P1|P2|...`.
"""

import logging
import time
from collections import Counter

import requests
from sqlalchemy import Connection

from application.ports.publishers_enrichment import PublisherEnrichmentQueries
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdateFields,
)
from domain.sources.openalex import full_openalex_id, short_openalex_id

BATCH_SIZE = 50
# Coupe-circuit : N batches consécutifs en 429 (budget API OpenAlex épuisé) avant coupure.
RATE_LIMIT_STRIKES_MAX = 3


class _OpenAlexRateLimited(Exception):
    """429 répétés sur un batch (3 retries épuisés) : budget API probablement épuisé."""


def fetch_publishers_batch(
    openalex_ids: list[str],
    logger: logging.Logger,
    *,
    openalex_publishers_api: str,
    api_key: str | None,
    mailto: str,
) -> dict[str, dict]:
    """Interroge l'API OpenAlex Publishers pour un lot d'IDs et retourne
    un dict short_id → données. Select restreint aux champs consommés."""
    full_ids = [full_openalex_id(oid) for oid in openalex_ids]
    filter_value = "|".join(full_ids)
    params = {
        "filter": f"ids.openalex:{filter_value}",
        "per_page": str(len(openalex_ids)),
        "select": "id,country_codes",
    }
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = mailto

    for attempt in range(3):
        try:
            resp = requests.get(openalex_publishers_api, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited (429), attente {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return {short_openalex_id(source["id"]): source for source in data.get("results", [])}
        except requests.RequestException as e:
            if attempt < 2:
                logger.warning(f"Erreur requête (tentative {attempt + 1}/3): {e}")
                time.sleep(2 ** (attempt + 1))
            else:
                logger.error(f"Échec après 3 tentatives: {e}")
                return {}
    raise _OpenAlexRateLimited()


def extract_country(source: dict) -> str | None:
    """Extrait le `country` depuis la payload OpenAlex Publishers.

    Premier code de `country_codes`, en minuscule (canonique ; OpenAlex
    renvoie de la majuscule). Vide → None.
    """
    country_codes = source.get("country_codes") or []
    return country_codes[0].lower() if country_codes else None


def run_enrich_publishers_from_openalex(
    conn: Connection,
    queries: PublisherEnrichmentQueries,
    logger: logging.Logger,
    *,
    publisher_repo: PublisherRepository,
    api_key: str | None,
    mailto: str,
    openalex_publishers_api: str,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.1,
) -> None:
    try:
        publishers = queries.fetch_publishers_needing_enrichment(conn, limit=limit or None)
        total = len(publishers)
        logger.info(f"{total} publishers à enrichir (avec openalex_id, manque country).")

        if total == 0:
            logger.info("Rien à faire.")
            return

        updated = 0
        with_country = 0
        country_counter: Counter[str] = Counter()
        no_response = 0
        processed = 0
        strikes = 0  # batches 429 consécutifs (coupe-circuit)

        for i in range(0, total, BATCH_SIZE):
            batch = publishers[i : i + BATCH_SIZE]
            oa_ids = [row[1] for row in batch]
            id_map = {row[1]: row[0] for row in batch}

            try:
                sources = fetch_publishers_batch(
                    oa_ids,
                    logger,
                    openalex_publishers_api=openalex_publishers_api,
                    api_key=api_key,
                    mailto=mailto,
                )
            except _OpenAlexRateLimited:
                strikes += 1
                if strikes >= RATE_LIMIT_STRIKES_MAX:
                    if not dry_run:
                        conn.commit()
                    logger.warning(
                        "⚡ Coupe-circuit OpenAlex (429 sur %d batches consécutifs) : "
                        "enrichissement publishers interrompu à %d/%d. Reste retenté au prochain run.",
                        strikes,
                        processed,
                        total,
                    )
                    return
                continue
            strikes = 0
            time.sleep(rate_delay)

            for oa_id, publisher_id in id_map.items():
                source = sources.get(oa_id)
                if not source:
                    no_response += 1
                    processed += 1
                    continue

                country = extract_country(source)

                # On charge l'état actuel via l'aggregate pour décider du
                # gating "NULL only". Un fetch supplémentaire par publisher
                # — acceptable vu le volume (au max ~1000 publishers à
                # enrichir).
                current = publisher_repo.find_by_id(publisher_id)
                if current is None:
                    no_response += 1
                    processed += 1
                    continue

                fields: PublisherUpdateFields = {}
                if country and current.country is None:
                    fields["country"] = country
                    with_country += 1
                    country_counter[country] += 1

                if fields and not dry_run:
                    publisher_repo.update_publisher_fields(publisher_id, fields)
                    updated += 1
                elif fields:
                    updated += 1  # compté en dry-run aussi
                processed += 1

            # Commit chaque batch pour préserver la progression en cas
            # d'interruption — l'enrich est par nature idempotent (re-skip
            # les publishers déjà enrichis via le filtre `fetch_publishers_needing_enrichment`).
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
