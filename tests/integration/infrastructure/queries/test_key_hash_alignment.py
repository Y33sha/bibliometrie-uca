"""Colonnes générées de `contributor_information` : `key_hash` concorde avec l'expression calculée par `key_hash_sql`, `author_name_normalized` réunit prénom et nom.

Un écart sur `key_hash` ferait échouer sans erreur la recherche des informations du contributeur par `key_hash`.
"""

from sqlalchemy import text

from pipeline.ingestion.common.source_contribution_store import (
    CONTRIBUTOR_INFORMATION_KEY_COLUMNS,
    key_hash_sql,
)


def test_key_hash_sql_matches_generated_column(sa_sync_conn):
    """Le md5 recalculé par `key_hash_sql` égale la colonne générée, pour toutes les combinaisons de NULL."""
    conn = sa_sync_conn
    conn.execute(
        text(
            "INSERT INTO contributor_information"
            " (last_name_normalized, first_name_normalized, identifiers) VALUES "
            "('dupont', 'jean', '{\"orcid\": \"0000\"}'::jsonb), "
            "('curie', NULL, NULL), "
            "('', NULL, '{\"idref\": \"42\"}'::jsonb), "
            "('', NULL, NULL)"
        )
    )
    mismatches = conn.execute(
        text(
            "SELECT count(*) FROM contributor_information "
            "WHERE key_hash IS DISTINCT FROM " + key_hash_sql(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)
        )
    ).scalar_one()
    assert mismatches == 0


def test_forme_prenom_nom_calculee(sa_sync_conn):
    """`author_name_normalized` réunit prénom et nom, sans les parties vides."""
    sa_sync_conn.execute(
        text(
            "INSERT INTO contributor_information (last_name_normalized, first_name_normalized) "
            "VALUES ('dupont', 'jean'), ('curie', NULL), ('', 'z bardacova')"
        )
    )
    formes = (
        sa_sync_conn.execute(
            text("SELECT author_name_normalized FROM contributor_information ORDER BY id")
        )
        .scalars()
        .all()
    )
    assert formes == ["jean dupont", "curie", "z bardacova"]
