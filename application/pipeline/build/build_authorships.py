"""
Construit la table authorships (table de vérité) à partir des authorships sources.

Étape 1 : Insérer les authorships manquantes (paires publication_id, person_id)
Étape 2 : Peupler les FK (source_authorships.authorship_id → authorships.id)
Étape 3 : Propager author_position et is_corresponding
Étape 4 : Propager in_perimeter et structure_ids (union des sources)

Le SQL est isolé dans `infrastructure/db/queries/authorships_build.py`.

Usage:
    python build_authorships.py              # exécuter
    python build_authorships.py --dry-run    # dry-run
"""

import argparse
import os
import time
from typing import Any

from infrastructure.db.connection import get_connection
from infrastructure.db.queries.authorships_build import (
    count_authorships_in_perimeter,
    insert_missing_authorships,
    link_source_authorships_to_authorship_for,
    propagate_author_position,
    propagate_is_corresponding,
    propagate_perimeter_and_structures_from,
    propagate_roles,
    reset_authorships_perimeter_and_structures,
)
from infrastructure.log import setup_logger

logger = setup_logger("build_authorships", os.path.join(os.path.dirname(__file__), "logs"))


def build(cur: Any, sources: Any = None) -> Any:
    all_sources = [
        ("HAL", "hal"),
        ("OpenAlex", "openalex"),
        ("WoS", "wos"),
        ("ScanR", "scanr"),
        ("theses.fr", "theses"),
    ]
    if sources:
        active_sources = [(n, v) for n, v in all_sources if v in sources]
    else:
        active_sources = all_sources
    active_values = {v for _, v in active_sources}
    full_run = active_values == {v for _, v in all_sources}

    t0 = time.perf_counter()
    logger.info(f"Sources : {', '.join(n for n, _ in active_sources)}")

    logger.info("Étape 1 : insertion des authorships manquantes...")
    inserted = insert_missing_authorships(cur)
    logger.info(f"  {inserted} authorships créées")

    logger.info("Étape 2 : peuplement des FK (source_authorships → authorships)...")
    for source_name, source_value in active_sources:
        n = link_source_authorships_to_authorship_for(cur, source_value)
        logger.info(f"  {source_name} FK : {n} liens")

    logger.info("Étape 3 : author_position et is_corresponding...")
    logger.info(f"  {propagate_author_position(cur)} positions mises à jour")
    logger.info(f"  {propagate_is_corresponding(cur)} is_corresponding mises à jour")
    logger.info(f"  {propagate_roles(cur)} roles mises à jour")

    logger.info("Étape 4 : propagation in_perimeter et structure_ids...")
    if full_run:
        reset = reset_authorships_perimeter_and_structures(cur)
        logger.info(f"  Reset {reset} authorships")
    else:
        logger.info("  Pas de reset (run partiel)")

    for source_name, source_value in active_sources:
        n = propagate_perimeter_and_structures_from(cur, source_value)
        logger.info(f"  {source_name} : {n} authorships mises à jour")

    total_uca = count_authorships_in_perimeter(cur)
    logger.info(f"  Total authorships in_perimeter=TRUE : {total_uca}")

    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")


def main() -> Any:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    parser.add_argument("--sources", default=None, help="Sources à traiter (défaut: toutes)")
    args = parser.parse_args()

    sources = set(s.strip() for s in args.sources.split(",") if s.strip()) if args.sources else None

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    build(cur, sources=sources)

    if args.dry_run:
        conn.rollback()
        logger.info("DRY-RUN — aucune modification.")
    else:
        conn.commit()
        logger.info("COMMIT effectué.")

    conn.close()


if __name__ == "__main__":
    main()
