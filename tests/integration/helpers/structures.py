"""Helper de test : matérialiser des liens authorship ↔ structure.

`authorship_structures` et `source_authorship_structures` sont des
MATERIALIZED VIEW (migrations a2c6e4f8b1d7, e8f1a3c5d7b9) — les tests ne peuvent
plus les `INSERT` directement. Ce helper sème la chaîne source minimale
(source_authorship → adresse → address_structures, structure rattachée au
périmètre d'affiliation) puis rafraîchit les deux matviews (transactionnel :
rollback avec le test).
"""

import itertools

from sqlalchemy import text

_seq = itertools.count(1)


def refresh_structure_matviews(conn) -> None:
    """Rafraîchit `source_authorship_structures` puis `authorship_structures`
    (matview-sur-matview, ordre imposé). Non-concurrent = transactionnel, donc
    compatible avec l'isolation par rollback des tests. En prod ces matviews sont
    maintenues par le pipeline ; les tests les rafraîchissent explicitement."""
    conn.execute(text("REFRESH MATERIALIZED VIEW source_authorship_structures"))
    conn.execute(text("REFRESH MATERIALIZED VIEW authorship_structures"))


def add_authorship_structure(conn, authorship_id: int, structure_id: int) -> None:
    """Lie `authorship_id` à `structure_id` dans la matview `authorship_structures`
    (via une chaîne source minimale + appartenance au périmètre d'affiliation),
    puis rafraîchit `source_authorship_structures` et `authorship_structures`."""
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
    addr_id = conn.execute(
        text("INSERT INTO addresses (raw_text, normalized_text) VALUES (:t, :t) RETURNING id"),
        {"t": f"as-test-addr-{n}"},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
            "VALUES (:sa, :a)"
        ),
        {"sa": sa_id, "a": addr_id},
    )
    conn.execute(
        text(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (:a, :s, NULL)"
        ),
        {"a": addr_id, "s": structure_id},
    )
    # La matview SAS filtre sur le périmètre d'affiliation : garantir qu'un
    # périmètre d'affiliation existe (config + ligne perimeters) et y rattacher
    # la structure pour que le lien apparaisse. Coopère avec les tests qui
    # configurent déjà `perimeter_affiliations` (ON CONFLICT DO NOTHING).
    conn.execute(
        text(
            "INSERT INTO config (key, value) VALUES ('perimeter_affiliations', '\"uca_wide\"') "
            "ON CONFLICT (key) DO NOTHING"
        )
    )
    perim_id = conn.execute(
        text("""
            INSERT INTO perimeters (code, name)
            SELECT value #>> '{}', 'test affiliation perimeter'
            FROM config WHERE key = 'perimeter_affiliations'
            ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
            RETURNING id
        """)
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO perimeter_structures (perimeter_id, structure_id) "
            "VALUES (:p, :s) ON CONFLICT DO NOTHING"
        ),
        {"p": perim_id, "s": structure_id},
    )
    refresh_structure_matviews(conn)
