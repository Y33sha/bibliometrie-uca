# STATUS: oneshot (2026-10-19)
"""Fusionne les doublons de personnes relevés par la relecture des groupes d'auteurs à plusieurs personnes.

Le fichier CSV donne une fusion par ligne : colonnes `conservée` et `absorbée`, identifiants de personnes. Chaque identifiant suit sa redirection de fusion (`merge_redirects`) jusqu'à la personne qui l'a absorbé. Une ligne est ignorée quand ses deux personnes sont déjà fusionnées, quand une personne a disparu sans redirection, ou quand les deux ont une fiche RH. Chaque fusion est commitée seule.

Usage :
    python -m interfaces.cli.oneshot.merge_reviewed_person_duplicates <fichier.csv>            # exécution
    python -m interfaces.cli.oneshot.merge_reviewed_person_duplicates <fichier.csv> --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import Connection, text

from domain.errors import ConflictError
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from interfaces.api.deps import person_service

log = setup_logger("merge_reviewed_person_duplicates", os.path.dirname(__file__))


def read_pairs(path: Path) -> list[tuple[int, int]]:
    """Couples (conservée, absorbée) du fichier CSV."""
    with path.open(newline="") as f:
        return [(int(row["conservée"]), int(row["absorbée"])) for row in csv.DictReader(f)]


def current_person(conn: Connection, person_id: int) -> int | None:
    """Personne désignée par l'identifiant `person_id` après les fusions, ou `None` si elle a disparu sans redirection."""
    return conn.execute(
        text("""
            SELECT p.id FROM persons p
            WHERE p.id = coalesce(
                (SELECT r.kept_id FROM merge_redirects r
                 WHERE r.entity = 'person' AND r.absorbed_id = :id),
                :id)
        """),
        {"id": person_id},
    ).scalar()


def merge_pairs(conn: Connection, pairs: Iterable[tuple[int, int]], *, apply: bool) -> Counter[str]:
    """Fusionne chaque couple (conservée, absorbée), commite chaque fusion si `apply`, et renvoie le décompte des issues."""
    outcomes: Counter[str] = Counter()
    persons = person_service(conn)
    for kept, absorbed in pairs:
        target, source = current_person(conn, kept), current_person(conn, absorbed)
        if target is None or source is None:
            log.info("%s ← %s : personne disparue", kept, absorbed)
            outcomes["personne disparue"] += 1
            continue
        if target == source:
            outcomes["déjà fusionnées"] += 1
            continue
        try:
            persons.merge_person(target, source)
        except ConflictError as e:
            log.warning("%s", e)
            outcomes["deux fiches RH"] += 1
            continue
        if apply:
            conn.commit()
        outcomes["fusionnées"] += 1
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv", type=Path, help="Fichier des fusions : colonnes `conservée` et `absorbée`."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    apply = not args.dry_run
    with get_sync_engine().connect() as conn:
        outcomes = merge_pairs(conn, read_pairs(args.csv), apply=apply)
        if not apply:
            conn.rollback()
    for label, n in outcomes.items():
        log.info("%s : %d", label, n)
    log.info("✓ fusions appliquées" if apply else "DRY-RUN — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
