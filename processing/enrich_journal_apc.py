#!/usr/bin/env python3
"""
Enrichit les revues avec les données APC (Article Processing Charges) depuis OpenAlex.

Source des données : prix catalogue DOAJ, exposés via l'API OpenAlex Sources.
Champs mis à jour : apc_amount, apc_currency, is_in_doaj.

Utilise le filtre openalex avec pipe (|) pour interroger jusqu'à 50 sources par requête.
"""

import argparse
import logging
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from services.journals import update_journal_apc, reset_journal_apc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "logs", "enrich_journal_apc.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

OPENALEX_API = "https://api.openalex.org/sources"
OPENALEX_PREFIX = "https://openalex.org/"
BATCH_SIZE = 50          # max IDs par requête (API limit = 100, on reste prudent)
REQUEST_DELAY = 0.15     # délai entre requêtes (politeness)
COMMIT_EVERY = 500       # commit DB tous les N journals traités
try:
    from config.settings import OPENALEX
    MAILTO = OPENALEX.get("email", "bibliometrie@uca.fr")
except ImportError:
    MAILTO = "bibliometrie@uca.fr"


def to_full_id(short_id: str) -> str:
    """Convertit 'S20400310' → 'https://openalex.org/S20400310'."""
    if short_id.startswith("http"):
        return short_id
    return OPENALEX_PREFIX + short_id


def to_short_id(full_id: str) -> str:
    """Convertit 'https://openalex.org/S20400310' → 'S20400310'."""
    if full_id.startswith(OPENALEX_PREFIX):
        return full_id[len(OPENALEX_PREFIX):]
    return full_id


def fetch_sources_batch(openalex_ids: list[str]) -> dict[str, dict]:
    """Interroge l'API OpenAlex pour un lot d'IDs et retourne un dict short_id → données."""
    full_ids = [to_full_id(oid) for oid in openalex_ids]
    filter_value = "|".join(full_ids)
    params = {
        "filter": f"openalex:{filter_value}",
        "per_page": len(openalex_ids),
        "select": "id,apc_usd,apc_prices,is_in_doaj",
        "mailto": MAILTO,
    }

    for attempt in range(3):
        try:
            resp = requests.get(OPENALEX_API, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited (429), attente {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            results = {}
            for source in data.get("results", []):
                short = to_short_id(source["id"])
                results[short] = source
            return results
        except requests.RequestException as e:
            if attempt < 2:
                logger.warning(f"Erreur requête (tentative {attempt+1}/3): {e}")
                time.sleep(2 ** (attempt + 1))
            else:
                logger.error(f"Échec après 3 tentatives: {e}")
                return {}
    return {}


def extract_apc(source: dict) -> tuple[float | None, str]:
    """Extrait le montant APC et la devise depuis les données OpenAlex.

    Priorité : EUR dans apc_prices > première devise dispo > apc_usd en USD.
    """
    apc_prices = source.get("apc_prices") or []

    # Chercher EUR en priorité
    for entry in apc_prices:
        if entry.get("currency") == "EUR":
            return entry["price"], "EUR"

    # Sinon prendre la première devise disponible
    if apc_prices:
        entry = apc_prices[0]
        return entry["price"], entry.get("currency", "USD")

    # Fallback : apc_usd (montant converti par OpenAlex)
    apc_usd = source.get("apc_usd")
    if apc_usd is not None:
        return apc_usd, "USD"

    return None, "EUR"


def main():
    parser = argparse.ArgumentParser(
        description="Enrichir les revues avec les APC depuis OpenAlex (prix catalogue DOAJ)"
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="Limiter le nombre de revues traitées (0 = toutes)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Aperçu sans modifier la base")
    parser.add_argument("--reset", action="store_true",
                        help="Réinitialiser apc_amount/is_in_doaj pour retraiter")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        if args.reset:
            count = reset_journal_apc(cur)
            conn.commit()
            logger.info(f"Reset : {count} revues réinitialisées.")

        # Sélectionner les revues avec openalex_id et sans APC renseigné
        query = """
            SELECT id, openalex_id
            FROM journals
            WHERE openalex_id IS NOT NULL
              AND apc_amount IS NULL
            ORDER BY id
        """
        if args.limit:
            query += f" LIMIT {args.limit}"

        cur.execute(query)
        journals = cur.fetchall()
        total = len(journals)
        logger.info(f"{total} revues à traiter (avec openalex_id, sans APC).")

        if total == 0:
            logger.info("Rien à faire.")
            return

        updated = 0
        doaj_count = 0
        with_apc = 0
        processed = 0

        # Traiter par lots
        for i in range(0, total, BATCH_SIZE):
            batch = journals[i:i + BATCH_SIZE]
            oa_ids = [row[1] for row in batch]
            id_map = {row[1]: row[0] for row in batch}  # openalex_id → journal_id

            sources = fetch_sources_batch(oa_ids)
            time.sleep(REQUEST_DELAY)

            for oa_id, journal_id in id_map.items():
                source = sources.get(oa_id)
                if not source:
                    processed += 1
                    continue

                is_in_doaj = source.get("is_in_doaj", False) or False
                apc_amount, apc_currency = extract_apc(source)

                if not args.dry_run:
                    update_journal_apc(cur, journal_id,
                                       apc_amount=apc_amount,
                                       apc_currency=apc_currency,
                                       is_in_doaj=is_in_doaj)

                updated += 1
                if is_in_doaj:
                    doaj_count += 1
                if apc_amount is not None:
                    with_apc += 1
                processed += 1

            # Commit par lots
            if not args.dry_run and processed % COMMIT_EVERY < BATCH_SIZE:
                conn.commit()

            logger.info(
                f"  {min(i + BATCH_SIZE, total)}/{total} — "
                f"{with_apc} avec APC, {doaj_count} DOAJ"
            )

        if not args.dry_run:
            conn.commit()

        logger.info(
            f"Terminé : {updated}/{total} revues mises à jour, "
            f"{with_apc} avec APC, {doaj_count} dans DOAJ."
        )

    except KeyboardInterrupt:
        if not args.dry_run:
            conn.commit()
        logger.warning("Interruption — données déjà traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
