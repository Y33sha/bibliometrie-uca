# STATUS: oneshot (2026-09-15)
"""Fusionne chaque personne au prénom réduit à des initiales dans la seule personne de même nom de famille au prénom plein compatible.

« Perret P. » rejoint « Perret Pascal », « Al-Izeri A. » rejoint « Al-Izeri Abdul-Majeed » : les initiales de la personne réduite commencent celles du prénom plein, dans l'ordre (`full_namesakes`). Une personne réduite à plusieurs candidates, ou marquée distincte de sa candidate, reste en l'état.

La phase `persons` rattache ces signatures par initiales compatibles ; ce script fusionne les doublons du stock.

Usage :
    python -m interfaces.cli.oneshot.merge_reduced_first_name_duplicates            # exécution
    python -m interfaces.cli.oneshot.merge_reduced_first_name_duplicates --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict

from sqlalchemy import Connection, text

from application.services.persons.core import merge_person
from domain.errors import ConflictError
from domain.normalize import normalize_name
from domain.persons.matching import Namesake, full_namesakes
from domain.persons.name_matching import first_name_initials
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
from infrastructure.repositories import person_repository

log = setup_logger("merge_reduced_first_name_duplicates", os.path.dirname(__file__))


def _pairs_to_merge(conn: Connection) -> list[tuple[Namesake, Namesake]]:
    """Couples (personne réduite, seule personne au prénom plein compatible), hors paires marquées distinctes."""
    namesakes = PgPersonsMatchingQueries().fetch_namesakes(conn)
    by_id = {n.person_id: n for n in namesakes}
    by_last_name: dict[str, list[Namesake]] = defaultdict(list)
    for n in namesakes:
        by_last_name[normalize_name(n.last_name)].append(n)
    distinct = {
        frozenset((r.person_id_a, r.person_id_b))
        for r in conn.execute(text("SELECT person_id_a, person_id_b FROM distinct_persons"))
    }

    pairs = []
    for n in namesakes:
        initials = first_name_initials(n.first_name)
        if initials is None:
            continue
        candidates = full_namesakes(initials, by_last_name[normalize_name(n.last_name)])
        if len(candidates) == 1 and frozenset((n.person_id, candidates[0])) not in distinct:
            pairs.append((n, by_id[candidates[0]]))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    apply = not parser.parse_args().dry_run
    if not apply:
        log.info("DRY-RUN (rapport seul) — retirer --dry-run pour écrire")

    engine = get_sync_engine()
    with engine.connect() as conn:
        pairs = _pairs_to_merge(conn)
        log.info("couples à fusionner : %d", len(pairs))
        repo = person_repository(conn)
        merged = 0
        for reduced, full in pairs:
            log.info(
                "%d %s %s → %d %s %s",
                reduced.person_id,
                reduced.last_name,
                reduced.first_name,
                full.person_id,
                full.last_name,
                full.first_name,
            )
            if not apply:
                continue
            try:
                merge_person(full.person_id, reduced.person_id, repo=repo)
            except ConflictError as exc:
                log.warning("%d → %d écarté : %s", reduced.person_id, full.person_id, exc)
                continue
            merged += 1
        if apply:
            conn.commit()
            log.info("✓ %d fusions appliquées", merged)
        else:
            log.info("DRY-RUN terminé — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
