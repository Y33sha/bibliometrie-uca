"""Le lookup `key_hash` (Python) doit rester aligné sur la colonne générée `author_identifying_keys.key_hash`.

Un désalignement ferait échouer silencieusement la résolution d'identité par `key_hash`.
"""

from sqlalchemy import text

from infrastructure.pipeline.normalize.authorships import IDENTITY_KEY_COLUMNS, key_hash_sql


def test_key_hash_sql_matches_generated_column(sa_sync_conn):
    """Le md5 recalculé par `key_hash_sql` égale la colonne générée, pour toutes les combinaisons de NULL."""
    conn = sa_sync_conn
    conn.execute(
        text(
            "INSERT INTO author_identifying_keys"
            " (author_name_normalized, last_name_normalized, first_name_normalized,"
            "  person_identifiers) VALUES "
            "('jean dupont', 'dupont', 'jean', '{\"orcid\": \"0000\"}'::jsonb), "
            "('marie curie', 'curie', NULL, NULL), "
            "('marie curie', NULL, NULL, NULL), "
            '(NULL, NULL, NULL, \'{"idref": "42"}\'::jsonb), '
            "(NULL, NULL, NULL, NULL)"
        )
    )
    mismatches = conn.execute(
        text(
            "SELECT count(*) FROM author_identifying_keys "
            "WHERE key_hash IS DISTINCT FROM " + key_hash_sql(IDENTITY_KEY_COLUMNS)
        )
    ).scalar_one()
    assert mismatches == 0
