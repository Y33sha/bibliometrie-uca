"""
Enrichissement du statut Open Access via l'API Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour
le statut OA. Écrase les valeurs existantes, SAUF : ne remplace jamais
'diamond' par 'gold' (Unpaywall ne connaît pas le diamond OA).

Usage:
    python enrich_oa_unpaywall.py              # traiter toutes les publis avec DOI
    python enrich_oa_unpaywall.py --limit 500  # traiter N publis (pour test)
    python enrich_oa_unpaywall.py --dry-run    # afficher sans modifier

API: https://api.unpaywall.org/v2/{doi}?email=...
Rate limit: 100 000 req/jour, ~10 req/s recommandé
"""

import argparse
import os
import time

import requests

from db.connection import get_connection
from services.publications import update_oa_status
from utils.api_limits import UNPAYWALL_DELAY
from utils.log import setup_logger

log = setup_logger("enrich_oa_unpaywall", os.path.join(os.path.dirname(__file__), "logs"))

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


def fetch_oa_status(doi: str) -> str | None:
    """Interroge Unpaywall pour un DOI. Retourne le statut OA ou None."""
    for attempt in range(3):
        try:
            url = f"{UNPAYWALL_BASE}/{doi}?email={UNPAYWALL_EMAIL}"
            resp = requests.get(url, timeout=10)

            if resp.status_code == 404:
                return None  # DOI inconnu d'Unpaywall
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                log.warning(f"Rate limited, pause {wait}s (tentative {attempt + 1}/3)...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                log.warning(f"  HTTP {resp.status_code} pour {doi}")
                return None

            data = resp.json()
            oa_status = data.get("oa_status")
            return OA_MAP.get(oa_status)

        except requests.RequestException as e:
            log.warning(f"  Erreur réseau pour {doi}: {e}")
            return None

    log.warning(f"  Échec après 3 tentatives pour {doi}")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0, help="Nombre max de publis à traiter (0=toutes)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Afficher sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Trouver les publis avec DOI (toutes, pas seulement unknown)
    query = """
        SELECT id, doi, oa_status::text FROM publications
        WHERE doi IS NOT NULL
        ORDER BY pub_year DESC, id
    """
    if args.limit:
        query += f" LIMIT {args.limit}"

    cur.execute(query)
    pubs = cur.fetchall()
    total = len(pubs)
    log.info(f"{total} publications avec DOI à vérifier sur Unpaywall")

    if not total:
        conn.close()
        return

    updated = 0
    skipped = 0
    not_found = 0
    errors = 0

    for i, (pub_id, doi, current_status) in enumerate(pubs):
        if i > 0 and i % BATCH_SIZE == 0:
            if not args.dry_run:
                conn.commit()
            log.info(
                f"  {i}/{total} — {updated} mis à jour, {skipped} inchangés, {not_found} non trouvés"
            )

        status = fetch_oa_status(doi)

        if status:
            # Ne pas écraser diamond par gold (Unpaywall ne connaît pas diamond)
            if current_status == "diamond" and status == "gold":
                skipped += 1
                time.sleep(UNPAYWALL_DELAY)
                continue

            # Ne pas mettre à jour si le statut est identique
            if status == current_status:
                skipped += 1
                time.sleep(UNPAYWALL_DELAY)
                continue

            if args.dry_run:
                log.info(f"  [DRY] {doi} : {current_status} → {status}")
            else:
                update_oa_status(cur, pub_id, status)
            updated += 1
        elif status is None:
            not_found += 1
        else:
            errors += 1

        time.sleep(UNPAYWALL_DELAY)

    if not args.dry_run:
        conn.commit()

    log.info(
        f"Terminé : {updated} mis à jour, {skipped} inchangés, {not_found} non trouvés sur Unpaywall, {errors} erreurs"
    )
    conn.close()


if __name__ == "__main__":
    main()
