"""Tests d'intégration pour `pipeline.transformation.publications.oa_status` : DOI à soumettre à Unpaywall et à doi.org, réponses, publications de ces DOI."""

from sqlalchemy import text

from pipeline.transformation.publications.oa_status import DOI_ORG, UNPAYWALL, OaStatusStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_doi_prefix
from tests.integration.helpers.sources import insert_source_record

STALENESS = 30  # seuil de péremption arbitraire pour ces tests


def _verdict(conn, doi, oa_status, *, days_ago):
    conn.execute(
        text(
            "INSERT INTO dois (doi, unpaywall_oa_status, unpaywall_checked_at)"
            " VALUES (:doi, CAST(:os AS oa_type), now() - make_interval(days => :d))"
        ),
        {"doi": doi, "os": oa_status, "d": days_ago},
    )


def _resolved_only(conn, doi, *, days_ago=0):
    conn.execute(
        text(
            "INSERT INTO dois (doi, registered_url, resolved_at)"
            " VALUES (:doi, 'https://x', now() - make_interval(days => :d))"
        ),
        {"doi": doi, "d": days_ago},
    )


class TestDoisToQuery:
    def test_seuls_les_doi_sans_verdict_ou_perimes(self, sa_sync_conn):
        """La péremption regarde seulement la date du verdict, nul compris."""
        for doi in ("10.1/n", "10.1/s", "10.1/f", "10.1/absent"):
            insert_publication(sa_sync_conn, doi=doi)
        insert_publication(sa_sync_conn, doi=None)
        _verdict(sa_sync_conn, "10.1/s", "gold", days_ago=999)
        _verdict(sa_sync_conn, "10.1/f", "gold", days_ago=1)
        _verdict(sa_sync_conn, "10.1/absent", None, days_ago=1)
        store = OaStatusStore(sa_sync_conn)

        dois = store.fetch_dois_to_query(UNPAYWALL, staleness_days=STALENESS)

        assert {"10.1/n", "10.1/s"} <= set(dois)
        assert not {"10.1/f", "10.1/absent"} & set(dois)
        assert store.count_dois_to_query(UNPAYWALL, staleness_days=STALENESS) == len(dois)

    def test_jamais_verifies_d_abord(self, sa_sync_conn):
        insert_publication(sa_sync_conn, doi="10.1/a")
        insert_publication(sa_sync_conn, doi="10.1/b")
        _verdict(sa_sync_conn, "10.1/a", "closed", days_ago=999)

        dois = [
            d
            for d in OaStatusStore(sa_sync_conn).fetch_dois_to_query(
                UNPAYWALL, staleness_days=STALENESS
            )
            if d in ("10.1/a", "10.1/b")
        ]

        assert dois == ["10.1/b", "10.1/a"]

    def test_chaque_service_a_sa_file(self, sa_sync_conn):
        """Une adresse lue laisse le DOI dans la file d'Unpaywall ; un verdict le laisse dans celle de doi.org."""
        insert_publication(sa_sync_conn, doi="10.1/r")
        insert_publication(sa_sync_conn, doi="10.1/v")
        insert_publication(sa_sync_conn, doi="10.1/old")
        _resolved_only(sa_sync_conn, "10.1/r")
        _verdict(sa_sync_conn, "10.1/v", "gold", days_ago=1)
        _resolved_only(sa_sync_conn, "10.1/old", days_ago=999)
        store = OaStatusStore(sa_sync_conn)

        unpaywall = set(store.fetch_dois_to_query(UNPAYWALL, staleness_days=STALENESS))
        doi_org = set(store.fetch_dois_to_query(DOI_ORG, staleness_days=STALENESS))

        assert {"10.1/r", "10.1/old"} <= unpaywall
        assert "10.1/v" not in unpaywall
        assert {"10.1/v", "10.1/old"} <= doi_org
        assert "10.1/r" not in doi_org

    def test_doi_datacite_ecartes_d_unpaywall_seulement(self, sa_sync_conn):
        """Un préfixe DataCite écarte le DOI d'Unpaywall ; un préfixe d'une autre agence ou pas encore résolu le garde. doi.org reçoit tous les DOI."""
        insert_doi_prefix(sa_sync_conn, "10.9001", ra="DataCite")
        insert_doi_prefix(sa_sync_conn, "10.9002", ra="mEDRA")
        for doi in ("10.9001/x", "10.9002/y", "10.9003/z"):
            insert_publication(sa_sync_conn, doi=doi)
        store = OaStatusStore(sa_sync_conn)

        unpaywall = set(store.fetch_dois_to_query(UNPAYWALL, staleness_days=STALENESS))
        doi_org = set(store.fetch_dois_to_query(DOI_ORG, staleness_days=STALENESS))

        assert {"10.9002/y", "10.9003/z"} <= unpaywall
        assert "10.9001/x" not in unpaywall
        assert {"10.9001/x", "10.9002/y", "10.9003/z"} <= doi_org

    def test_respecte_le_plafond(self, sa_sync_conn):
        for i in range(3):
            insert_publication(sa_sync_conn, doi=f"10.1/{i}")
        dois = OaStatusStore(sa_sync_conn).fetch_dois_to_query(
            DOI_ORG, limit=2, staleness_days=STALENESS
        )
        assert len(dois) == 2


