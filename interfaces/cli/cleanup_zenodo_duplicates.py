"""
Nettoyage rétroactif des doublons Zenodo (concept DOI vs version DOI).

Deux passes :
1. Paires consécutives (N, N+1) — sans appel API, rapide
2. Paires non consécutives — résolution via API Zenodo avec backoff

Usage:
    python scripts/cleanup_zenodo_duplicates.py              # dry-run
    python scripts/cleanup_zenodo_duplicates.py --apply       # appliquer
"""

import argparse
import os
import time
from typing import Any

from application.publications import merge_publications
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger
from infrastructure.zenodo import resolve_zenodo_doi

logger = setup_logger(
    "cleanup_zenodo", os.path.join(os.path.dirname(__file__), "../processing/logs")
)

# Pause entre chaque appel API (secondes)
API_POLITE_DELAY = 1.5


def find_consecutive_pairs(cur: Any) -> Any:
    """Passe 1 : paires N/N+1 (sans API)."""
    cur.execute("""
        WITH zenodo_pubs AS (
            SELECT id, doi,
                   (regexp_match(doi, 'zenodo\\.(\\d+)'))[1]::bigint AS zid,
                   title_normalized
            FROM publications
            WHERE doi ~* 'zenodo\\.\\d+'
        )
        SELECT concept.id, concept.doi, version.id, version.doi,
               concept.title_normalized
        FROM zenodo_pubs concept
        JOIN zenodo_pubs version
          ON version.title_normalized = concept.title_normalized
         AND version.zid = concept.zid + 1
        ORDER BY concept.title_normalized
    """)
    return cur.fetchall()


def find_remaining_groups(cur: Any) -> Any:
    """Passe 2 : groupes de doublons Zenodo restants (non consécutifs)."""
    cur.execute("""
        WITH zenodo_pubs AS (
            SELECT id, doi, title_normalized
            FROM publications
            WHERE doi ~* 'zenodo\\.\\d+'
        )
        SELECT title_normalized, array_agg(id ORDER BY id) AS pub_ids,
               array_agg(doi ORDER BY id) AS dois
        FROM zenodo_pubs
        GROUP BY title_normalized
        HAVING count(*) > 1
    """)
    return cur.fetchall()


def do_merge(
    cur: Any,
    conn: Any,
    target_id: Any,
    target_doi: Any,
    source_id: Any,
    source_doi: Any,
    apply: Any,
) -> Any:
    """Fusionne source dans target + supprime l'openalex_document source."""
    label = f"pub {source_id} ({source_doi}) → {target_id} ({target_doi})"
    print(f"  {'MERGE' if apply else 'DRY'} {label}")

    if not apply:
        return True

    try:
        merge_publications(cur, target_id, source_id)
        # Supprimer le source_document du concept DOI (maintenant rattaché à target)
        cur.execute(
            """
            DELETE FROM source_publications
            WHERE source = 'openalex' AND publication_id = %s AND lower(doi) = lower(%s)
        """,
            (target_id, source_doi),
        )
        return True
    except Exception as e:
        logger.error(f"Erreur merge {label}: {e}")
        conn.rollback()
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Nettoyage doublons Zenodo")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    merged = 0
    errors = 0

    # --- Passe 1 : paires consécutives (N, N+1) ---
    pairs = find_consecutive_pairs(cur)
    if pairs:
        print(f"=== Passe 1 : {len(pairs)} paires consécutives ===\n")
        for concept_id, concept_doi, version_id, version_doi, _ in pairs:
            if do_merge(cur, conn, version_id, version_doi, concept_id, concept_doi, args.apply):
                merged += 1
            else:
                errors += 1
        if args.apply:
            conn.commit()

    # --- Passe 2 : doublons restants (via API) ---
    groups = find_remaining_groups(cur)
    if groups:
        print(f"\n=== Passe 2 : {len(groups)} groupes restants (appel API) ===\n")
        for title_norm, pub_ids, dois in groups:
            # Résoudre chaque DOI via l'API
            version_ids = []
            concept_ids = []

            for pub_id, doi in zip(pub_ids, dois, strict=True):
                time.sleep(API_POLITE_DELAY)
                version_doi = resolve_zenodo_doi(doi)
                if version_doi is None:
                    version_ids.append((pub_id, doi))
                else:
                    concept_ids.append((pub_id, doi))

            if not version_ids or not concept_ids:
                print(f"  SKIP {title_norm[:60]} — impossible de distinguer concept/version")
                continue

            target_id, target_doi = version_ids[0]
            sources = concept_ids + [(pid, d) for pid, d in version_ids[1:]]

            for source_id, source_doi in sources:
                if do_merge(cur, conn, target_id, target_doi, source_id, source_doi, args.apply):
                    merged += 1
                else:
                    errors += 1

        if args.apply:
            conn.commit()

    # --- Résumé ---
    print("\nRésumé :")
    print(f"  Fusionnées : {merged}")
    print(f"  Erreurs : {errors}")
    if not args.apply and merged:
        print("\nDry-run — ajouter --apply pour appliquer.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
