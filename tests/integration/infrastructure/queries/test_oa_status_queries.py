"""Tests d'intégration pour `pipeline.transformation.publications.oa_status_queries` : DOI à vérifier sur Unpaywall, verdicts, publications de ces DOI."""

from sqlalchemy import text

from pipeline.transformation.publications.oa_status_queries import OaSignal, OaStatusQueries
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_publication

_Q = OaStatusQueries()

STALENESS = 30  # seuil de péremption arbitraire pour ces tests


def _verdict(conn, doi, oa_status, *, days_ago):
    conn.execute(
        text(
            "INSERT INTO unpaywall (doi, oa_status, checked_at)"
            " VALUES (:doi, CAST(:os AS oa_type), now() - make_interval(days => :d))"
        ),
        {"doi": doi, "os": oa_status, "d": days_ago},
    )


class TestDoisToCheck:
    def test_seuls_les_doi_sans_verdict_ou_perimes(self, sa_sync_conn):
        """La péremption regarde seulement la date du verdict, nul compris."""
        for doi in ("10.1/n", "10.1/s", "10.1/f", "10.1/absent"):
            insert_publication(sa_sync_conn, doi=doi)
        insert_publication(sa_sync_conn, doi=None)
        _verdict(sa_sync_conn, "10.1/s", "gold", days_ago=999)
        _verdict(sa_sync_conn, "10.1/f", "gold", days_ago=1)
        _verdict(sa_sync_conn, "10.1/absent", None, days_ago=1)

        dois = _Q.fetch_dois_to_check(sa_sync_conn, staleness_days=STALENESS)

        assert {"10.1/n", "10.1/s"} <= set(dois)
        assert not {"10.1/f", "10.1/absent"} & set(dois)
        assert _Q.count_dois_to_check(sa_sync_conn, staleness_days=STALENESS) == len(dois)

    def test_jamais_verifies_d_abord(self, sa_sync_conn):
        insert_publication(sa_sync_conn, doi="10.1/a")
        insert_publication(sa_sync_conn, doi="10.1/b")
        _verdict(sa_sync_conn, "10.1/a", "closed", days_ago=999)

        dois = [
            d
            for d in _Q.fetch_dois_to_check(sa_sync_conn, staleness_days=STALENESS)
            if d in ("10.1/a", "10.1/b")
        ]

        assert dois == ["10.1/b", "10.1/a"]

    def test_respecte_le_plafond(self, sa_sync_conn):
        for i in range(3):
            insert_publication(sa_sync_conn, doi=f"10.1/{i}")
        assert len(_Q.fetch_dois_to_check(sa_sync_conn, limit=2, staleness_days=STALENESS)) == 2


class TestVerdicts:
    def test_un_verdict_reecrit_le_precedent(self, sa_sync_conn):
        _verdict(sa_sync_conn, "10.1/v", "closed", days_ago=999)
        _Q.record_verdicts(sa_sync_conn, [("10.1/v", "gold"), ("10.1/w", None)])
        rows = sa_sync_conn.execute(
            text(
                "SELECT doi, oa_status::text, checked_at > now() - interval '1 minute'"
                " FROM unpaywall WHERE doi IN ('10.1/v', '10.1/w') ORDER BY doi"
            )
        ).all()
        assert [tuple(r) for r in rows] == [("10.1/v", "gold", True), ("10.1/w", None, True)]


class TestPublicationsOfDois:
    def test_statuts_des_notices(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn, doi="10.1/p", oa_status="closed")
        insert_source_publication(
            sa_sync_conn, pub, source="hal", source_id="hal-oa", oa_status="green"
        )
        insert_source_publication(
            sa_sync_conn, pub, source="openalex", source_id="W-oa", oa_status=None
        )

        [inputs] = _Q.fetch_oa_inputs(sa_sync_conn, ["10.1/p"])

        assert (inputs.id, inputs.doi, inputs.oa_status) == (pub, "10.1/p", "closed")
        assert inputs.signals == [OaSignal("hal", "green"), OaSignal("openalex", None)]


class TestCounters:
    def test_count_publications_by_oa_status_groups_the_stock(self, sa_sync_conn):
        insert_publication(sa_sync_conn, doi="10.1/a", oa_status="gold")
        insert_publication(sa_sync_conn, doi="10.1/b", oa_status="gold")
        insert_publication(sa_sync_conn, doi="10.1/c", oa_status="closed")
        assert _Q.count_publications_by_oa_status(sa_sync_conn) == {"gold": 2, "closed": 1}
