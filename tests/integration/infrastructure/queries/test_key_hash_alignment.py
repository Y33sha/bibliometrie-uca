"""Le lookup `key_hash` (Python) doit rester aligné sur la colonne générée `author_identifying_keys.key_hash`.

Un désalignement ferait échouer silencieusement la résolution d'identité par `key_hash`.
"""

from sqlalchemy import text

from infrastructure.queries.pipeline.normalize.authorships import key_hash_sql


def test_key_hash_sql_matches_generated_column(sa_sync_conn):
    """Le md5 recalculé par `key_hash_sql` égale la colonne générée, pour toutes les combinaisons de NULL."""
    conn = sa_sync_conn
    conn.execute(
        text(
            "INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers) VALUES "
            "('jean dupont', '{\"orcid\": \"0000\"}'::jsonb), "
            "('marie curie', NULL), "
            '(NULL, \'{"idref": "42"}\'::jsonb), '
            "(NULL, NULL)"
        )
    )
    mismatches = conn.execute(
        text(
            "SELECT count(*) FROM author_identifying_keys "
            "WHERE key_hash IS DISTINCT FROM "
            + key_hash_sql("author_name_normalized", "person_identifiers")
        )
    ).scalar_one()
    assert mismatches == 0
