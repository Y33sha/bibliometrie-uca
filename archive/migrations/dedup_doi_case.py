"""
Déduplique les publications ayant le même DOI à la casse près.

Les DOI sont insensibles à la casse (spec DOI), mais stockés tels quels
depuis les différentes sources. Ce script fusionne les doublons et
normalise tous les DOI en minuscules.

Priorité des métadonnées : OpenAlex > WoS > HAL.

Usage:
    python processing/dedup_doi_case.py              # exécuter
    python processing/dedup_doi_case.py --dry-run    # dry-run
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "dedup_doi_case.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


def source_priority(cur, pub_id):
    """Retourne un score de priorité (plus élevé = meilleur).
    OpenAlex=3, WoS=2, HAL=1, rien=0."""
    score = 0
    cur.execute("SELECT 1 FROM openalex_documents WHERE publication_id = %s LIMIT 1", (pub_id,))
    if cur.fetchone():
        score = max(score, 3)
    cur.execute("SELECT 1 FROM wos_documents WHERE publication_id = %s LIMIT 1", (pub_id,))
    if cur.fetchone():
        score = max(score, 2)
    cur.execute("SELECT 1 FROM hal_documents WHERE publication_id = %s LIMIT 1", (pub_id,))
    if cur.fetchone():
        score = max(score, 1)
    return score


def find_doi_duplicates(cur):
    """Trouve les groupes de publications partageant le même DOI (insensible à la casse)."""
    cur.execute("""
        SELECT LOWER(doi) AS doi_lower, array_agg(id ORDER BY id) AS pub_ids
        FROM publications
        WHERE doi IS NOT NULL
        GROUP BY LOWER(doi)
        HAVING COUNT(*) > 1
        ORDER BY doi_lower
    """)
    return cur.fetchall()


def merge_publication(cur, target_id, source_id):
    """Fusionne source dans target (même logique que merge_hal_openalex_pubs.py)."""
    cur.execute("SAVEPOINT merge_doi")
    try:
        # 1. Réassigner les documents source
        for tbl in ("hal_documents", "openalex_documents", "wos_documents"):
            cur.execute(f"UPDATE {tbl} SET publication_id = %s WHERE publication_id = %s",
                        (target_id, source_id))

        # 2. Supprimer les authorships en doublon
        cur.execute("""
            DELETE FROM authorships
            WHERE publication_id = %s
              AND person_id IN (
                  SELECT person_id FROM authorships WHERE publication_id = %s
              )
        """, (source_id, target_id))

        # 3. Réassigner les authorships restants
        cur.execute("UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
                    (target_id, source_id))

        # 4. Enrichir les métadonnées (source → target, coalesce)
        cur.execute("""
            UPDATE publications dest SET
                doi = LOWER(COALESCE(dest.doi, src.doi)),
                journal_id = COALESCE(dest.journal_id, src.journal_id),
                oa_status = CASE
                    WHEN dest.oa_status = 'diamond' THEN 'diamond'
                    WHEN src.oa_status = 'diamond' THEN 'diamond'
                    WHEN dest.oa_status IN ('unknown', 'closed') AND src.oa_status NOT IN ('unknown', 'closed')
                    THEN src.oa_status ELSE dest.oa_status END,
                language = COALESCE(dest.language, src.language),
                container_title = COALESCE(dest.container_title, src.container_title),
                updated_at = now()
            FROM publications src
            WHERE dest.id = %s AND src.id = %s
        """, (target_id, source_id))

        # 5. Nettoyer distinct_publications
        cur.execute("""
            DELETE FROM distinct_publications
            WHERE pub_id_a = %s OR pub_id_b = %s OR pub_id_a = %s OR pub_id_b = %s
        """, (source_id, source_id, source_id, source_id))

        # 6. Supprimer la publication source
        cur.execute("DELETE FROM publications WHERE id = %s", (source_id,))

        cur.execute("RELEASE SAVEPOINT merge_doi")
        return True
    except Exception as e:
        cur.execute("ROLLBACK TO SAVEPOINT merge_doi")
        logger.warning(f"  Échec fusion #{source_id} → #{target_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Déduplique les DOI insensible à la casse")
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)

        groups = find_doi_duplicates(cur)
        logger.info(f"{len(groups)} DOI avec doublons de casse")

        if not groups:
            logger.info("Rien à faire.")
            return

        merged = 0
        errors = 0

        for row in groups:
            doi_lower = row["doi_lower"]
            pub_ids = row["pub_ids"]

            # Calculer la priorité de chaque publication
            scored = [(pid, source_priority(cur, pid)) for pid in pub_ids]
            # Trier par priorité décroissante, puis par id croissant
            scored.sort(key=lambda x: (-x[1], x[0]))
            target_id = scored[0][0]

            for source_id, _ in scored[1:]:
                if args.dry_run:
                    logger.info(f"  [DRY] {doi_lower}: #{source_id} → #{target_id}")
                else:
                    if merge_publication(cur, target_id, source_id):
                        logger.info(f"  Fusionné {doi_lower}: #{source_id} → #{target_id}")
                        merged += 1
                    else:
                        errors += 1

            if not args.dry_run and merged % 200 == 0 and merged > 0:
                conn.commit()

        if not args.dry_run:
            # Normaliser les DOI en minuscules un par un
            # (certains peuvent encore entrer en conflit si un DOI lower existe déjà)
            cur.execute("""
                SELECT id, doi FROM publications
                WHERE doi IS NOT NULL AND doi <> LOWER(doi)
                ORDER BY id
            """)
            to_normalize = cur.fetchall()
            normalized = 0
            extra_merges = 0

            for row in to_normalize:
                pid = row["id"]
                doi_lower = row["doi"].lower()

                # Vérifier si une autre publication a déjà ce DOI en lower
                cur.execute(
                    "SELECT id FROM publications WHERE doi = %s AND id <> %s",
                    (doi_lower, pid)
                )
                conflict = cur.fetchone()

                if conflict:
                    # Fusionner : garder celle qui a déjà le bon DOI
                    target = conflict["id"]
                    if merge_publication(cur, target, pid):
                        logger.info(f"  Fusion post-normalisation : #{pid} → #{target} ({doi_lower})")
                        extra_merges += 1
                        merged += 1
                    else:
                        errors += 1
                else:
                    cur.execute(
                        "UPDATE publications SET doi = %s WHERE id = %s",
                        (doi_lower, pid)
                    )
                    normalized += 1

            if extra_merges:
                logger.info(f"  {extra_merges} fusions supplémentaires lors de la normalisation")
            logger.info(f"  {normalized} DOI normalisés en minuscules")

            conn.commit()

        logger.info(f"\n=== Résultat ===")
        logger.info(f"  Groupes de doublons : {len(groups)}")
        logger.info(f"  Publications fusionnées : {merged}")
        logger.info(f"  Erreurs : {errors}")
        if args.dry_run:
            logger.info("  (dry-run)")
            conn.rollback()

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
