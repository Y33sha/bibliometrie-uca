"""La cascade personnes ignore les identifiants qu'une signature neutralise."""

import json

from sqlalchemy import text

from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
from tests.integration.helpers.authorships import upsert_identity

_ORCID = "0000-0001-2345-6789"


def _signature(conn, neutralized):
    """Signature du périmètre, non rattachée, portant un ORCID et la carte `neutralized`."""
    pub = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
    ).scalar_one()
    sd = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('crossref', 'c-neutralisation', 'X', :p) RETURNING id"
        ),
        {"p": pub},
    ).scalar_one()
    identity_id = upsert_identity(
        conn, author_name_normalized="dupont jean", person_identifiers={"orcid": _ORCID}
    )
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, in_perimeter,
                 raw_author_name, identity_id, neutralized_identifiers)
            VALUES ('crossref', :sd, 0, TRUE, 'Jean Neutralisation', :iid, CAST(:neu AS jsonb))
        """),
        {"sd": sd, "iid": identity_id, "neu": json.dumps(neutralized) if neutralized else None},
    )


def _orcid_projete(conn):
    rows = PgPersonsMatchingQueries().fetch_unlinked_authorships(conn)
    [row] = [r for r in rows if r.full_name == "Jean Neutralisation"]
    return row.orcid


def test_orcid_neutralise_absent_de_la_projection(sa_sync_conn):
    _signature(sa_sync_conn, {"orcid": "shared"})
    assert _orcid_projete(sa_sync_conn) is None


def test_orcid_non_neutralise_present_dans_la_projection(sa_sync_conn):
    _signature(sa_sync_conn, None)
    assert _orcid_projete(sa_sync_conn) == _ORCID
