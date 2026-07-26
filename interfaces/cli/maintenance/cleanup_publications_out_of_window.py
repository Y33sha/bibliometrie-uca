# STATUS: maintenance
"""Purge les publications hors fenêtre d'extraction et les enregistrements devenus orphelins.

Rétablit l'invariant « aucune publication antérieure à l'ancre du pipeline » (`config.pipeline_start_year_full`, année absolue), les thèses exceptées (hors fenêtre par nature). Sert de filet lorsqu'une source dépose une publication trop ancienne, ou lorsque l'ancre est avancée et laisse un stock en deçà de la fenêtre.

Critères de suppression :
  - publications : `pub_year < ancre` ET aucune source_publication `theses`
  - persons : aucune source_authorship `in_perimeter = TRUE` ET aucune fiche persons_rh
  - addresses : aucun source_authorship_address ni address_structure

Cascade FK mobilisée :
  - `source_publications` → `source_authorships` → `source_authorship_addresses`, `source_authorship_structures`
  - `publications` → `authorships`, `publication_subjects`, `distinct_publications`
  - `persons` → `person_identifiers`, `person_name_forms`

Usage :
    python -m interfaces.cli.maintenance.cleanup_publications_out_of_window [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("cleanup_publications_out_of_window", os.path.dirname(__file__))


def fetch_cutoff(conn: Connection) -> int:
    """Année-ancre du pipeline (`config.pipeline_start_year_full`) : les publications antérieures sont hors fenêtre."""
    return conn.execute(
        text("SELECT (value #>> '{}')::int FROM config WHERE key = 'pipeline_start_year_full'")
    ).scalar_one()


def select_target_pub_ids(conn: Connection, cutoff: int) -> list[int]:
    """Publications antérieures à l'ancre, thèses exceptées (hors fenêtre par nature)."""
    rows = conn.execute(
        text("""
            SELECT p.id FROM publications p
            WHERE p.pub_year < :cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM source_publications sp
                  WHERE sp.publication_id = p.id AND sp.source = 'theses'
              )
        """),
        {"cutoff": cutoff},
    ).all()
    return [r[0] for r in rows]


def count_dependents(conn: Connection, pub_ids: list[int]) -> tuple[int, int]:
    """Nombre de source_publications et de source_authorships rattachés aux publications cibles."""
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
    return sp_count, sa_count


def purge(conn: Connection, pub_ids: list[int]) -> None:
    """Supprime les publications cibles, puis les enregistrements devenus orphelins.

    Les source_authorships et leurs dépendances partent par cascade FK avec les source_publications. persons et addresses sont ensuite balayées sur leur condition d'orphelinage globale (aucune référence restante), ce qui ramasse aussi d'éventuels orphelins préexistants, pas seulement ceux libérés par la purge.
    """
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
        cutoff = fetch_cutoff(conn)
        log.info("Ancre : purge des publications avec pub_year < %d", cutoff)

        pub_ids = select_target_pub_ids(conn, cutoff)
        log.info("Publications cibles : %d", len(pub_ids))
        if not pub_ids:
            log.info("Rien à faire.")
            return 0

        sp_count, sa_count = count_dependents(conn, pub_ids)
        log.info("  → source_publications à supprimer : %d", sp_count)
        log.info("  → source_authorships à supprimer (cascade) : %d", sa_count)

    if args.dry_run:
        log.info("Dry-run : aucune écriture.")
        return 0

    with engine.begin() as conn:
        purge(conn, pub_ids)

    log.info("✓ Nettoyage terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
