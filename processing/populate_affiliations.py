"""
Résolution des affiliations sur les authorships sources.

Peuple in_perimeter et structure_ids sur source_authorships
en utilisant les périmètres configurés (utils/uca_perimeter.py).

Deux périmètres :
  - restreint : UCA + labos tutellés → sert pour in_perimeter
  - large : restreint + partenaires (CHU, INP…) → sert pour structure_ids

Usage:
    python populate_affiliations.py          # exécution complète
    python populate_affiliations.py --stats  # afficher les compteurs sans modifier
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.uca_perimeter import get_uca_structure_ids, get_uca_structure_ids_wide
from utils.log import setup_logger

logger = setup_logger("populate_affiliations", os.path.join(os.path.dirname(__file__), "logs"))


def step1_hal_structure_ids(cur):
    """Étape 1 : HAL — mapper source_struct_ids → structure_ids (réels)."""
    cur.execute("""
        UPDATE source_authorships sa
        SET structure_ids = mapped.struct_ids
        FROM (
            SELECT sa2.id,
                   array_agg(DISTINCT ss.structure_id) AS struct_ids
            FROM source_authorships sa2,
                 LATERAL unnest(sa2.source_struct_ids) AS ssid(val)
            JOIN source_structures ss ON ss.id = ssid.val
            WHERE sa2.source = 'hal'
              AND ss.structure_id IS NOT NULL
            GROUP BY sa2.id
        ) mapped
        WHERE sa.id = mapped.id
    """)
    logger.info(f"Étape 1 — HAL structure_ids mappés : {cur.rowcount} authorships")


def step2_hal_in_perimeter(cur, uca_ids):
    """Étape 2 : HAL — recalculer in_perimeter."""
    cur.execute("UPDATE source_authorships SET in_perimeter = FALSE WHERE source = 'hal'")
    logger.info(f"Étape 2 — HAL in_perimeter reset : {cur.rowcount} authorships")

    cur.execute("""
        UPDATE source_authorships sa
        SET in_perimeter = TRUE
        WHERE sa.source = 'hal'
          AND sa.structure_ids IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM unnest(sa.structure_ids) AS sid
            WHERE sid = ANY(%s)
          )
    """, (list(uca_ids),))
    logger.info(f"Étape 2 — HAL in_perimeter = TRUE : {cur.rowcount} authorships")


def step3_openalex(cur, uca_ids, uca_wide_ids):
    """Étape 3 : OpenAlex — calculer in_perimeter + structure_ids."""
    cur.execute("UPDATE source_authorships SET in_perimeter = FALSE, structure_ids = NULL WHERE source = 'openalex'")
    logger.info(f"Étape 3 — OA reset : {cur.rowcount} authorships")

    # in_perimeter via périmètre restreint
    cur.execute("""
        UPDATE source_authorships sa
        SET in_perimeter = TRUE
        WHERE sa.source = 'openalex'
          AND EXISTS (
            SELECT 1
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            WHERE saa.source_authorship_id = sa.id
              AND ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
        )
    """, (list(uca_ids),))
    logger.info(f"Étape 3 — OA in_perimeter = TRUE : {cur.rowcount} authorships")

    # structure_ids via périmètre large
    cur.execute("""
        WITH oa_structs AS (
            SELECT saa.source_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            WHERE sa2.source = 'openalex'
              AND ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET structure_ids = os.struct_ids
        FROM oa_structs os
        WHERE sa.source = 'openalex'
          AND sa.id = os.source_authorship_id
    """, (list(uca_wide_ids),))
    logger.info(f"Étape 3 — OA structure_ids : {cur.rowcount} authorships")


def step3b_wos(cur, uca_ids, uca_wide_ids):
    """Étape 3b : WoS — calculer in_perimeter + structure_ids."""
    cur.execute("UPDATE source_authorships SET in_perimeter = FALSE, structure_ids = NULL WHERE source = 'wos'")
    logger.info(f"Étape 3b — WoS reset : {cur.rowcount} authorships")

    # in_perimeter via périmètre restreint
    cur.execute("""
        UPDATE source_authorships sa
        SET in_perimeter = TRUE
        WHERE sa.source = 'wos'
          AND EXISTS (
            SELECT 1
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            WHERE saa.source_authorship_id = sa.id
              AND ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
        )
    """, (list(uca_ids),))
    logger.info(f"Étape 3b — WoS in_perimeter = TRUE : {cur.rowcount} authorships")

    # structure_ids via périmètre large
    cur.execute("""
        WITH wos_structs AS (
            SELECT saa.source_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            WHERE sa2.source = 'wos'
              AND ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET structure_ids = ws.struct_ids
        FROM wos_structs ws
        WHERE sa.source = 'wos'
          AND sa.id = ws.source_authorship_id
    """, (list(uca_wide_ids),))
    logger.info(f"Étape 3b — WoS structure_ids : {cur.rowcount} authorships")


def step3c_scanr(cur, uca_ids, uca_wide_ids):
    """Étape 3c : ScanR — calculer in_perimeter + structure_ids."""
    cur.execute("UPDATE source_authorships SET in_perimeter = FALSE, structure_ids = NULL WHERE source = 'scanr'")
    logger.info(f"Étape 3c — ScanR reset : {cur.rowcount} authorships")

    # in_perimeter via périmètre restreint
    cur.execute("""
        UPDATE source_authorships sa
        SET in_perimeter = TRUE
        WHERE sa.source = 'scanr'
          AND EXISTS (
            SELECT 1
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            WHERE saa.source_authorship_id = sa.id
              AND ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
        )
    """, (list(uca_ids),))
    logger.info(f"Étape 3c — ScanR in_perimeter = TRUE : {cur.rowcount} authorships")

    # structure_ids via périmètre large
    cur.execute("""
        WITH scanr_structs AS (
            SELECT saa.source_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            WHERE sa2.source = 'scanr'
              AND ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET structure_ids = ss.struct_ids
        FROM scanr_structs ss
        WHERE sa.source = 'scanr'
          AND sa.id = ss.source_authorship_id
    """, (list(uca_wide_ids),))
    logger.info(f"Étape 3c — ScanR structure_ids : {cur.rowcount} authorships")


def show_stats(cur):
    """Affiche les compteurs in_perimeter par source."""
    for source_name, source_value in [("HAL", "hal"), ("OpenAlex", "openalex"),
                                       ("WoS", "wos"), ("ScanR", "scanr")]:
        cur.execute("SELECT COUNT(*) FROM source_authorships WHERE source = %s", (source_value,))
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM source_authorships WHERE source = %s AND in_perimeter = TRUE", (source_value,))
        uca = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM source_authorships WHERE source = %s AND structure_ids IS NOT NULL", (source_value,))
        with_structs = cur.fetchone()[0]
        logger.info(f"  {source_name:10s} : {total} total, {uca} in_perimeter, {with_structs} avec structure_ids")


def main():
    parser = argparse.ArgumentParser(description="Peuplement in_perimeter et structure_ids")
    parser.add_argument("--stats", action="store_true", help="Stats uniquement")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    t0 = time.perf_counter()

    # Charger les périmètres UCA une seule fois
    uca_ids = get_uca_structure_ids(cur)
    uca_wide_ids = get_uca_structure_ids_wide(cur)
    logger.info(f"Périmètre UCA restreint : {len(uca_ids)} structures")
    logger.info(f"Périmètre UCA large     : {len(uca_wide_ids)} structures")

    step1_hal_structure_ids(cur)
    step2_hal_in_perimeter(cur, uca_ids)
    step3_openalex(cur, uca_ids, uca_wide_ids)
    step3b_wos(cur, uca_ids, uca_wide_ids)
    step3c_scanr(cur, uca_ids, uca_wide_ids)

    conn.commit()
    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
    show_stats(cur)
    conn.close()


if __name__ == "__main__":
    main()
