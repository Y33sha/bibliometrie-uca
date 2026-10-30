"""ROR des publications (`ror_organizations`, `ror_relations`, `publication_rors`) pour les tests d'intégration."""

from sqlalchemy import Connection, text

from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import refresh_structure_matviews


def insert_ror_tree(conn: Connection) -> None:
    """Insère un laboratoire `0lab00001`, en France, rattaché à son université `0univ0001`, et un laboratoire allemand `0ger00001`."""
    conn.execute(
        text("""
            INSERT INTO ror_organizations (ror_id, name, country_code, types, status) VALUES
                ('0univ0001', 'Université', 'fr', '{education}', 'active'),
                ('0lab00001', 'Laboratoire', 'fr', '{facility}', 'active'),
                ('0ger00001', 'Labor', 'de', '{facility}', 'active');
            INSERT INTO ror_relations (parent_ror_id, child_ror_id) VALUES ('0univ0001', '0lab00001');
        """)
    )


def insert_author(
    conn: Connection, publication: int, source_id: str, ror: str, person: int | None = None
) -> int:
    """Insère un auteur de `publication`, dont la contribution source cite `ror`, rattaché ou non à `person`. Renvoie l'`id` de la contribution source."""
    record = insert_source_record(conn, publication, source="openalex", source_id=source_id)
    source_contribution = insert_source_contribution(conn, record)
    contribution = align_source_contributions(conn, publication, [(source_contribution, record)])
    conn.execute(
        text("""
            UPDATE contributions SET roles = '{author}', person_id = :p,
                resolution_mode = CASE WHEN CAST(:p AS int) IS NULL THEN NULL
                                       ELSE CAST('manual' AS resolution_mode) END
            WHERE id = :c
        """),
        {"p": person, "c": contribution},
    )
    conn.execute(
        text(
            "INSERT INTO source_contribution_rors (source_contribution_id, ror_id) VALUES (:s, :r)"
        ),
        {"s": source_contribution, "r": ror},
    )
    return source_contribution


def refresh_publication_rors(conn: Connection) -> None:
    """Rafraîchit les vues des structures, puis `publication_rors`, qui en dépend."""
    refresh_structure_matviews(conn)
    conn.execute(text("REFRESH MATERIALIZED VIEW publication_rors"))
