"""Récupère les IdRef depuis l'API HAL ref/author pour les hal_authors avec idhal.

Pour chaque hal_author ayant un idhal et un person_id, interroge l'API HAL
et insère l'IdRef dans person_identifiers.

Usage:
    python processing/harvest_hal_idrefs.py [--dry-run]
"""
import argparse
import sys
import time
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, ".")
from config.settings import DB
from services.persons import add_identifier

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
        r = requests.get(HAL_AUTHOR_API, params={
            "q": q,
            "fl": "person_i,idrefId_s",
            "rows": 1,
        }, timeout=10)
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        if docs and docs[0].get("idrefId_s"):
            url = docs[0]["idrefId_s"][0]
            return url.rsplit("/", 1)[-1] if "/" in url else url
    except Exception as e:
        print(f"  Erreur: {e}")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Hal authors avec hal_person_id + person_id, sans IdRef déjà connu
    cur.execute("""
        SELECT ha.id AS ha_id, ha.hal_person_id, ha.idhal, ha.person_id, ha.full_name
        FROM hal_authors ha
        WHERE ha.hal_person_id IS NOT NULL
          AND ha.person_id IS NOT NULL
          AND ha.idref IS NULL
        ORDER BY ha.person_id
    """)
    authors = cur.fetchall()
    print(f"{len(authors)} auteurs HAL à interroger")

    found = 0
    for i, a in enumerate(authors):
        idref = fetch_idref(hal_person_id=a["hal_person_id"], idhal=a["idhal"])
        if idref:
            found += 1
            if not args.dry_run:
                # Stocker dans hal_authors
                cur.execute("UPDATE hal_authors SET idref = %s WHERE id = %s",
                            (idref, a["ha_id"]))
                # Stocker dans person_identifiers
                add_identifier(cur, a["person_id"], "idref", idref, source="hal")
            print(f"  {a['full_name']}: {idref}")

        if (i + 1) % 100 == 0:
            if not args.dry_run:
                conn.commit()
            print(f"  {i+1}/{len(authors)} traités, {found} IdRef trouvés")
            time.sleep(0.5)  # politesse API

    if not args.dry_run:
        conn.commit()

    print(f"\nTerminé: {found} IdRef trouvés sur {len(authors)} auteurs")
    conn.close()


if __name__ == "__main__":
    main()
