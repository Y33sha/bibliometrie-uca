"""
Peuplement is_uca et structure_ids sur les authorships sources.

Convertit l'ancien script SQL db/populate_uca_flags.sql en Python
pour être portable (pas de dépendance à psql) et réutiliser
le périmètre UCA centralisé (utils/uca_perimeter.py).

Deux périmètres :
  - restreint : UCA + labos tutellés → sert pour is_uca
  - large : restreint + partenaires (CHU, INP…) → sert pour structure_ids

Usage:
    python populate_uca_flags.py          # exécution complète
    python populate_uca_flags.py --stats  # afficher les compteurs sans modifier
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.uca_perimeter import get_uca_structure_ids, get_uca_structure_ids_wide

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def step1_hal_structure_ids(cur):
    """Étape 1 : HAL — mapper hal_struct_ids → structure_ids (réels)."""
    cur.execute("""
        UPDATE hal_authorships has
        SET structure_ids = mapped.struct_ids
        FROM (
            SELECT has2.id,
                   array_agg(DISTINCT hs.structure_id) AS struct_ids
            FROM hal_authorships has2,
                 LATERAL unnest(has2.hal_struct_ids) AS hsid(val)
            JOIN hal_structures hs ON hs.hal_struct_id = hsid.val
            WHERE hs.structure_id IS NOT NULL
            GROUP BY has2.id
        ) mapped
        WHERE has.id = mapped.id
    """)
    logger.info(f"Étape 1 — HAL structure_ids mappés : {cur.rowcount} authorships")


def step2_hal_is_uca(cur, uca_ids):
    """Étape 2 : HAL — recalculer is_uca."""
    cur.execute("UPDATE hal_authorships SET is_uca = FALSE")
    logger.info(f"Étape 2 — HAL is_uca reset : {cur.rowcount} authorships")

    cur.execute("""
        UPDATE hal_authorships has
        SET is_uca = TRUE
        WHERE has.structure_ids IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM unnest(has.structure_ids) AS sid
            WHERE sid = ANY(%s)
          )
    """, (list(uca_ids),))
    logger.info(f"Étape 2 — HAL is_uca = TRUE : {cur.rowcount} authorships")


def step3_openalex(cur, uca_ids, uca_wide_ids):
    """Étape 3 : OpenAlex — calculer is_uca + structure_ids."""
    cur.execute("UPDATE openalex_authorships SET is_uca = FALSE, structure_ids = NULL")
    logger.info(f"Étape 3 — OA reset : {cur.rowcount} authorships")

    # is_uca via périmètre restreint
    cur.execute("""
        UPDATE openalex_authorships oas
        SET is_uca = TRUE
        WHERE EXISTS (
            SELECT 1
            FROM openalex_authorship_addresses oaa
            JOIN address_structures ast ON ast.address_id = oaa.address_id
            WHERE oaa.openalex_authorship_id = oas.id
              AND ast.structure_id = ANY(%s)
        )
    """, (list(uca_ids),))
    logger.info(f"Étape 3 — OA is_uca = TRUE : {cur.rowcount} authorships")

    # structure_ids via périmètre large
    cur.execute("""
        WITH oas_structs AS (
            SELECT oaa.openalex_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM openalex_authorship_addresses oaa
            JOIN address_structures ast ON ast.address_id = oaa.address_id
            WHERE ast.structure_id = ANY(%s)
            GROUP BY oaa.openalex_authorship_id
        )
        UPDATE openalex_authorships oas
        SET structure_ids = os.struct_ids
        FROM oas_structs os
        WHERE oas.id = os.openalex_authorship_id
    """, (list(uca_wide_ids),))
    logger.info(f"Étape 3 — OA structure_ids : {cur.rowcount} authorships")


def step3b_wos(cur, uca_ids, uca_wide_ids):
    """Étape 3b : WoS — calculer is_uca + structure_ids."""
    cur.execute("UPDATE wos_authorships SET is_uca = FALSE, structure_ids = NULL")
    logger.info(f"Étape 3b — WoS reset : {cur.rowcount} authorships")

    # is_uca via périmètre restreint
    cur.execute("""
        UPDATE wos_authorships was
        SET is_uca = TRUE
        WHERE EXISTS (
            SELECT 1
            FROM wos_authorship_addresses waa
            JOIN address_structures ast ON ast.address_id = waa.address_id
            WHERE waa.wos_authorship_id = was.id
              AND ast.structure_id = ANY(%s)
        )
    """, (list(uca_ids),))
    logger.info(f"Étape 3b — WoS is_uca = TRUE : {cur.rowcount} authorships")

    # structure_ids via périmètre large
    cur.execute("""
        WITH was_structs AS (
            SELECT waa.wos_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM wos_authorship_addresses waa
            JOIN address_structures ast ON ast.address_id = waa.address_id
            WHERE ast.structure_id = ANY(%s)
            GROUP BY waa.wos_authorship_id
        )
        UPDATE wos_authorships was
        SET structure_ids = ws.struct_ids
        FROM was_structs ws
        WHERE was.id = ws.wos_authorship_id
    """, (list(uca_wide_ids),))
    logger.info(f"Étape 3b — WoS structure_ids : {cur.rowcount} authorships")


def show_stats(cur):
    """Affiche les compteurs is_uca par source."""
    for source, table in [("HAL", "hal_authorships"),
                          ("OpenAlex", "openalex_authorships"),
                          ("WoS", "wos_authorships")]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE is_uca = TRUE")
        uca = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE structure_ids IS NOT NULL")
        with_structs = cur.fetchone()[0]
        logger.info(f"  {source:10s} : {total} total, {uca} is_uca, {with_structs} avec structure_ids")


def main():
    parser = argparse.ArgumentParser(description="Peuplement is_uca et structure_ids")
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
    step2_hal_is_uca(cur, uca_ids)
    step3_openalex(cur, uca_ids, uca_wide_ids)
    step3b_wos(cur, uca_ids, uca_wide_ids)

    conn.commit()
    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
    show_stats(cur)
    conn.close()


if __name__ == "__main__":
    main()
