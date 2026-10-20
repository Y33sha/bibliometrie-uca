"""La cascade personnes ignore les contributions sources collectives."""

from pipeline.transformation.persons.identifier_arbitration import fetch_identifier_votes
from pipeline.transformation.persons.loading import fetch_unlinked_contributions
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0002-9876-5432"


def _source_contribution(conn, raw_name, *, collective, source_id, orcid=None):
    """Contribution source crossref du périmètre, seule dans son enregistrement source. Retourne son identifiant."""
    source_record = insert_source_record(
        conn, insert_publication(conn), source="crossref", source_id=source_id
    )
    return insert_source_contribution(
        conn,
        source_record,
        source="crossref",
        raw_author_name=raw_name,
        author_name_normalized=raw_name.lower(),
        identifiers={"orcid": orcid} if orcid else None,
        in_perimeter=True,
        collective=collective,
    )


def test_contribution_source_collective_absente_des_candidates(sa_sync_conn):
    _source_contribution(sa_sync_conn, "Zeta Consortium", collective=True, source_id="c-coll-1")
    _source_contribution(sa_sync_conn, "Jean Zetaindividu", collective=False, source_id="c-coll-2")

    names = {r.name.display() for r in fetch_unlinked_contributions(sa_sync_conn)}

    assert "Jean Zetaindividu" in names
    assert "Zeta Consortium" not in names


def test_contribution_source_collective_ne_vote_pas(sa_sync_conn):
    _source_contribution(
        sa_sync_conn, "Zeta Consortium", collective=True, source_id="c-coll-6", orcid=_ORCID
    )
    _source_contribution(
        sa_sync_conn, "Jean Zetaindividu", collective=False, source_id="c-coll-7", orcid=_ORCID
    )

    votes = fetch_identifier_votes(sa_sync_conn, "orcid")

    assert votes[_ORCID] == {"jean zetaindividu": 1}
