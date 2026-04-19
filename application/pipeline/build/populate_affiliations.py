"""
Résolution des affiliations sur les authorships sources.

Peuple in_perimeter et structure_ids sur source_authorships
en utilisant les adresses résolues (address_structures) et les
périmètres configurés (utils/perimeter.py).

Circuit unifié pour toutes les sources (HAL, OpenAlex, WoS, ScanR, theses.fr) :
les adresses sont créées pendant la normalisation, résolues par resolve_addresses,
puis ce script lit les résultats.

Deux périmètres :
  - restreint : UCA + labos tutellés → sert pour in_perimeter
  - large : restreint + partenaires (CHU, INP…) → sert pour structure_ids

Usage:
    python populate_affiliations.py          # exécution complète
    python populate_affiliations.py --stats  # afficher les compteurs sans modifier
    python populate_affiliations.py --mode daily  # traiter uniquement les authorships récentes
"""

import argparse
import os
import time
from typing import Any

from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger
from infrastructure.perimeter import get_affiliations_structure_ids, get_persons_structure_ids

logger = setup_logger("populate_affiliations", os.path.join(os.path.dirname(__file__), "logs"))

# Filtre temporel pour le mode daily : authorships dont le source_document
# a été créé dans les dernières 24h (= insérées pendant ce pipeline run).
DAILY_FILTER = "sd.created_at >= NOW() - INTERVAL '24 hours'"


def _step_address_source(
    cur: Any, source: Any, perimeter_ids: Any, wide_ids: Any, daily: Any = False
) -> Any:
    """Étapes 3/3b/3c : source avec adresses — calculer in_perimeter + structure_ids."""
    label = source.capitalize() if source != "openalex" else "OA"

    if not daily:
        cur.execute(
            "UPDATE source_authorships SET in_perimeter = FALSE, structure_ids = NULL WHERE source = %s",
            (source,),
        )
        logger.info(f"  {label} reset : {cur.rowcount} authorships")

    # in_perimeter via périmètre restreint
    if daily:
        cur.execute(
            f"""
            UPDATE source_authorships sa
            SET in_perimeter = TRUE
            FROM source_publications sd
            WHERE sa.source = %s
              AND sd.id = sa.source_publication_id
              AND {DAILY_FILTER}
              AND EXISTS (
                SELECT 1
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                WHERE saa.source_authorship_id = sa.id
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
            )
        """,
            (source, list(perimeter_ids)),
        )
    else:
        cur.execute(
            """
            UPDATE source_authorships sa
            SET in_perimeter = TRUE
            WHERE sa.source = %s
              AND EXISTS (
                SELECT 1
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                WHERE saa.source_authorship_id = sa.id
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
            )
        """,
            (source, list(perimeter_ids)),
        )
    logger.info(f"  {label} in_perimeter = TRUE : {cur.rowcount} authorships")

    # structure_ids via périmètre large
    if daily:
        cur.execute(
            f"""
            WITH src_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                JOIN source_publications sd ON sd.id = sa2.source_publication_id
                     AND {DAILY_FILTER}
                WHERE sa2.source = %s
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ss.struct_ids
            FROM src_structs ss
            WHERE sa.id = ss.source_authorship_id
        """,
            (source, list(wide_ids)),
        )
    else:
        cur.execute(
            """
            WITH src_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                WHERE sa2.source = %s
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ss.struct_ids
            FROM src_structs ss
            WHERE sa.id = ss.source_authorship_id
        """,
            (source, list(wide_ids)),
        )
    logger.info(f"  {label} structure_ids : {cur.rowcount} authorships")


def step3d_theses(cur: Any, wide_ids: Any, daily: Any = False) -> Any:
    """Étape 3d : theses.fr — résoudre structure_ids via adresses.

    in_perimeter est déjà à TRUE (posé par normalize_theses), on ne le reset pas.
    On résout uniquement les structure_ids via les adresses résolues.
    """
    if daily:
        cur.execute(
            f"""
            WITH theses_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                JOIN source_publications sd ON sd.id = sa2.source_publication_id
                     AND {DAILY_FILTER}
                WHERE sa2.source = 'theses'
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ts.struct_ids
            FROM theses_structs ts
            WHERE sa.source = 'theses'
              AND sa.id = ts.source_authorship_id
        """,
            (list(wide_ids),),
        )
    else:
        cur.execute(
            """
            WITH theses_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                WHERE sa2.source = 'theses'
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ts.struct_ids
            FROM theses_structs ts
            WHERE sa.source = 'theses'
              AND sa.id = ts.source_authorship_id
        """,
            (list(wide_ids),),
        )
    logger.info(f"Étape 3d — theses.fr structure_ids : {cur.rowcount} authorships")


def show_stats(cur: Any) -> Any:
    """Affiche les compteurs in_perimeter par source."""
    for source_name, source_value in [
        ("HAL", "hal"),
        ("OpenAlex", "openalex"),
        ("WoS", "wos"),
        ("ScanR", "scanr"),
        ("theses.fr", "theses"),
    ]:
        cur.execute("SELECT COUNT(*) FROM source_authorships WHERE source = %s", (source_value,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM source_authorships WHERE source = %s AND in_perimeter = TRUE",
            (source_value,),
        )
        uca = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM source_authorships WHERE source = %s AND structure_ids IS NOT NULL",
            (source_value,),
        )
        with_structs = cur.fetchone()[0]
        logger.info(
            f"  {source_name:10s} : {total} total, {uca} in_perimeter, {with_structs} avec structure_ids"
        )


def main() -> Any:
    parser = argparse.ArgumentParser(description="Peuplement in_perimeter et structure_ids")
    parser.add_argument("--stats", action="store_true", help="Stats uniquement")
    parser.add_argument(
        "--sources",
        default="hal,openalex,wos,scanr,theses",
        help="Sources à traiter (défaut: toutes)",
    )
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "weekly", "monthly", "daily"],
        help="Mode d'exécution (daily: incrémental, autres: complet)",
    )
    args = parser.parse_args()

    sources = set(s.strip() for s in args.sources.split(",") if s.strip())
    daily = args.mode == "daily"

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    t0 = time.perf_counter()

    # Charger les périmètres une seule fois
    perimeter_ids = get_persons_structure_ids(cur)
    wide_ids = get_affiliations_structure_ids(cur)
    logger.info(f"Périmètre restreint : {len(perimeter_ids)} structures")
    logger.info(f"Périmètre large     : {len(wide_ids)} structures")
    logger.info(f"Sources : {', '.join(sorted(sources))}")
    if daily:
        logger.info("Mode daily : traitement des authorships récentes uniquement")

    # Toutes les sources utilisent le même circuit (adresses résolues)
    for source in ["hal", "openalex", "wos", "scanr"]:
        if source in sources:
            _step_address_source(cur, source, perimeter_ids, wide_ids, daily=daily)
    if "theses" in sources:
        step3d_theses(cur, wide_ids, daily=daily)

    conn.commit()
    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
    conn.close()


if __name__ == "__main__":
    main()
