"""
Moissonnage des identifiants (ORCID, IdRef) depuis l'API personnes HAL.

Interroge l'API ref/author de HAL pour les source_persons HAL avec hal_person_id
et récupère ORCID et IdRef en une seule passe.

Met à jour :
  - source_persons.orcid, source_persons.idref

L'orchestrateur dépend du port `HarvestQueries`. Le point d'entrée CLI
est dans `interfaces/cli/pipeline/harvest_hal_identifiers.py`.
"""

import time
from typing import Any

import requests

from application.ports.harvest import HarvestQueries


def fetch_identifiers_batch(
    person_ids: list[int], logger: Any, *, hal_ref_author_api: str
) -> dict[int, dict]:
    """Interroge l'API HAL pour un lot de person_ids.

    Retourne {hal_person_id: {"orcid": ..., "idref": ...}} pour ceux qui en ont.
    """
    if not person_ids:
        return {}

    or_clause = " OR ".join(str(pid) for pid in person_ids)
    params = {
        "q": f"person_i:({or_clause})",
        "fl": "person_i,orcidId_s,idrefId_s",
        "rows": str(len(person_ids)),
        "wt": "json",
    }

    for attempt in range(3):
        try:
            resp = requests.get(hal_ref_author_api, params=params, timeout=30)
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

        orcid_raw = doc.get("orcidId_s")
        if orcid_raw:
            if isinstance(orcid_raw, list):
                orcid_raw = orcid_raw[0]
            orcid = orcid_raw.replace("https://orcid.org/", "").strip()
            if orcid:
                identifiers["orcid"] = orcid

        idref_raw = doc.get("idrefId_s")
        if idref_raw:
            if isinstance(idref_raw, list):
                idref_raw = idref_raw[0]
            idref = idref_raw.rsplit("/", 1)[-1] if "/" in idref_raw else idref_raw
            idref = idref.strip()
            if idref:
                identifiers["idref"] = idref

        if identifiers:
            results[pid] = identifiers

    return results


def run_harvest(
    cur: Any,
    conn: Any,
    queries: HarvestQueries,
    logger: Any,
    *,
    hal_ref_author_api: str,
    batch_size: int = 100,
    dry_run: bool = False,
    rate_delay: float = 0.1,
) -> None:
    try:
        rows = queries.fetch_hal_persons_missing_identifiers(cur)
        logger.info(f"{len(rows)} source_persons HAL à interroger (ORCID ou IdRef manquant)")

        if not rows:
            logger.info("Rien à faire.")
            return

        stats = {"orcid_found": 0, "idref_found": 0, "ha_updated": 0}

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            id_map = {row[1]: (row[0], row[2]) for row in batch}
            person_ids = list(id_map.keys())

            identifiers = fetch_identifiers_batch(
                person_ids, logger, hal_ref_author_api=hal_ref_author_api
            )

            if identifiers and not dry_run:
                for pid, ids in identifiers.items():
                    ha_id, _person_id = id_map[pid]

                    if "orcid" in ids:
                        if queries.fill_source_person_orcid_if_null(cur, ha_id, ids["orcid"]):
                            stats["ha_updated"] += 1
                        stats["orcid_found"] += 1

                    if "idref" in ids:
                        if queries.fill_source_person_idref_if_null(cur, ha_id, ids["idref"]):
                            stats["ha_updated"] += 1
                        stats["idref_found"] += 1

                conn.commit()
            elif identifiers:
                for _pid, ids in identifiers.items():
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

            time.sleep(rate_delay)

        if dry_run:
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
