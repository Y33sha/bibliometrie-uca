# STATUS: maintenance
"""Supprime les personnes sans aucune publication (zéro authorship canonique), avec tout ce qui pointe vers elles, en préservant les notices RH.

Ces personnes — créées au fil des runs sans jamais être rattachées à une publication — polluent la base (notamment la file « formes ambiguës » : leurs formes dérivées du nom canonique partagent un homonyme avec de vraies personnes, sans intérêt).

Critère : zéro ligne `authorships` ET aucune `persons_rh`. Les personnes RH sont des entités légitimes (enseignants-chercheurs sans publi dans le corpus) ; la FK RESTRICT `persons_rh` les protège de toute façon.

Manœuvre :
  1. NULL `source_authorships.person_id` des personnes cibles (FK NO ACTION → on détache avant de supprimer) ;
  2. DELETE `persons` — le CASCADE emporte `person_name_forms`, `person_identifiers`, `distinct_persons`, `rejected_authorships`.

Réutilisable : la situation peut se reformer après chaque pipeline.

Usage :
    python -m interfaces.cli.maintenance.delete_persons_without_publications [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("delete_persons_without_publications", os.path.dirname(__file__))

# Personnes à zéro authorship canonique et sans notice RH.
_TARGET = """
    FROM persons p
    WHERE NOT EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="N'écrit rien : affiche les comptes et sort."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        n_persons = conn.execute(text(f"SELECT count(*) {_TARGET}")).scalar_one()
        n_sa = conn.execute(
            text(
                f"SELECT count(*) FROM source_authorships sa WHERE sa.person_id IN (SELECT p.id {_TARGET})"
            )
        ).scalar_one()
        n_ids = conn.execute(
            text(
                f"SELECT count(*) FROM person_identifiers pi WHERE pi.person_id IN (SELECT p.id {_TARGET})"
            )
        ).scalar_one()
        n_forms = conn.execute(
            text(
                f"SELECT count(*) FROM person_name_forms pnf WHERE pnf.person_id IN (SELECT p.id {_TARGET})"
            )
        ).scalar_one()

    log.info("Personnes sans publication (hors RH) : %d", n_persons)
    log.info("  → source_authorships à détacher (person_id NULL) : %d", n_sa)
    log.info("  → person_identifiers supprimés (cascade) : %d", n_ids)
    log.info("  → person_name_forms supprimées (cascade) : %d", n_forms)

    if n_persons == 0:
        log.info("Rien à faire.")
        return 0
    if args.dry_run:
        log.info("Dry-run : aucune écriture.")
        return 0

    with engine.begin() as conn:
        detached = conn.execute(
            text(
                f"UPDATE source_authorships SET person_id = NULL WHERE person_id IN (SELECT p.id {_TARGET})"
            )
        ).rowcount
        log.info("1/2 — source_authorships détachées : %d", detached)

        deleted = conn.execute(text(f"DELETE {_TARGET}")).rowcount
        log.info("2/2 — personnes supprimées (+ cascade) : %d", deleted)

    log.info("✓ Terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
