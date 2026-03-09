"""
Enrichissement du statut Open Access via l'API Unpaywall.

Pour les publications ayant un DOI mais un statut OA 'unknown',
interroge Unpaywall (gratuit, pas de clé API, juste un email).

Usage:
    python enrich_oa_unpaywall.py              # traiter toutes les publis unknown
    python enrich_oa_unpaywall.py --limit 500  # traiter N publis (pour test)
    python enrich_oa_unpaywall.py --dry-run    # afficher sans modifier

API: https://api.unpaywall.org/v2/{doi}?email=...
Rate limit: 100 000 req/jour, ~10 req/s recommandé
"""

import argparse
import logging
import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Email requis par Unpaywall (politesse, pas d'auth)
UNPAYWALL_EMAIL = "bibliometrie@uca.fr"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2"

# Mapping Unpaywall oa_status → notre enum oa_type
OA_MAP = {
    "gold": "gold",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "green": "green",
    "closed": "closed",
}

BATCH_SIZE = 50
REQUEST_DELAY = 0.12  # ~8 req/s, conservateur


def fetch_oa_status(doi: str) -> str | None:
    """Interroge Unpaywall pour un DOI. Retourne le statut OA ou None."""
    try:
        url = f"{UNPAYWALL_BASE}/{doi}?email={UNPAYWALL_EMAIL}"
        resp = requests.get(url, timeout=10)

        if resp.status_code == 404:
            return None  # DOI inconnu d'Unpaywall
        if resp.status_code == 429:
            log.warning("Rate limited, pause 5s...")
            time.sleep(5)
            return fetch_oa_status(doi)  # retry
        if resp.status_code != 200:
            log.warning(f"  HTTP {resp.status_code} pour {doi}")
            return None

        data = resp.json()
        oa_status = data.get("oa_status")
        return OA_MAP.get(oa_status)

    except requests.RequestException as e:
        log.warning(f"  Erreur réseau pour {doi}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Nombre max de publis à traiter (0=toutes)")
    parser.add_argument("--dry-run", action="store_true", help="Afficher sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Trouver les publis avec DOI et statut unknown
    query = """
        SELECT id, doi FROM publications
        WHERE oa_status = 'unknown' AND doi IS NOT NULL
        ORDER BY pub_year DESC, id
    """
    if args.limit:
        query += f" LIMIT {args.limit}"

    cur.execute(query)
    pubs = cur.fetchall()
    total = len(pubs)
    log.info(f"{total} publications avec DOI et statut OA indéterminé")

    if not total:
        conn.close()
        return

    updated = 0
    not_found = 0
    errors = 0

    for i, (pub_id, doi) in enumerate(pubs):
        if i > 0 and i % BATCH_SIZE == 0:
            if not args.dry_run:
                conn.commit()
            log.info(f"  {i}/{total} — {updated} mis à jour, {not_found} non trouvés")

        status = fetch_oa_status(doi)

        if status:
            if args.dry_run:
                log.info(f"  [DRY] {doi} → {status}")
            else:
                cur.execute(
                    "UPDATE publications SET oa_status = %s::oa_type, updated_at = now() WHERE id = %s",
                    (status, pub_id),
                )
            updated += 1
        elif status is None:
            not_found += 1
        else:
            errors += 1

        time.sleep(REQUEST_DELAY)

    if not args.dry_run:
        conn.commit()

    log.info(f"Terminé : {updated} mis à jour, {not_found} non trouvés sur Unpaywall, {errors} erreurs")
    conn.close()


if __name__ == "__main__":
    main()
