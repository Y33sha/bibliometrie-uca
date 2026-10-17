"""La cascade personnes ignore les signatures collectives."""

from pipeline.transformation.persons.matching import PersonsMatchingQueries
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication

_ORCID = "0000-0002-9876-5432"


def _signature(conn, raw_name, *, collective, source_id, orcid=None):
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
        in_perimeter=True,
        collective=collective,
    )


def test_signature_collective_absente_des_candidates(sa_sync_conn):
    _signature(sa_sync_conn, "Zeta Consortium", collective=True, source_id="c-coll-1")
    _signature(sa_sync_conn, "Jean Zetaindividu", collective=False, source_id="c-coll-2")

    names = {
        r.name.display() for r in PersonsMatchingQueries().fetch_unlinked_authorships(sa_sync_conn)
    }

    assert "Jean Zetaindividu" in names
    assert "Zeta Consortium" not in names


def test_signature_collective_ne_vote_pas(sa_sync_conn):
    _signature(sa_sync_conn, "Zeta Consortium", collective=True, source_id="c-coll-6", orcid=_ORCID)
    _signature(
        sa_sync_conn, "Jean Zetaindividu", collective=False, source_id="c-coll-7", orcid=_ORCID
    )

    votes = PersonsMatchingQueries().fetch_identifier_votes(sa_sync_conn, "orcid")

    assert votes[_ORCID] == {"jean zetaindividu": 1}
