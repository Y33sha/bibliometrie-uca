"""La cascade personnes ignore les identifiants qu'une signature neutralise."""

import json

from sqlalchemy import text

from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
from tests.integration.helpers.authorships import upsert_identity

_ORCID = "0000-0001-2345-6789"


def _signature(conn, neutralized, *, name="dupont jean", source_id="c-neutralisation"):
    """Signature crossref du périmètre, non rattachée, portant un ORCID et la carte `neutralized`."""
    pub = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
    ).scalar_one()
    sd = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('crossref', :sid, 'X', :p) RETURNING id"
        ),
        {"sid": source_id, "p": pub},
    ).scalar_one()
    identity_id = upsert_identity(
        conn, author_name_normalized=name, person_identifiers={"orcid": _ORCID}
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


def test_signature_neutralisee_ne_vote_pas(sa_sync_conn):
    _signature(sa_sync_conn, None, name="dupont jean", source_id="c-vote-1")
    _signature(sa_sync_conn, {"orcid": "shared"}, name="martin pierre", source_id="c-vote-2")
    votes = PgPersonsMatchingQueries().fetch_identifier_votes(sa_sync_conn, "orcid", [_ORCID])
    assert votes == {_ORCID: {"dupont jean": 1}}
