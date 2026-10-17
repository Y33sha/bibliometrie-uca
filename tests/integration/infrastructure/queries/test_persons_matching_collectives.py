"""La cascade personnes ignore les signatures collectives, et détache celles qui ont une personne sans épinglage."""

from sqlalchemy import text

from pipeline.transformation.persons.matching import PersonsMatchingQueries
from tests.integration.helpers.authorships import insert_confirmed_authorship
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication

_ORCID = "0000-0002-9876-5432"


def _signature(conn, raw_name, *, collective, source_id, person_id=None, orcid=None):
    """Signature crossref du périmètre, seule dans sa notice. Retourne son identifiant."""
    sd = insert_source_publication(
        conn, insert_publication(conn), source="crossref", source_id=source_id
    )
    return insert_signature(
        conn,
        sd,
        source="crossref",
        raw_author_name=raw_name,
        author_name_normalized=raw_name.lower(),
        person_identifiers={"orcid": orcid} if orcid else None,
        person_id=person_id,
        in_perimeter=True,
        collective=collective,
    )


def _person_id(conn, signature_id):
    return conn.execute(
        text("SELECT person_id FROM source_authorships WHERE id = :id"), {"id": signature_id}
    ).scalar_one()


def test_signature_collective_absente_des_candidates(sa_sync_conn):
    _signature(sa_sync_conn, "Zeta Consortium", collective=True, source_id="c-coll-1")
    _signature(sa_sync_conn, "Jean Zetaindividu", collective=False, source_id="c-coll-2")

    names = {
        r.name.display() for r in PersonsMatchingQueries().fetch_unlinked_authorships(sa_sync_conn)
    }

    assert "Jean Zetaindividu" in names
    assert "Zeta Consortium" not in names


def test_signature_collective_detachee_sauf_epinglee(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Consortium", first_name="Zeta")
    detached = _signature(
        conn, "Zeta Consortium", collective=True, source_id="c-coll-3", person_id=person
    )
    pinned = _signature(
        conn, "Zeta Consortium", collective=True, source_id="c-coll-4", person_id=person
    )
    insert_confirmed_authorship(conn, pinned, person_id=person)
    individual = _signature(
        conn, "Jean Zetaindividu", collective=False, source_id="c-coll-5", person_id=person
    )

    assert PersonsMatchingQueries().detach_collective_signatures(conn) == 1
    assert [_person_id(conn, s) for s in (detached, pinned, individual)] == [None, person, person]


def test_signature_collective_ne_vote_pas(sa_sync_conn):
    _signature(sa_sync_conn, "Zeta Consortium", collective=True, source_id="c-coll-6", orcid=_ORCID)
    _signature(
        sa_sync_conn, "Jean Zetaindividu", collective=False, source_id="c-coll-7", orcid=_ORCID
    )

    votes = PersonsMatchingQueries().fetch_identifier_votes(sa_sync_conn, "orcid")

    assert votes[_ORCID] == {"jean zetaindividu": 1}
