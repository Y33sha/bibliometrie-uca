"""Le type JSONB du projet écrit `None` en NULL SQL, jamais en JSON `null`.

Les deux se relisent en `None` côté Python, mais SQL les distingue : une colonne qui mélange les
deux formes échappe aux contraintes et aux index qui raisonnent sur NULL.
"""

from sqlalchemy import bindparam, text

from infrastructure.db.jsonb import Jsonb
from infrastructure.pipeline.normalize.authorships import key_hash_sql


def test_parametre_lie_none_donne_null_sql(sa_sync_conn):
    stmt = text("SELECT jsonb_typeof(CAST(:p AS jsonb)) AS forme").bindparams(
        bindparam("p", type_=Jsonb)
    )
    assert sa_sync_conn.execute(stmt, {"p": None}).scalar_one() is None


def test_colonne_de_table_none_donne_null_sql(sa_sync_conn):
    """Une identité d'auteur sans identifiant s'écrit avec un `person_identifiers` NULL."""
    sa_sync_conn.execute(
        text(
            "INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers) "
            "VALUES ('sans identifiant', :p)"
        ).bindparams(bindparam("p", type_=Jsonb)),
        {"p": None},
    )
    forme = sa_sync_conn.execute(
        text(
            "SELECT jsonb_typeof(person_identifiers) FROM author_identifying_keys "
            "WHERE author_name_normalized = 'sans identifiant'"
        )
    ).scalar_one()
    assert forme is None


def test_identite_sans_identifiant_ne_se_dedouble_pas(sa_sync_conn):
    """Une signature sans identifiant rejoint l'identité NULL de même nom, au lieu d'en créer une.

    C'est ce que porte l'unique `NULLS NOT DISTINCT` de la table, et ce qu'un JSON `null` mettait
    en défaut : il n'est pas NULL, l'unique le laissait passer, et le `key_hash` de la ligne en
    double différait de celui que le rapprochement recherche.
    """
    sa_sync_conn.execute(
        text(
            "INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers) "
            "VALUES ('durand j', NULL)"
        )
    )
    sa_sync_conn.execute(
        text("""
            INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers)
            VALUES (:nom, :p)
            ON CONFLICT (author_name_normalized, person_identifiers) DO NOTHING
        """).bindparams(bindparam("p", type_=Jsonb)),
        {"nom": "durand j", "p": None},
    )

    lignes = sa_sync_conn.execute(
        text(
            "SELECT count(*) FROM author_identifying_keys WHERE author_name_normalized = 'durand j'"
        )
    ).scalar_one()
    assert lignes == 1

    lookup = text(
        "SELECT count(*) FROM author_identifying_keys WHERE key_hash = "
        + key_hash_sql(":nom", ":p")
    ).bindparams(bindparam("p", type_=Jsonb))
    assert sa_sync_conn.execute(lookup, {"nom": "durand j", "p": None}).scalar_one() == 1
