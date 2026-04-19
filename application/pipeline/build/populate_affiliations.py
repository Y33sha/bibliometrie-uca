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

Le SQL est isolé dans `infrastructure/db/queries/affiliations.py`.

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
from infrastructure.db.queries.affiliations import (
    count_source_authorships_stats,
    reset_source_authorships_for,
    set_in_perimeter_from_addresses,
    set_structure_ids_from_addresses,
    set_theses_structure_ids,
)
from infrastructure.log import setup_logger
from infrastructure.perimeter import get_affiliations_structure_ids, get_persons_structure_ids

logger = setup_logger("populate_affiliations", os.path.join(os.path.dirname(__file__), "logs"))


def _step_address_source(
    cur: Any, source: str, perimeter_ids: Any, wide_ids: Any, daily: bool = False
) -> None:
    """Étapes 3/3b/3c : source avec adresses — calculer in_perimeter + structure_ids."""
    label = source.capitalize() if source != "openalex" else "OA"

    if not daily:
        n = reset_source_authorships_for(cur, source)
        logger.info(f"  {label} reset : {n} authorships")

    n = set_in_perimeter_from_addresses(
        cur, source=source, perimeter_ids=list(perimeter_ids), daily=daily
    )
    logger.info(f"  {label} in_perimeter = TRUE : {n} authorships")

    n = set_structure_ids_from_addresses(cur, source=source, wide_ids=list(wide_ids), daily=daily)
    logger.info(f"  {label} structure_ids : {n} authorships")


def step3d_theses(cur: Any, wide_ids: Any, daily: bool = False) -> None:
    """Étape 3d : theses.fr — résoudre structure_ids via adresses.

    in_perimeter est déjà à TRUE (posé par normalize_theses), on ne le reset pas.
    """
    n = set_theses_structure_ids(cur, wide_ids=list(wide_ids), daily=daily)
    logger.info(f"Étape 3d — theses.fr structure_ids : {n} authorships")


def show_stats(cur: Any) -> None:
    """Affiche les compteurs in_perimeter par source."""
    for source_name, source_value in [
        ("HAL", "hal"),
        ("OpenAlex", "openalex"),
        ("WoS", "wos"),
        ("ScanR", "scanr"),
        ("theses.fr", "theses"),
    ]:
        total, uca, with_structs = count_source_authorships_stats(cur, source_value)
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

    perimeter_ids = get_persons_structure_ids(cur)
    wide_ids = get_affiliations_structure_ids(cur)
    logger.info(f"Périmètre restreint : {len(perimeter_ids)} structures")
    logger.info(f"Périmètre large     : {len(wide_ids)} structures")
    logger.info(f"Sources : {', '.join(sorted(sources))}")
    if daily:
        logger.info("Mode daily : traitement des authorships récentes uniquement")

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
