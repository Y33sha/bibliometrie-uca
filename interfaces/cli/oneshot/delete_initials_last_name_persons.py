# STATUS: oneshot (2026-10-06)
"""Supprime les personnes dont le nom de famille se réduit à des initiales (« P.P. » / « Lechalard »).

Ces fiches ont pris le découpage inversé de la signature qui les a créées. Leurs signatures portent le découpage corrigé : supprimées, les fiches laissent leurs signatures orphelines (`ON DELETE SET NULL`), et le run suivant les rattache ou recrée la personne d'après ce découpage. Sont épargnées les personnes du référentiel RH et celles qui portent une curation : épinglage, identifiant confirmé, verdict sur une forme de nom.

Usage :
    python -m interfaces.cli.oneshot.delete_initials_last_name_persons            # exécution
    python -m interfaces.cli.oneshot.delete_initials_last_name_persons --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("delete_initials_last_name_persons", os.path.dirname(__file__))

_CANDIDATES_SQL = text(r"""
    SELECT p.id, p.last_name, p.first_name
    FROM persons p
    WHERE p.last_name_normalized ~ '^([a-z] )*[a-z]$'
      AND NOT EXISTS (SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM confirmed_authorships ca WHERE ca.person_id = p.id)
      AND NOT EXISTS (
          SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.status = 'confirmed'
      )
      AND NOT EXISTS (
          SELECT 1 FROM person_name_forms f WHERE f.person_id = p.id AND f.status <> 'pending'
      )
    ORDER BY p.id
""")


def delete_persons(conn: Connection, *, apply: bool) -> list[int]:
    """Supprime les personnes candidates et rend leurs identifiants."""
    rows = conn.execute(_CANDIDATES_SQL).all()
    for r in rows:
        log.info("%d : %s / %s", r.id, r.last_name, r.first_name)
    ids = [r.id for r in rows]
    if apply and ids:
        conn.execute(text("DELETE FROM persons WHERE id = ANY(:ids)"), {"ids": ids})
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    apply = not parser.parse_args().dry_run
    with get_sync_engine().connect() as conn:
        ids = delete_persons(conn, apply=apply)
        if apply:
            conn.commit()
            log.info("✓ %d personnes supprimées", len(ids))
        else:
            log.info("DRY-RUN — %d personnes à supprimer, aucune écriture", len(ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
