#!/usr/bin/env python3
"""
migrate_authorships.py — Phase 2, étape 2.6
=============================================
Construit la table de vérité `authorships` en combinant :
  - hal_authorships (fan-out structure_ids[] → une ligne par structure)
  - openalex_authorships (idem)

Seuls les authorships avec person_id résolu sont inclus.
UNIQUE (publication_id, person_id, structure_id) avec ON CONFLICT
pour fusionner les sources.

Usage:
    python3 migrate_authorships.py
    python3 migrate_authorships.py --dry-run
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
            os.path.join(os.path.dirname(__file__), "migrate_authorships.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


def insert_from_hal(cur) -> dict:
    """Insère les authorships depuis HAL avec fan-out des structure_ids."""
    stats = {"with_structures": 0, "without_structures": 0, "skipped_no_person": 0}

    # Compter les skippés (pas de person_id)
    cur.execute("""
        SELECT COUNT(*)
        FROM hal_authorships has_
        JOIN hal_authors ha ON ha.id = has_.hal_author_id
        WHERE ha.person_id IS NULL
    """)
    stats["skipped_no_person"] = cur.fetchone()[0]

    # 1. Authorships UCA avec structures → fan-out unnest(structure_ids)
    cur.execute("""
        INSERT INTO authorships
            (publication_id, person_id, structure_id, author_position, is_uca, source_hal)
        SELECT
            hd.publication_id,
            ha.person_id,
            unnest(has_.structure_ids),
            has_.author_position,
            TRUE,
            TRUE
        FROM hal_authorships has_
        JOIN hal_documents hd ON hd.id = has_.hal_document_id
        JOIN hal_authors ha ON ha.id = has_.hal_author_id
        WHERE hd.publication_id IS NOT NULL
          AND ha.person_id IS NOT NULL
          AND has_.is_uca = TRUE
          AND has_.structure_ids IS NOT NULL
          AND array_length(has_.structure_ids, 1) > 0
        ON CONFLICT (publication_id, person_id, structure_id) DO UPDATE SET
            source_hal = TRUE,
            is_uca = TRUE,
            author_position = COALESCE(authorships.author_position, EXCLUDED.author_position)
    """)
    stats["with_structures"] = cur.rowcount
    logger.info(f"  HAL UCA avec structures : {stats['with_structures']}")

    # 2. Authorships sans structures (non-UCA ou UCA sans structure résolue)
    #    → structure_id = NULL
    cur.execute("""
        INSERT INTO authorships
            (publication_id, person_id, structure_id, author_position, is_uca, source_hal)
        SELECT
            hd.publication_id,
            ha.person_id,
            NULL,
            has_.author_position,
            has_.is_uca,
            TRUE
        FROM hal_authorships has_
        JOIN hal_documents hd ON hd.id = has_.hal_document_id
        JOIN hal_authors ha ON ha.id = has_.hal_author_id
        WHERE hd.publication_id IS NOT NULL
          AND ha.person_id IS NOT NULL
          AND (has_.structure_ids IS NULL OR array_length(has_.structure_ids, 1) IS NULL)
        ON CONFLICT (publication_id, person_id, structure_id) DO UPDATE SET
            source_hal = TRUE,
            author_position = COALESCE(authorships.author_position, EXCLUDED.author_position)
    """)
    stats["without_structures"] = cur.rowcount
    logger.info(f"  HAL sans structures : {stats['without_structures']}")

    return stats


def insert_from_openalex(cur) -> dict:
    """Insère les authorships depuis OpenAlex avec fan-out des structure_ids."""
    stats = {"with_structures": 0, "without_structures": 0, "skipped_no_person": 0}

    cur.execute("""
        SELECT COUNT(*)
        FROM openalex_authorships oas
        JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
        WHERE oa.person_id IS NULL
    """)
    stats["skipped_no_person"] = cur.fetchone()[0]

    # 1. UCA avec structures → fan-out
    cur.execute("""
        INSERT INTO authorships
            (publication_id, person_id, structure_id, author_position, is_uca, source_openalex)
        SELECT
            od.publication_id,
            oa.person_id,
            unnest(oas.structure_ids),
            oas.author_position,
            TRUE,
            TRUE
        FROM openalex_authorships oas
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
        WHERE od.publication_id IS NOT NULL
          AND oa.person_id IS NOT NULL
          AND oas.is_uca = TRUE
          AND oas.structure_ids IS NOT NULL
          AND array_length(oas.structure_ids, 1) > 0
        ON CONFLICT (publication_id, person_id, structure_id) DO UPDATE SET
            source_openalex = TRUE,
            is_uca = TRUE,
            author_position = COALESCE(authorships.author_position, EXCLUDED.author_position)
    """)
    stats["with_structures"] = cur.rowcount
    logger.info(f"  OpenAlex UCA avec structures : {stats['with_structures']}")

    # 2. Sans structures
    cur.execute("""
        INSERT INTO authorships
            (publication_id, person_id, structure_id, author_position, is_uca, source_openalex)
        SELECT
            od.publication_id,
            oa.person_id,
            NULL,
            oas.author_position,
            oas.is_uca,
            TRUE
        FROM openalex_authorships oas
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
        WHERE od.publication_id IS NOT NULL
          AND oa.person_id IS NOT NULL
          AND (oas.structure_ids IS NULL OR array_length(oas.structure_ids, 1) IS NULL)
        ON CONFLICT (publication_id, person_id, structure_id) DO UPDATE SET
            source_openalex = TRUE,
            author_position = COALESCE(authorships.author_position, EXCLUDED.author_position)
    """)
    stats["without_structures"] = cur.rowcount
    logger.info(f"  OpenAlex sans structures : {stats['without_structures']}")

    return stats


def report(cur):
    logger.info("\n--- Rapport authorships (vérité) ---")

    cur.execute("SELECT COUNT(*) FROM authorships")
    total = cur.fetchone()[0]
    logger.info(f"  Total : {total}")

    cur.execute("SELECT COUNT(*) FROM authorships WHERE is_uca = TRUE")
    uca = cur.fetchone()[0]
    logger.info(f"  UCA : {uca}")

    cur.execute("SELECT COUNT(*) FROM authorships WHERE source_hal = TRUE AND source_openalex = TRUE")
    both = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM authorships WHERE source_hal = TRUE AND (source_openalex IS NULL OR source_openalex = FALSE)")
    hal_only = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM authorships WHERE source_openalex = TRUE AND (source_hal IS NULL OR source_hal = FALSE)")
    oa_only = cur.fetchone()[0]
    logger.info(f"  HAL seul : {hal_only}")
    logger.info(f"  OpenAlex seul : {oa_only}")
    logger.info(f"  Les deux : {both}")

    cur.execute("SELECT COUNT(DISTINCT person_id) FROM authorships")
    persons = cur.fetchone()[0]
    logger.info(f"  Personnes distinctes : {persons}")

    cur.execute("SELECT COUNT(DISTINCT publication_id) FROM authorships")
    pubs = cur.fetchone()[0]
    logger.info(f"  Publications distinctes : {pubs}")

    cur.execute("""
        SELECT COUNT(DISTINCT structure_id)
        FROM authorships
        WHERE structure_id IS NOT NULL
    """)
    structs = cur.fetchone()[0]
    logger.info(f"  Structures distinctes : {structs}")


def main():
    parser = argparse.ArgumentParser(
        description="Construction de la table de vérité authorships"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport sans écriture en base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        logger.info("=== Construction authorships (vérité) ===")
        if args.dry_run:
            logger.info("[MODE DRY RUN]")

        logger.info("\n--- HAL ---")
        hal_stats = insert_from_hal(cur)

        logger.info("\n--- OpenAlex ---")
        oa_stats = insert_from_openalex(cur)

        if args.dry_run:
            # Report avant rollback
            report(cur)
            conn.rollback()
            logger.info("\n[DRY RUN] Aucune modification enregistrée")
        else:
            conn.commit()
            report(cur)

        # Résumé
        logger.info(f"\n=== Résumé ===")
        logger.info(f"HAL : {hal_stats['with_structures']} + {hal_stats['without_structures']} "
                     f"insérés, {hal_stats['skipped_no_person']} skippés (pas de person_id)")
        logger.info(f"OpenAlex : {oa_stats['with_structures']} + {oa_stats['without_structures']} "
                     f"insérés, {oa_stats['skipped_no_person']} skippés (pas de person_id)")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