class TestAnswers:
    def test_reponses_en_table_nul_compris(self, sa_sync_conn):
        _verdict(sa_sync_conn, "10.1/t", "gold", days_ago=1)
        _verdict(sa_sync_conn, "10.1/u", None, days_ago=1)
        _resolved_only(sa_sync_conn, "10.1/r")
        store = OaStatusStore(sa_sync_conn)
        dois = ["10.1/t", "10.1/u", "10.1/r", "10.1/z"]

        assert store.fetch_answers(UNPAYWALL, dois) == {"10.1/t": "gold", "10.1/u": None}
        assert store.fetch_answers(DOI_ORG, dois) == {"10.1/r": "https://x"}

    def test_une_reponse_reecrit_la_precedente_du_meme_service(self, sa_sync_conn):
        _verdict(sa_sync_conn, "10.1/v", "closed", days_ago=999)
        store = OaStatusStore(sa_sync_conn)
        store.record_answers(UNPAYWALL, [("10.1/v", "gold"), ("10.1/w", None)])
        store.record_answers(DOI_ORG, [("10.1/v", "https://e.org/v.pdf")])
        rows = sa_sync_conn.execute(
            text(
                "SELECT doi, unpaywall_oa_status::text, registered_url,"
                " unpaywall_checked_at > now() - interval '1 minute',"
                " resolved_at IS NOT NULL"
                " FROM dois WHERE doi IN ('10.1/v', '10.1/w') ORDER BY doi"
            )
        ).all()
        assert [tuple(r) for r in rows] == [
            ("10.1/v", "gold", "https://e.org/v.pdf", True, True),
            ("10.1/w", None, None, True, False),
        ]


class TestPublicationsOfDois:
    def test_donnees_du_statut(self, sa_sync_conn):
        publication = insert_publication(
            sa_sync_conn, doi="10.1/p", oa_status="closed", doc_type="ongoing_thesis"
        )
        record = insert_source_record(sa_sync_conn, publication, source="hal", source_id="hal-oa")
        sa_sync_conn.execute(
            text("INSERT INTO embargoes (source_record_id, until) VALUES (:id, NULL)"),
            {"id": record},
        )
        _verdict(sa_sync_conn, "10.1/p", "green", days_ago=1)

        [inputs] = OaStatusStore(sa_sync_conn).fetch_oa_inputs(["10.1/p"])

        assert (inputs.id, inputs.doi, inputs.oa_status) == (publication, "10.1/p", "closed")
        assert (inputs.embargoed, inputs.restricted, inputs.copies) == (True, True, [])
        assert inputs.unpaywall == "green"


class TestCounters:
    def test_count_publications_by_oa_status_groups_the_stock(self, sa_sync_conn):
        insert_publication(sa_sync_conn, doi="10.1/a", oa_status="gold")
        insert_publication(sa_sync_conn, doi="10.1/b", oa_status="gold")
        insert_publication(sa_sync_conn, doi="10.1/c", oa_status="closed")
        assert OaStatusStore(sa_sync_conn).count_publications_by_oa_status() == {
            "gold": 2,
            "closed": 1,
        }
