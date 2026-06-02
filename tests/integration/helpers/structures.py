"""Helper de test : matérialiser des liens authorship ↔ structure.

`authorship_structures` est une `MATERIALIZED VIEW` dérivée de
`source_authorship_structures` (via `source_authorships.authorship_id`) — les
tests ne peuvent plus l'`INSERT` directement. Ce helper sème la chaîne source
minimale puis rafraîchit la matview (transactionnel : rollback avec le test).
"""

import itertools

from sqlalchemy import text

_seq = itertools.count(1)


def add_authorship_structure(conn, authorship_id: int, structure_id: int) -> None:
    """Lie `authorship_id` à `structure_id` dans la matview `authorship_structures`
    (via une chaîne source minimale), puis rafraîchit la matview."""
    n = next(_seq)
    sp_id = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, pub_year) "
            "VALUES ('hal', :sid, 'X', 2024) RETURNING id"
        ),
        {"sid": f"as-test-{n}"},
    ).scalar_one()
    sa_id = conn.execute(
        text(
            "INSERT INTO source_authorships "
            "(source, source_publication_id, author_position, authorship_id) "
            "VALUES ('hal', :sp, 0, :aid) RETURNING id"
        ),
        {"sp": sp_id, "aid": authorship_id},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO source_authorship_structures (source_authorship_id, structure_id) "
            "VALUES (:sa, :s)"
        ),
        {"sa": sa_id, "s": structure_id},
    )
    conn.execute(text("REFRESH MATERIALIZED VIEW authorship_structures"))
