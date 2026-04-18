"""
Moissonnage des identifiants (ORCID, IdRef) depuis l'API personnes HAL.

Interroge l'API ref/author de HAL pour les source_persons HAL avec hal_person_id
et récupère ORCID et IdRef en une seule passe.

Met à jour :
  - source_persons.orcid, source_persons.idref
  - person_identifiers (source='hal')

Usage:
    python harvest_hal_identifiers.py              # moissonnage complet
    python harvest_hal_identifiers.py --dry-run    # rapport sans écriture
    python harvest_hal_identifiers.py --batch 50   # taille de batch API
"""

import argparse
import os
import time

import requests

from infrastructure.db.connection import get_connection
from infrastructure.api_limits import HAL_DELAY
from infrastructure.log import setup_logger

logger = setup_logger("harvest_hal_identifiers", os.path.join(os.path.dirname(__file__), "logs"))

API_URL = "https://api.archives-ouvertes.fr/ref/author/"


def fetch_identifiers_batch(person_ids: list[int]) -> dict[int, dict]:
    """Interroge l'API HAL pour un lot de person_ids.

    Retourne {hal_person_id: {"orcid": ..., "idref": ...}} pour ceux qui en ont.
    """
    if not person_ids:
        return {}

    or_clause = " OR ".join(str(pid) for pid in person_ids)
    params = {
        "q": f"person_i:({or_clause})",
        "fl": "person_i,orcidId_s,idrefId_s",
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
                logger.warning(f"Erreur API (tentative {attempt + 1}/3): {e} — attente {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"Échec après 3 tentatives: {e}")
                return {}

    results = {}
    for doc in data.get("response", {}).get("docs", []):
        pid = doc.get("person_i")
        if not pid:
            continue

        identifiers = {}

        # ORCID
        orcid_raw = doc.get("orcidId_s")
        if orcid_raw:
            if isinstance(orcid_raw, list):
                orcid_raw = orcid_raw[0]
            orcid = orcid_raw.replace("https://orcid.org/", "").strip()
            if orcid:
                identifiers["orcid"] = orcid

        # IdRef
        idref_raw = doc.get("idrefId_s")
        if idref_raw:
            if isinstance(idref_raw, list):
                idref_raw = idref_raw[0]
            # idrefId_s peut être une URL complète ou juste l'identifiant
            idref = idref_raw.rsplit("/", 1)[-1] if "/" in idref_raw else idref_raw
            idref = idref.strip()
            if idref:
                identifiers["idref"] = idref

        if identifiers:
            results[pid] = identifiers

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Moissonnage ORCID + IdRef depuis l'API personnes HAL"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--batch", type=int, default=100, help="Nombre de person_ids par requête API (défaut: 100)"
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        # source_persons HAL avec hal_person_id mais sans ORCID ou sans idRef
        cur.execute("""
            SELECT id, (source_ids->>'hal_person_id')::int AS hal_person_id, person_id
            FROM source_persons
            WHERE source = 'hal'
              AND (source_ids->>'hal_person_id') IS NOT NULL
              AND (orcid IS NULL OR idref IS NULL)
            ORDER BY id
        """)
        rows = cur.fetchall()
        logger.info(f"{len(rows)} source_persons HAL à interroger (ORCID ou IdRef manquant)")

        if not rows:
            logger.info("Rien à faire.")
            return

        stats = {"orcid_found": 0, "idref_found": 0, "ha_updated": 0}
        batch_size = args.batch

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            # {hal_person_id: (source_persons.id, person_id)}
            id_map = {row[1]: (row[0], row[2]) for row in batch}
            person_ids = list(id_map.keys())

            identifiers = fetch_identifiers_batch(person_ids)

            if identifiers and not args.dry_run:
                for pid, ids in identifiers.items():
                    ha_id, person_id = id_map[pid]

                    if "orcid" in ids:
                        cur.execute(
                            """
                            UPDATE source_persons
                            SET orcid = COALESCE(orcid, %s), updated_at = now()
                            WHERE id = %s AND orcid IS NULL
                        """,
                            (ids["orcid"], ha_id),
                        )
                        if cur.rowcount:
                            stats["ha_updated"] += 1
                        stats["orcid_found"] += 1

                    if "idref" in ids:
                        cur.execute(
                            """
                            UPDATE source_persons
                            SET idref = COALESCE(idref, %s), updated_at = now()
                            WHERE id = %s AND idref IS NULL
                        """,
                            (ids["idref"], ha_id),
                        )
                        if cur.rowcount:
                            stats["ha_updated"] += 1
                        stats["idref_found"] += 1

                conn.commit()
            elif identifiers:
                for pid, ids in identifiers.items():
                    if "orcid" in ids:
                        stats["orcid_found"] += 1
                    if "idref" in ids:
                        stats["idref_found"] += 1

            batch_num = i // batch_size + 1
            total_batches = (len(rows) + batch_size - 1) // batch_size
            if batch_num % 10 == 0 or batch_num == total_batches:
                logger.info(
                    f"  Batch {batch_num}/{total_batches} — "
                    f"{stats['orcid_found']} ORCID, {stats['idref_found']} IdRef"
                )

            time.sleep(HAL_DELAY)

        if args.dry_run:
            conn.rollback()
            logger.info(
                f"\n[DRY RUN] {stats['orcid_found']} ORCID, {stats['idref_found']} IdRef trouvés"
            )
        else:
            logger.info("\n=== Terminé ===")
            logger.info(f"  ORCID trouvés : {stats['orcid_found']}")
            logger.info(f"  IdRef trouvés : {stats['idref_found']}")
            logger.info(f"  source_persons mis à jour : {stats['ha_updated']}")

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
