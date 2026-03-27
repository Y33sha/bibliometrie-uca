#!/usr/bin/env python3
"""
migrate_person_links.py — Phase 2, étape 2.3
==============================================
Transfère les person_id de legacy_authors (ancienne table authors)
vers hal_authors et openalex_authors via identifiants communs.

Ordre de priorité :
  HAL      : idhal → orcid
  OpenAlex : openalex_id → orcid

Rapport final : mappings transférés, perdus, conflits.

Usage:
    python3 migrate_person_links.py
    python3 migrate_person_links.py --dry-run   # rapport sans écriture
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
            os.path.join(os.path.dirname(__file__), "migrate_person_links.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


def transfer_hal(cur, dry_run: bool) -> dict:
    """Transfère les person_id vers hal_authors."""
    stats = {"by_idhal": 0, "by_orcid": 0, "conflicts": 0}

    # 1. Par idhal
    cur.execute("""
        UPDATE hal_authors ha
        SET person_id = la.person_id
        FROM legacy_authors la
        WHERE la.person_id IS NOT NULL
          AND la.idhal IS NOT NULL
          AND ha.idhal = la.idhal
          AND ha.person_id IS NULL
    """)
    stats["by_idhal"] = cur.rowcount
    logger.info(f"  HAL par idhal : {stats['by_idhal']} transférés")

    # 2. Par orcid (seulement si pas déjà renseigné)
    cur.execute("""
        UPDATE hal_authors ha
        SET person_id = la.person_id
        FROM legacy_authors la
        WHERE ha.person_id IS NULL
          AND la.person_id IS NOT NULL
          AND la.orcid IS NOT NULL
          AND ha.orcid = la.orcid
    """)
    stats["by_orcid"] = cur.rowcount
    logger.info(f"  HAL par orcid : {stats['by_orcid']} transférés")

    # Conflits : hal_authors qui ont reçu un person_id différent de ce qu'on
    # aurait eu par un autre identifiant
    cur.execute("""
        SELECT ha.id, ha.full_name, ha.person_id AS assigned,
               la.person_id AS would_be, 'idhal→orcid conflict' AS reason
        FROM hal_authors ha
        JOIN legacy_authors la ON la.orcid = ha.orcid
        WHERE ha.person_id IS NOT NULL
          AND la.person_id IS NOT NULL
          AND ha.person_id != la.person_id
          AND la.orcid IS NOT NULL
    """)
    conflicts = cur.fetchall()
    stats["conflicts"] = len(conflicts)
    for c in conflicts[:10]:
        logger.warning(f"  Conflit HAL : {c[1]} (ha.id={c[0]}) → "
                       f"person_id={c[2]} vs {c[3]} ({c[4]})")
    if len(conflicts) > 10:
        logger.warning(f"  ... et {len(conflicts) - 10} autres conflits HAL")

    if dry_run:
        logger.info("  [DRY RUN] Rollback HAL")

    return stats


def transfer_openalex(cur, dry_run: bool) -> dict:
    """Transfère les person_id vers openalex_authors."""
    stats = {"by_openalex_id": 0, "by_orcid": 0, "conflicts": 0}

    # 1. Par openalex_id
    cur.execute("""
        UPDATE openalex_authors oa
        SET person_id = la.person_id
        FROM legacy_authors la
        WHERE la.person_id IS NOT NULL
          AND la.openalex_id IS NOT NULL
          AND oa.openalex_id = la.openalex_id
          AND oa.person_id IS NULL
    """)
    stats["by_openalex_id"] = cur.rowcount
    logger.info(f"  OpenAlex par openalex_id : {stats['by_openalex_id']} transférés")

    # 2. Par orcid
    cur.execute("""
        UPDATE openalex_authors oa
        SET person_id = la.person_id
        FROM legacy_authors la
        WHERE oa.person_id IS NULL
          AND la.person_id IS NOT NULL
          AND la.orcid IS NOT NULL
          AND oa.orcid = la.orcid
    """)
    stats["by_orcid"] = cur.rowcount
    logger.info(f"  OpenAlex par orcid : {stats['by_orcid']} transférés")

    # Conflits
    cur.execute("""
        SELECT oa.id, oa.full_name, oa.person_id AS assigned,
               la.person_id AS would_be, 'openalex_id→orcid conflict' AS reason
        FROM openalex_authors oa
        JOIN legacy_authors la ON la.orcid = oa.orcid
        WHERE oa.person_id IS NOT NULL
          AND la.person_id IS NOT NULL
          AND oa.person_id != la.person_id
          AND la.orcid IS NOT NULL
    """)
    conflicts = cur.fetchall()
    stats["conflicts"] = len(conflicts)
    for c in conflicts[:10]:
        logger.warning(f"  Conflit OpenAlex : {c[1]} (oa.id={c[0]}) → "
                       f"person_id={c[2]} vs {c[3]} ({c[4]})")
    if len(conflicts) > 10:
        logger.warning(f"  ... et {len(conflicts) - 10} autres conflits OpenAlex")

    if dry_run:
        logger.info("  [DRY RUN] Rollback OpenAlex")

    return stats


def report_lost(cur):
    """Identifie les legacy_authors avec person_id sans correspondance dans les nouvelles tables."""
    logger.info("\n--- Rapport person_id orphelins ---")

    cur.execute("""
        SELECT COUNT(DISTINCT person_id)
        FROM legacy_authors
        WHERE person_id IS NOT NULL
    """)
    total_legacy = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT person_id)
        FROM hal_authors
        WHERE person_id IS NOT NULL
    """)
    in_hal = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT person_id)
        FROM openalex_authors
        WHERE person_id IS NOT NULL
    """)
    in_oa = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT person_id) FROM (
            SELECT person_id FROM hal_authors WHERE person_id IS NOT NULL
            UNION
            SELECT person_id FROM openalex_authors WHERE person_id IS NOT NULL
        ) combined
    """)
    in_either = cur.fetchone()[0]

    lost = total_legacy - in_either

    logger.info(f"  Legacy authors avec person_id : {total_legacy}")
    logger.info(f"  Transférés vers hal_authors   : {in_hal}")
    logger.info(f"  Transférés vers openalex_auth : {in_oa}")
    logger.info(f"  Couverts (union)              : {in_either}")
    logger.info(f"  Perdus (aucune correspondance): {lost}")

    if lost > 0:
        # Détail des perdus
        cur.execute("""
            SELECT la.id, la.full_name, la.person_id, la.idhal, la.orcid, la.openalex_id
            FROM legacy_authors la
            WHERE la.person_id IS NOT NULL
              AND la.person_id NOT IN (
                  SELECT person_id FROM hal_authors WHERE person_id IS NOT NULL
                  UNION
                  SELECT person_id FROM openalex_authors WHERE person_id IS NOT NULL
              )
            ORDER BY la.full_name
            LIMIT 20
        """)
        rows = cur.fetchall()
        logger.info(f"  Exemples de perdus ({min(lost, 20)} affichés) :")
        for r in rows:
            logger.info(f"    id={r[0]} {r[1]} person_id={r[2]} "
                        f"idhal={r[3]} orcid={r[4]} openalex_id={r[5]}")

    # Stats par table cible
    for table in ["hal_authors", "openalex_authors"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE person_id IS NOT NULL")
        linked = cur.fetchone()[0]
        logger.info(f"  {table} : {linked}/{total} avec person_id")


def main():
    parser = argparse.ArgumentParser(
        description="Transfert des person_id legacy → nouvelles tables auteurs"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport sans écriture en base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        logger.info("=== Transfert des person_id ===")

        if args.dry_run:
            logger.info("[MODE DRY RUN]")

        logger.info("\n--- HAL ---")
        hal_stats = transfer_hal(cur, args.dry_run)

        logger.info("\n--- OpenAlex ---")
        oa_stats = transfer_openalex(cur, args.dry_run)

        if args.dry_run:
            conn.rollback()
            logger.info("\n[DRY RUN] Aucune modification enregistrée")
        else:
            conn.commit()

        report_lost(cur)

        # Résumé
        logger.info("\n=== Résumé ===")
        total_hal = hal_stats["by_idhal"] + hal_stats["by_orcid"]
        total_oa = oa_stats["by_openalex_id"] + oa_stats["by_orcid"]
        logger.info(f"HAL      : {total_hal} transférés "
                    f"(idhal={hal_stats['by_idhal']}, orcid={hal_stats['by_orcid']}, "
                    f"conflits={hal_stats['conflicts']})")
        logger.info(f"OpenAlex : {total_oa} transférés "
                    f"(openalex_id={oa_stats['by_openalex_id']}, orcid={oa_stats['by_orcid']}, "
                    f"conflits={oa_stats['conflicts']})")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
