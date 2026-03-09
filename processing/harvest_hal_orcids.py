#!/usr/bin/env python3
"""
harvest_hal_orcids.py — Moissonnage des ORCID depuis l'API personnes HAL
========================================================================
Interroge l'API ref/author de HAL pour récupérer les ORCID associés
aux hal_person_id présents dans hal_authors.

Met à jour :
  - hal_authors.orcid  (enrichissement direct)
  - person_identifiers  (ajout d'entrées orcid source='hal')

Workflow HAL — position dans le pipeline :
  1. extract_hal.py           → staging_hal
  2. migrate_hal.py           → hal_documents, hal_authors, hal_authorships
  3. harvest_hal_orcids.py    → enrichit hal_authors.orcid (CE SCRIPT)
  4. migrate_person_identifiers.py → person_identifiers

Usage:
    python3 harvest_hal_orcids.py              # moissonnage complet
    python3 harvest_hal_orcids.py --dry-run    # rapport sans écriture
    python3 harvest_hal_orcids.py --batch 50   # taille de batch API (défaut: 100)
"""

import argparse
import logging
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from config.settings import HAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "harvest_hal_orcids.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

API_URL = "https://api.archives-ouvertes.fr/ref/author/"


def fetch_orcids_batch(person_ids: list[int]) -> dict[int, str]:
    """Interroge l'API HAL pour un lot de person_ids.

    Retourne {hal_person_id: orcid} pour ceux qui en ont un.
    """
    if not person_ids:
        return {}

    # Requête : person_i:(id1 OR id2 OR ...)
    or_clause = " OR ".join(str(pid) for pid in person_ids)
    params = {
        "q": f"person_i:({or_clause})",
        "fl": "person_i,orcidId_s",
        "rows": len(person_ids),
        "wt": "json",
    }

    for attempt in range(3):
        try:
            resp = requests.get(API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Erreur API (tentative {attempt+1}/3): {e} — attente {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"Échec après 3 tentatives: {e}")
                return {}

    results = {}
    for doc in data.get("response", {}).get("docs", []):
        pid = doc.get("person_i")
        orcid_raw = doc.get("orcidId_s")
        if pid and orcid_raw:
            # orcidId_s peut être une string ou une liste
            if isinstance(orcid_raw, list):
                orcid_raw = orcid_raw[0]
            orcid = orcid_raw.replace("https://orcid.org/", "").strip()
            if orcid:
                results[pid] = orcid

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Moissonnage des ORCID depuis l'API personnes HAL"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport sans écriture en base")
    parser.add_argument("--batch", type=int, default=100,
                        help="Nombre de person_ids par requête API (défaut: 100)")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        # Récupérer les hal_authors avec un hal_person_id mais sans ORCID
        cur.execute("""
            SELECT id, hal_person_id
            FROM hal_authors
            WHERE hal_person_id IS NOT NULL AND orcid IS NULL
            ORDER BY id
        """)
        rows = cur.fetchall()
        logger.info(f"=== Moissonnage ORCID depuis HAL ===")
        logger.info(f"{len(rows)} hal_authors avec person_id mais sans ORCID")

        if not rows:
            logger.info("Rien à faire.")
            return

        # Traitement par batch
        total_found = 0
        total_updated = 0
        total_pi_inserted = 0
        batch_size = args.batch

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            id_map = {pid: aid for aid, pid in batch}  # {hal_person_id: hal_authors.id}
            person_ids = list(id_map.keys())

            orcids = fetch_orcids_batch(person_ids)
            total_found += len(orcids)

            if orcids and not args.dry_run:
                for pid, orcid in orcids.items():
                    # 1. Mettre à jour hal_authors.orcid
                    cur.execute("""
                        UPDATE hal_authors
                        SET orcid = %s, updated_at = now()
                        WHERE hal_person_id = %s AND orcid IS NULL
                    """, (orcid, pid))
                    total_updated += cur.rowcount

                    # 2. Insérer dans person_identifiers (si person_id résolu)
                    cur.execute("""
                        INSERT INTO person_identifiers (person_id, id_type, id_value, source)
                        SELECT person_id, 'orcid', %s, 'hal'
                        FROM hal_authors
                        WHERE hal_person_id = %s AND person_id IS NOT NULL
                        ON CONFLICT (id_type, id_value) DO NOTHING
                    """, (orcid, pid))
                    total_pi_inserted += cur.rowcount

                conn.commit()

            batch_num = i // batch_size + 1
            total_batches = (len(rows) + batch_size - 1) // batch_size
            if batch_num % 10 == 0 or batch_num == total_batches:
                logger.info(
                    f"  Batch {batch_num}/{total_batches} — "
                    f"{total_found} ORCID trouvés, {total_updated} hal_authors mis à jour"
                )

            time.sleep(HAL["request_delay"])

        if args.dry_run:
            conn.rollback()
            logger.info(f"\n[DRY RUN] {total_found} ORCID trouvés (aucune modification)")
        else:
            # Stats finales
            cur.execute("SELECT COUNT(*) FROM hal_authors WHERE orcid IS NOT NULL")
            with_orcid = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM hal_authors")
            total_authors = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM person_identifiers
                WHERE id_type = 'orcid' AND source = 'hal'
            """)
            pi_hal_orcid = cur.fetchone()[0]

            logger.info(f"\n=== Terminé ===")
            logger.info(f"ORCID trouvés via API : {total_found}")
            logger.info(f"hal_authors mis à jour : {total_updated}")
            logger.info(f"person_identifiers ajoutés : {total_pi_inserted}")
            logger.info(f"hal_authors avec ORCID : {with_orcid}/{total_authors}")
            logger.info(f"person_identifiers (orcid, hal) : {pi_hal_orcid}")

    except KeyboardInterrupt:
        conn.commit()
        logger.warning("Interruption — données déjà écrites conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
