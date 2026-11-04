# STATUS: oneshot (2026-11-02)
"""Fusionne chaque personne RH avec son unique homonyme sans fiche RH : même nom, même prénom complet, aucun autre homonyme, paire non marquée distincte.

La personne RH est conservée (`merge_direction`). Son nom, en capitales comme dans l'export RH, prend la graphie de la personne absorbée quand celle-ci n'est pas en capitales. Chaque fusion est commitée seule.

Usage :
    uv run python -m interfaces.cli.oneshot.merge_hr_homonyms
    uv run python -m interfaces.cli.oneshot.merge_hr_homonyms --dry-run
"""

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, Row, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from interfaces.api.deps import person_service

log = setup_logger("merge_hr_homonyms", os.path.dirname(__file__))

_PAIRS = text(r"""
    WITH named AS (
        SELECT p.id, p.last_name, p.first_name, p.exclusion,
               p.last_name_normalized AS ln, p.first_name_normalized AS fn,
               EXISTS (SELECT 1 FROM hr_records r WHERE r.person_id = p.id) AS has_record
        FROM persons p
        WHERE p.first_name_normalized ~ '^[a-z]{2,}( [a-z]{2,})*$'
    ),
    pairs AS (
        SELECT ln, fn FROM named GROUP BY ln, fn
        HAVING count(*) = 2 AND count(*) FILTER (WHERE has_record) = 1
    )
    SELECT rh.id AS rh_id, rh.last_name AS rh_last_name, rh.first_name AS rh_first_name,
           other.id AS other_id, other.last_name AS other_last_name,
           other.first_name AS other_first_name
    FROM pairs
    JOIN named rh ON (rh.ln, rh.fn) = (pairs.ln, pairs.fn) AND rh.has_record
    JOIN named other ON (other.ln, other.fn) = (pairs.ln, pairs.fn) AND NOT other.has_record
    WHERE other.exclusion IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM distinct_persons d
          WHERE (d.person_id_a, d.person_id_b) IN ((rh.id, other.id), (other.id, rh.id))
      )
    ORDER BY rh.last_name, rh.first_name
""")


def _is_upper(*names: str | None) -> bool:
    return all((name or "").isupper() for name in names if name)


def merge_pair(conn: Connection, pair: Row) -> bool:
    """Fusionne la paire, et renvoie vrai quand la personne conservée prend le nom de l'absorbée."""
    persons = person_service(conn)
    kept, _ = persons.merge_person(pair.rh_id, pair.other_id)
    renamed = _is_upper(pair.rh_last_name, pair.rh_first_name) and not _is_upper(
        pair.other_last_name, pair.other_first_name
    )
    if renamed:
        persons.update_name(kept, pair.other_last_name, pair.other_first_name or "")
    return renamed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Rapport seul : n'écrit rien")
    args = parser.parse_args()

    outcomes: Counter[str] = Counter()
    with get_sync_engine().connect() as conn:
        pairs = conn.execute(_PAIRS).all()
        log.info("%s paires", len(pairs))
        for pair in pairs:
            renamed = merge_pair(conn, pair)
            outcomes["fusionnées"] += 1
            outcomes["renommées"] += renamed
            if not args.dry_run:
                conn.commit()
        if args.dry_run:
            conn.rollback()
    log.info("%s fusionnées, dont %s renommées", outcomes["fusionnées"], outcomes["renommées"])
    log.info("fusions appliquées" if not args.dry_run else "(dry-run, rien d'écrit)")


if __name__ == "__main__":
    main()
