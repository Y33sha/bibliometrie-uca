# STATUS: oneshot (2026-11-26)
"""Inscrit en base les verdicts des pages de jugement des attributions : épinglage pour « de la personne », rejet pour « homonyme ».

Chaque répertoire contient un fichier JSON par verdict : `person`, `publication`, `verdict` (`personne`, `homonyme` ou `incertain`). Un verdict « incertain » est ignoré. Deux verdicts contraires sur une même paire sont signalés et ignorés.

- « de la personne » : la contribution rattachée à la personne est épinglée sur elle. Une paire rejetée ou une publication sans contribution de la personne est signalée et laissée en l'état.
- « homonyme » : la paire (publication, personne) est rejetée, que la contribution soit rattachée ou non. Une paire déjà rejetée est laissée en l'état.

Usage :
    uv run python -m interfaces.cli.oneshot.record_review_verdicts <répertoire>...            # exécution
    uv run python -m interfaces.cli.oneshot.record_review_verdicts <répertoire>... --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import REJECTED_PAIRS
from interfaces.api.deps import contribution_service, person_service

log = setup_logger("record_review_verdicts", os.path.dirname(__file__))

PERSON = "personne"
HOMONYM = "homonyme"


def read_verdicts(directories: list[Path]) -> dict[tuple[int, int], str]:
    """Renvoie le verdict tranché de chaque paire (personne, publication). Une paire aux verdicts contraires est écartée."""
    seen: dict[tuple[int, int], set[str]] = {}
    for directory in directories:
        for path in sorted(directory.glob("*.json")):
            v = json.loads(path.read_text())
            if v["verdict"] in (PERSON, HOMONYM):
                seen.setdefault((v["person"], v["publication"]), set()).add(v["verdict"])
    for pair, verdicts in seen.items():
        if len(verdicts) > 1:
            log.warning("personne %d, publication %d : verdicts contraires, ignorés", *pair)
    return {pair: verdicts.pop() for pair, verdicts in seen.items() if len(verdicts) == 1}


def record(conn: Connection, verdicts: dict[tuple[int, int], str]) -> Counter[str]:
    """Épingle ou rejette chaque paire selon son verdict, et renvoie le décompte des issues."""
    rejected = set(
        conn.execute(
            text(f"SELECT DISTINCT person_id, publication_id FROM ({REJECTED_PAIRS}) rp")
        ).all()
    )
    attached = {
        (r.person_id, r.publication_id): r
        for r in conn.execute(
            text("""
                SELECT id, person_id, publication_id, resolution_mode::text AS mode FROM contributions
                WHERE (person_id, publication_id) IN (SELECT * FROM unnest(CAST(:persons AS int[]), CAST(:publications AS int[])))
            """),
            {"persons": [p for p, _ in verdicts], "publications": [q for _, q in verdicts]},
        )
    }
    existing = set(
        conn.execute(
            text("SELECT id FROM persons WHERE id = ANY(:p)"),
            {"p": sorted({p for p, _ in verdicts})},
        ).scalars()
    )
    contributions = contribution_service(conn)
    persons = person_service(conn)
    outcomes: Counter[str] = Counter()
    for (person_id, publication_id), verdict in sorted(verdicts.items()):
        pair = (person_id, publication_id)
        contribution = attached.get(pair)
        if person_id not in existing:
            outcome = "personne disparue"
        elif verdict == PERSON:
            if pair in rejected:
                outcome = "de la personne, paire rejetée : laissée en l'état"
            elif contribution is None:
                outcome = "de la personne, sans contribution rattachée : laissée en l'état"
            elif contribution.mode == "manual":
                outcome = "de la personne, déjà épinglée"
            else:
                contributions.batch_assign_orphan_contributions(person_id, [contribution.id])
                outcome = "de la personne, épinglée"
        elif pair in rejected:
            outcome = "homonyme, déjà rejetée"
        else:
            persons.detach_contributions(person_id, [publication_id])
            outcome = "homonyme, rejetée" + (
                "" if contribution else " (sans contribution rattachée)"
            )
        if "laissée" in outcome or outcome == "personne disparue":
            log.info("personne %d, publication %d : %s", person_id, publication_id, outcome)
        outcomes[outcome] += 1
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+", help="Répertoires des verdicts.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    verdicts = read_verdicts(args.directories)
    with get_sync_engine().connect() as conn:
        outcomes = record(conn, verdicts)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    for label, n in sorted(outcomes.items()):
        log.info("%s : %d", label, n)
    log.info("DRY-RUN — aucune écriture" if args.dry_run else "✓ verdicts inscrits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
