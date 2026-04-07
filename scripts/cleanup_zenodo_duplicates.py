"""
Nettoyage rétroactif des doublons Zenodo (concept DOI vs version DOI).

Zenodo attribue à chaque dépôt un concept DOI (parent, zenodo.N) et un
version DOI (zenodo.N+1). Le concept DOI redirige vers la dernière version.
Quand les deux sont importés, on a un doublon.

Stratégie : pour chaque paire de publications Zenodo ayant le même titre
normalisé et des numéros consécutifs (N, N+1), fusionner N (concept) dans
N+1 (version). Pas d'appel API Zenodo nécessaire.

Usage:
    python scripts/cleanup_zenodo_duplicates.py              # dry-run
    python scripts/cleanup_zenodo_duplicates.py --apply       # appliquer
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.log import setup_logger
from services.publications import merge_publications

logger = setup_logger("cleanup_zenodo", os.path.join(os.path.dirname(__file__), "../processing/logs"))


def main():
    parser = argparse.ArgumentParser(description="Nettoyage doublons Zenodo")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # Trouver les paires concept/version : même titre, numéros N et N+1
    cur.execute("""
        WITH zenodo_pubs AS (
            SELECT id, doi,
                   (regexp_match(doi, 'zenodo\.(\d+)'))[1]::bigint AS zid,
                   title_normalized
            FROM publications
            WHERE doi ~* 'zenodo\.\d+'
        )
        SELECT concept.id AS concept_pub_id, concept.doi AS concept_doi,
               version.id AS version_pub_id, version.doi AS version_doi,
               concept.title_normalized
        FROM zenodo_pubs concept
        JOIN zenodo_pubs version
          ON version.title_normalized = concept.title_normalized
         AND version.zid = concept.zid + 1
        ORDER BY concept.title_normalized
    """)
    pairs = cur.fetchall()
    print(f"{len(pairs)} paires concept→version trouvées\n")

    merged = 0
    errors = 0

    for concept_pub_id, concept_doi, version_pub_id, version_doi, title_norm in pairs:
        label = f"pub {concept_pub_id} ({concept_doi}) → {version_pub_id} ({version_doi})"
        print(f"  {'MERGE' if args.apply else 'DRY'} {label}")

        if args.apply:
            try:
                merge_publications(cur, version_pub_id, concept_pub_id)
                merged += 1
            except Exception as e:
                logger.error(f"Erreur merge {label}: {e}")
                conn.rollback()
                errors += 1

    if args.apply:
        conn.commit()

    print(f"\nRésumé :")
    print(f"  Paires traitées : {len(pairs)}")
    if args.apply:
        print(f"  Fusionnées : {merged}")
        print(f"  Erreurs : {errors}")
    else:
        print(f"\nDry-run — ajouter --apply pour appliquer.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
