"""Le type JSONB du projet écrit `None` en NULL SQL, jamais en JSON `null`.

Les deux se relisent en `None` côté Python, mais SQL les distingue : une colonne qui mélange les deux formes échappe aux contraintes et aux index qui raisonnent sur NULL.
"""

from sqlalchemy import bindparam, text

from infrastructure.db.jsonb import Jsonb
from pipeline.ingestion.common.source_contribution_store import key_hash_sql


def test_parametre_lie_none_donne_null_sql(sa_sync_conn):
    stmt = text("SELECT jsonb_typeof(CAST(:p AS jsonb)) AS forme").bindparams(
        bindparam("p", type_=Jsonb)
    )
    assert sa_sync_conn.execute(stmt, {"p": None}).scalar_one() is None


def test_colonne_de_table_none_donne_null_sql(sa_sync_conn):
    """Des informations du contributeur sans identifiant s'écrivent avec un `identifiers` NULL."""
    sa_sync_conn.execute(
        text(
            "INSERT INTO contributor_information (last_name_normalized, identifiers) "
            "VALUES ('sans identifiant', :p)"
        ).bindparams(bindparam("p", type_=Jsonb)),
        {"p": None},
    )
    forme = sa_sync_conn.execute(
        text(
            "SELECT jsonb_typeof(identifiers) FROM contributor_information "
            "WHERE last_name_normalized = 'sans identifiant'"
        )
    ).scalar_one()
    assert forme is None


def test_identite_sans_identifiant_ne_se_dedouble_pas(sa_sync_conn):
    """Une contribution source sans identifiant rejoint les informations du contributeur NULL de même nom, au lieu d'en créer d'autres.

    La contrainte d'unicité `NULLS NOT DISTINCT` de la table l'assure. Un JSON `null` la met en défaut : il diffère de NULL, donc la contrainte le laisse passer, et le `key_hash` de la ligne en double diffère de celui que la recherche par `key_hash` calcule.
    """
    sa_sync_conn.execute(
        text(
            "INSERT INTO contributor_information"
            " (last_name_normalized, first_name_normalized, identifiers)"
            " VALUES ('durand', 'j', NULL)"
        )
    )
    sa_sync_conn.execute(
        text("""
            INSERT INTO contributor_information
                (last_name_normalized, first_name_normalized, identifiers)
            VALUES (:nom, :prenom, :p)
            ON CONFLICT (last_name_normalized, first_name_normalized, identifiers)
            DO NOTHING
        """).bindparams(bindparam("p", type_=Jsonb)),
        {"nom": "durand", "prenom": "j", "p": None},
    )

    lignes = sa_sync_conn.execute(
        text("SELECT count(*) FROM contributor_information WHERE last_name_normalized = 'durand'")
    ).scalar_one()
    assert lignes == 1

    lookup = text(
        "SELECT count(*) FROM contributor_information WHERE key_hash = "
        + key_hash_sql([":nom", ":prenom", ":p"])
    ).bindparams(bindparam("p", type_=Jsonb))
    assert (
        sa_sync_conn.execute(lookup, {"nom": "durand", "prenom": "j", "p": None}).scalar_one() == 1
    )
