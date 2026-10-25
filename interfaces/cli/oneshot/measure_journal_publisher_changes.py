# STATUS: oneshot (2026-10-24)
"""Revues qui changent d'éditeur, d'après l'éditeur du préfixe DOI de leurs publications. Lecture seule sur la base.

L'éditeur d'un préfixe DOI Crossref est celui de `doi_prefixes`. Une revue change d'éditeur quand deux éditeurs de préfixe y couvrent des périodes disjointes, avec chacun au moins `--min` publications. Le rapport donne :

- le nombre de ces revues, de leurs publications, et des publications dont l'éditeur de préfixe diffère de l'éditeur de la revue ;
- la liste de ces revues, avec leurs éditeurs de préfixe et leurs années ;
- les autres revues de même titre normalisé, candidates au doublon ;
- les titres normalisés que portent plusieurs revues d'éditeurs distincts.

Usage :
    python -m interfaces.cli.oneshot.measure_journal_publisher_changes [--min 2]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("measure_journal_publisher_changes", os.path.dirname(__file__))

_TABLES = (
    """
    CREATE TEMP TABLE prefix_publications AS
    SELECT p.id, p.serial_id, p.publication_year AS year,
           dp.publisher_id AS prefix_publisher_id, j.publisher_id AS serial_publisher_id
    FROM publications p
    JOIN serials j ON j.id = p.serial_id
    JOIN doi_prefixes dp ON dp.prefix = split_part(p.doi, '/', 1) AND dp.ra = 'Crossref'
    WHERE p.doi IS NOT NULL AND dp.publisher_id IS NOT NULL
    """,
    """
    CREATE TEMP TABLE serial_prefix_publishers AS
    SELECT serial_id, prefix_publisher_id, count(*) AS publications, min(year) AS first_year, max(year) AS last_year
    FROM prefix_publications
    GROUP BY 1, 2
    HAVING count(*) >= :min
    """,
    """
    CREATE TEMP TABLE changing_serials AS
    SELECT DISTINCT a.serial_id
    FROM serial_prefix_publishers a
    JOIN serial_prefix_publishers b
      ON b.serial_id = a.serial_id AND b.prefix_publisher_id > a.prefix_publisher_id
    WHERE a.last_year < b.first_year OR b.last_year < a.first_year
    """,
)

_SUMMARY = """
    SELECT (SELECT count(DISTINCT serial_id) FROM prefix_publications) AS serials,
           (SELECT count(*) FROM changing_serials) AS changing,
           count(*) AS publications,
           count(*) FILTER (WHERE prefix_publisher_id IS DISTINCT FROM serial_publisher_id) AS mismatched
    FROM prefix_publications
    WHERE serial_id IN (SELECT serial_id FROM changing_serials)
"""

_CHANGING = """
    SELECT j.id, j.title, coalesce(jpub.name, '?') AS serial_publisher,
           string_agg(pub.name || ' ' || jp.publications || ' [' || jp.first_year || '-' || jp.last_year || ']',
                      ' | ' ORDER BY jp.first_year) AS prefix_publishers
    FROM changing_serials c
    JOIN serials j ON j.id = c.serial_id
    LEFT JOIN publishers jpub ON jpub.id = j.publisher_id
    JOIN serial_prefix_publishers jp ON jp.serial_id = j.id
    JOIN publishers pub ON pub.id = jp.prefix_publisher_id
    GROUP BY j.id, j.title, jpub.name
    ORDER BY sum(jp.publications) DESC
"""

_SAME_TITLE = """
    SELECT j.id, j.title, other.id, coalesce(opub.name, '?'), other.publication_count
    FROM changing_serials c
    JOIN serials j ON j.id = c.serial_id
    JOIN serials other ON other.title_normalized = j.title_normalized AND other.id <> j.id
    LEFT JOIN publishers opub ON opub.id = other.publisher_id
    ORDER BY j.title
"""

_SHARED_TITLES = """
    SELECT count(*) AS titles, sum(serials) AS serials
    FROM (
        SELECT title_normalized, count(*) AS serials
        FROM serials
        GROUP BY 1
        HAVING count(DISTINCT publisher_id) > 1
    ) t
"""


def report(conn: Connection, min_publications: int) -> None:
    for statement in _TABLES:
        conn.execute(text(statement), {"min": min_publications})
    serials, changing, publications, mismatched = conn.execute(text(_SUMMARY)).one()
    log.info("Revues à publications Crossref : %d", serials)
    log.info(
        "Revues qui changent d'éditeur : %d, %d publications, dont %d d'un éditeur de préfixe autre que celui de la revue",
        changing,
        publications or 0,
        mismatched or 0,
    )
    for serial_id, title, serial_publisher, prefix_publishers in conn.execute(text(_CHANGING)):
        log.info("  %d %s (%s) : %s", serial_id, title, serial_publisher, prefix_publishers)

    same_title = conn.execute(text(_SAME_TITLE)).all()
    log.info("Revues de même titre qu'une revue qui change d'éditeur : %d", len(same_title))
    for serial_id, title, other_id, other_publisher, other_count in same_title:
        log.info(
            "  %d %s ↔ %d (%s, %d publications)",
            serial_id,
            title,
            other_id,
            other_publisher,
            other_count,
        )

    titles, shared = conn.execute(text(_SHARED_TITLES)).one()
    log.info(
        "Titres normalisés portés par des revues d'éditeurs distincts : %d, %d revues",
        titles,
        shared or 0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min", type=int, default=2, help="publications minimales par éditeur de préfixe"
    )
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        report(conn, args.min)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
