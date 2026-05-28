# STATUS: oneshot (2026-05-28)
"""Purge les publications dont `pub_year` est antérieur à la fenêtre live du pipeline (= `current_year - config.pipeline_years_full`), avec leurs source_publications, source_authorships et addresses orphelines.

Contexte : fuite identifiée côté HAL daily (build_query posait `submittedDate_tdate:[since TO *]` sans borner `producedDateY_i` → dépôt HAL tardif d'une vieille publication passait le filtre). Fix appliqué côté extracteur (cf. `infrastructure/sources/hal/extract_hal.py::build_query`) ; ce script nettoie le stock accumulé.

Critères :
  - publications : `pub_year < cutoff` ET aucune source_publication theses (on préserve les thèses, hors fenêtre par design)
  - persons : aucune source_authorship `in_perimeter = TRUE` ET pas de ligne persons_rh
  - addresses : aucun source_authorship_address ni address_structure

Cascade FK utilisée :
  - `source_publications` → `source_authorships` → `source_authorship_addresses`, `source_authorship_structures` (CASCADE)
  - `publications` → `authorships`, `publication_subjects`, `distinct_publications` (CASCADE)
  - `persons` → `person_identifiers`, `person_name_forms` (CASCADE)

Usage :
    python -m interfaces.cli.oneshot.cleanup_publications_out_of_window [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("cleanup_publications_out_of_window", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien : affiche les comptes prévus et sort.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()

    with engine.connect() as conn:
        cutoff = conn.execute(
            text("""
                SELECT EXTRACT(YEAR FROM CURRENT_DATE)::int
                     - (SELECT value::int FROM config WHERE key = 'pipeline_years_full')
            """)
        ).scalar_one()
        log.info("Cutoff year : pub_year < %d", cutoff)

        target_ids_sql = text("""
            SELECT p.id FROM publications p
            WHERE p.pub_year < :cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM source_publications sp
                  WHERE sp.publication_id = p.id AND sp.source = 'theses'
              )
        """)
        pub_ids = [r[0] for r in conn.execute(target_ids_sql, {"cutoff": cutoff}).all()]
        log.info("Publications cibles : %d", len(pub_ids))

        if not pub_ids:
            log.info("Rien à faire.")
            return 0

        sp_count = conn.execute(
            text("SELECT COUNT(*) FROM source_publications WHERE publication_id = ANY(:ids)"),
            {"ids": pub_ids},
        ).scalar_one()
        sa_count = conn.execute(
            text("""
                SELECT COUNT(*) FROM source_authorships sa
                JOIN source_publications sp ON sp.id = sa.source_publication_id
                WHERE sp.publication_id = ANY(:ids)
            """),
            {"ids": pub_ids},
        ).scalar_one()
        log.info("  → source_publications à supprimer : %d", sp_count)
        log.info("  → source_authorships à supprimer (cascade) : %d", sa_count)

    if args.dry_run:
        log.info("Dry-run : aucune écriture.")
        return 0

    with engine.begin() as conn:
        n_sp = conn.execute(
            text("DELETE FROM source_publications WHERE publication_id = ANY(:ids)"),
            {"ids": pub_ids},
        ).rowcount
        log.info("DELETE source_publications : %d lignes", n_sp)

        n_p = conn.execute(
            text("DELETE FROM publications WHERE id = ANY(:ids)"),
            {"ids": pub_ids},
        ).rowcount
        log.info("DELETE publications : %d lignes", n_p)

        n_persons = conn.execute(
            text("""
                DELETE FROM persons p
                WHERE NOT EXISTS (SELECT 1 FROM persons_rh prh WHERE prh.person_id = p.id)
                  AND NOT EXISTS (
                      SELECT 1 FROM source_authorships sa
                      WHERE sa.person_id = p.id AND sa.in_perimeter = TRUE
                  )
            """)
        ).rowcount
        log.info("DELETE persons orphelines : %d lignes", n_persons)

        n_addresses = conn.execute(
            text("""
                DELETE FROM addresses a
                WHERE NOT EXISTS (
                    SELECT 1 FROM source_authorship_addresses saa
                    WHERE saa.address_id = a.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM address_structures ast
                    WHERE ast.address_id = a.id
                )
            """)
        ).rowcount
        log.info("DELETE addresses orphelines : %d lignes", n_addresses)

    log.info("✓ Nettoyage terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
