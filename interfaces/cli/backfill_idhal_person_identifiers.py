#!/usr/bin/env python3
"""
Backfill : insère dans person_identifiers les identifiants (idHAL, ORCID, IdRef)
présents dans source_persons mais absents de person_identifiers.

Les conflits (même identifiant attribué à une autre personne avec statut
pending ou confirmed) sont ignorés et loggés.
Les identifiants avec statut rejected sont réattribués (via add_identifier).
"""

import os

from infrastructure.db.connection import get_connection
from application.persons import add_identifier
from infrastructure.log import setup_logger

log = setup_logger(
    "backfill_identifiers", os.path.join(os.path.dirname(__file__), "../processing/logs")
)

# (id_type, colonne source_persons, filtre source optionnel)
IDENTIFIERS = [
    ("idhal", "sa.source_ids->>'idhal'", "sa.source = 'hal'"),
    ("orcid", "sa.orcid", None),
    ("idref", "sa.idref", None),
]


def backfill_identifier(cur, conn, id_type, column, source_filter):
    """Backfill un type d'identifiant."""
    where_source = f"AND {source_filter}" if source_filter else ""

    cur.execute(
        f"""
        SELECT DISTINCT sa.person_id, {column} AS id_value
        FROM source_persons sa
        WHERE sa.person_id IS NOT NULL
          AND {column} IS NOT NULL
          {where_source}
          AND NOT EXISTS (
              SELECT 1 FROM person_identifiers pi
              WHERE pi.person_id = sa.person_id
                AND pi.id_type = %s
                AND pi.id_value = {column}
          )
    """,
        (id_type,),
    )
    rows = cur.fetchall()

    if not rows:
        log.info("%s : rien à faire", id_type)
        return

    inserted = 0
    for person_id, id_value in rows:
        add_identifier(cur, person_id, id_type, id_value, source="hal")
        inserted += 1

    conn.commit()
    log.info("%s : %d insérés", id_type, inserted)

    # Vérification des restants (conflits)
    cur.execute(
        f"""
        SELECT COUNT(*) FROM source_persons sa
        WHERE sa.person_id IS NOT NULL
          AND {column} IS NOT NULL
          {where_source}
          AND NOT EXISTS (
              SELECT 1 FROM person_identifiers pi
              WHERE pi.person_id = sa.person_id
                AND pi.id_type = %s
                AND pi.id_value = {column}
          )
    """,
        (id_type,),
    )
    remaining = cur.fetchone()[0]
    if remaining:
        log.warning("%s : encore %d non propagés (conflits)", id_type, remaining)


def main():
    conn = get_connection()
    cur = conn.cursor()

    for id_type, column, source_filter in IDENTIFIERS:
        backfill_identifier(cur, conn, id_type, column, source_filter)

    conn.close()


if __name__ == "__main__":
    main()
