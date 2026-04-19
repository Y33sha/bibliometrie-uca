"""Récupère les IdRef depuis l'API HAL ref/author pour les source_persons HAL avec idhal.

Pour chaque hal_author ayant un idhal et un person_id, interroge l'API HAL
et insère l'IdRef dans person_identifiers.

Usage:
    python processing/harvest_hal_idrefs.py [--dry-run]
"""

import argparse
import os
import time
from typing import Any

import requests

from application.persons import add_identifier
from infrastructure.api_limits import HAL_DELAY
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.harvest import (
    fetch_hal_persons_missing_idref,
    update_source_person_idref,
)
from infrastructure.log import setup_logger

logger = setup_logger("harvest_hal_idrefs", os.path.join(os.path.dirname(__file__), "logs"))

HAL_AUTHOR_API = "https://api.archives-ouvertes.fr/ref/author/"


def fetch_idref(hal_person_id: int = None, idhal: str = None) -> str | None:
    """Interroge l'API HAL pour récupérer l'IdRef d'un auteur."""
    try:
        if idhal:
            q = f"idHal_s:{idhal}"
        elif hal_person_id:
            q = f"person_i:{hal_person_id}"
        else:
            return None
        r = requests.get(
            HAL_AUTHOR_API,
            params={
                "q": q,
                "fl": "person_i,idrefId_s",
                "rows": "1",
            },
            timeout=10,
        )
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        if docs and docs[0].get("idrefId_s"):
            url = docs[0]["idrefId_s"][0]
            return url.rsplit("/", 1)[-1] if "/" in url else url
    except Exception as e:
        logger.warning(f"Erreur: {e}")
    return None


def main() -> Any:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    authors = fetch_hal_persons_missing_idref(cur)
    logger.info(f"{len(authors)} auteurs HAL à interroger")

    found = 0
    for i, a in enumerate(authors):
        idref = fetch_idref(hal_person_id=a["hal_person_id"], idhal=a["idhal"])
        if idref:
            found += 1
            if not args.dry_run:
                update_source_person_idref(cur, a["ha_id"], idref)
                add_identifier(cur, a["person_id"], "idref", idref, source="hal")
            logger.info(f"  {a['full_name']}: {idref}")

        if (i + 1) % 100 == 0:
            if not args.dry_run:
                conn.commit()
            logger.info(f"  {i + 1}/{len(authors)} traités, {found} IdRef trouvés")
            time.sleep(HAL_DELAY)

    if not args.dry_run:
        conn.commit()

    logger.info(f"Terminé: {found} IdRef trouvés sur {len(authors)} auteurs")
    conn.close()


if __name__ == "__main__":
    main()
