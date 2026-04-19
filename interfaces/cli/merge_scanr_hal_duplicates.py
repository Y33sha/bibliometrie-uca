"""
Fusion rétrospective des doublons ScanR↔HAL.

Quand un scanr_document porte un hal_id qui correspond à un hal_document
existant, mais que les deux pointent vers des publications différentes,
on fusionne la publication ScanR dans la publication HAL (la source HAL
étant considérée comme référence).

Usage:
    python scripts/merge_scanr_hal_duplicates.py              # dry-run
    python scripts/merge_scanr_hal_duplicates.py --apply       # appliquer
"""

import argparse
import os
from typing import Any

from psycopg2.extras import RealDictCursor

from application.publications import merge_publications
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

logger = setup_logger(
    "merge_scanr_hal_dups", os.path.join(os.path.dirname(__file__), "../processing/logs")
)


def find_duplicates(cur: Any) -> list[dict]:
    """Trouve les paires (scanr_pub, hal_pub) à fusionner.

    Critères :
    - source_publications (scanr) external_ids->>'hal' correspond à un source_publications (hal) source_id
    - Les deux documents ont un publication_id non NULL
    - Les publication_id sont différents
    """
    cur.execute("""
        SELECT sd.id AS scanr_doc_id,
               sd.source_id AS scanr_id,
               sd.external_ids->>'hal' AS hal_id,
               sd.publication_id AS scanr_pub_id,
               hd.publication_id AS hal_pub_id,
               sd.title
        FROM source_publications sd
        JOIN source_publications hd ON hd.source = 'hal' AND hd.source_id = sd.external_ids->>'hal'
        WHERE sd.source = 'scanr'
          AND sd.external_ids->>'hal' IS NOT NULL
          AND sd.publication_id IS NOT NULL
          AND hd.publication_id IS NOT NULL
          AND sd.publication_id != hd.publication_id
        ORDER BY sd.id
    """)
    return cur.fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fusionne les doublons ScanR↔HAL par identifiant HAL"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Appliquer les fusions (sans ce flag : dry-run)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Taille du commit batch (défaut: 500)"
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    duplicates = find_duplicates(cur)
    logger.info(f"Doublons ScanR↔HAL trouvés : {len(duplicates)}")

    if not duplicates:
        logger.info("Rien à faire.")
        conn.close()
        return

    if not args.apply:
        logger.info("[DRY RUN] Exemples de fusions :")
        for dup in duplicates[:20]:
            logger.info(
                f"  {dup['scanr_id']} (hal_id={dup['hal_id']}) : "
                f"pub {dup['scanr_pub_id']} → {dup['hal_pub_id']}  "
                f"({dup['title'][:60]}...)"
            )
        if len(duplicates) > 20:
            logger.info(f"  ... et {len(duplicates) - 20} autres")
        conn.close()
        return

    merged = 0
    skipped = 0
    errors = 0
    # Suivre les publications supprimées → leur cible de fusion
    merged_into: dict[int, int] = {}  # {source_id: target_id}

    def resolve(pub_id: Any) -> Any:
        """Suit la chaîne de fusions pour trouver la publication vivante."""
        visited = set()
        while pub_id in merged_into:
            if pub_id in visited:
                break  # Cycle (ne devrait pas arriver)
            visited.add(pub_id)
            pub_id = merged_into[pub_id]
        return pub_id

    for dup in duplicates:
        scanr_pub_id = resolve(dup["scanr_pub_id"])
        hal_pub_id = resolve(dup["hal_pub_id"])

        if scanr_pub_id == hal_pub_id:
            skipped += 1
            continue  # Déjà résolu par une fusion précédente

        try:
            merge_publications(cur, target_id=hal_pub_id, source_id=scanr_pub_id)
            merged_into[scanr_pub_id] = hal_pub_id
            merged += 1

            if merged % args.batch_size == 0:
                conn.commit()
                logger.info(f"  {merged}/{len(duplicates)} fusionnés")

        except Exception as e:
            logger.error(
                f"  Erreur fusion pub {scanr_pub_id} → {hal_pub_id} "
                f"(scanr_id={dup['scanr_id']}): {e}"
            )
            conn.rollback()
            errors += 1

    conn.commit()
    logger.info(f"Terminé : {merged} fusions, {skipped} déjà résolus, {errors} erreurs")
    conn.close()


if __name__ == "__main__":
    main()
