"""Tests d'intégration pour `pipeline.transformation.publications.oa_status` : DOI à soumettre à Unpaywall et à doi.org, réponses, publications mises en file."""

from itertools import count

from sqlalchemy import text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from pipeline.transformation.publications.oa_status import DOI_ORG, UNPAYWALL, OaStatusStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.serials import insert_doi_prefix
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

STALENESS = 30  # seuil de péremption arbitraire pour ces tests

_ids = count()


def _candidate(conn, doi: str) -> int:
    """Insère une publication et son enregistrement source Crossref, de DOI `primary` `doi`. Renvoie la publication."""
    publication = insert_publication(conn, doi=doi)
    insert_source_record(
        conn, publication, source="crossref", source_id=f"cr-{next(_ids)}", doi=doi
    )
    return publication


def _record_with_dois(conn, publication: int | None, *dois: str) -> int:
    """Insère un enregistrement source HAL aux DOI `secondary` `dois`. Renvoie l'enregistrement source."""
    return insert_source_record(
        conn,
        publication,
        source="hal",
        source_id=f"hal-{next(_ids)}",
        identifiers=[
            SourceIdentifier(SourceIdentifierType.DOI, doi, SourceIdentifierRole.SECONDARY)
            for doi in dois
        ],
    )


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


def _to_query(conn, service=DOI_ORG) -> set[str]:
    return set(OaStatusStore(conn).fetch_dois_to_query(service, staleness_days=STALENESS))


class TestCandidateDois:
    """Les DOI interrogés suivent la règle des ancres : DOI `primary` ou `derived`, ou seul DOI de l'enregistrement source."""

    def test_le_seul_doi_d_un_enregistrement_source_est_candidat(self, sa_sync_conn):
        _record_with_dois(sa_sync_conn, insert_publication(sa_sync_conn), "10.1/seul")

        assert "10.1/seul" in _to_query(sa_sync_conn)

    def test_un_doi_secondaire_parmi_d_autres_est_ecarte(self, sa_sync_conn):
        _record_with_dois(sa_sync_conn, insert_publication(sa_sync_conn), "10.1/a", "10.1/b")

        assert not {"10.1/a", "10.1/b"} & _to_query(sa_sync_conn)

    def test_un_doi_qui_a_une_cible_est_ecarte(self, sa_sync_conn):
        _candidate(sa_sync_conn, "10.5281/zenodo.2")
        sa_sync_conn.execute(
            text(
                "INSERT INTO doi_targets (doi, target_doi, rule)"
                " VALUES ('10.5281/zenodo.2', '10.5281/zenodo.1', 'concept')"
            )
        )

        assert "10.5281/zenodo.2" not in _to_query(sa_sync_conn)

    def test_un_enregistrement_source_orphelin_compte_seulement_dans_le_perimetre(
        self, sa_sync_conn
    ):
        _record_with_dois(sa_sync_conn, None, "10.1/hors")
        in_perimeter = _record_with_dois(sa_sync_conn, None, "10.1/dans")
        insert_source_contribution(sa_sync_conn, in_perimeter, source="hal", in_perimeter=True)

        dois = _to_query(sa_sync_conn)

        assert "10.1/dans" in dois
        assert "10.1/hors" not in dois


class TestDoisToQuery:
    def test_seuls_les_doi_sans_verdict_ou_perimes(self, sa_sync_conn):
        """La péremption regarde seulement la date du verdict, nul compris."""
        for doi in ("10.1/n", "10.1/s", "10.1/f", "10.1/absent"):
            _candidate(sa_sync_conn, doi)
        _verdict(sa_sync_conn, "10.1/s", "gold", days_ago=999)
        _verdict(sa_sync_conn, "10.1/f", "gold", days_ago=1)
        _verdict(sa_sync_conn, "10.1/absent", None, days_ago=1)
        store = OaStatusStore(sa_sync_conn)

        dois = store.fetch_dois_to_query(UNPAYWALL, staleness_days=STALENESS)

        assert {"10.1/n", "10.1/s"} <= set(dois)
        assert not {"10.1/f", "10.1/absent"} & set(dois)
        assert store.count_dois_to_query(UNPAYWALL, staleness_days=STALENESS) == len(dois)

    def test_jamais_verifies_d_abord(self, sa_sync_conn):
        _candidate(sa_sync_conn, "10.1/a")
        _candidate(sa_sync_conn, "10.1/b")
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
        for doi in ("10.1/r", "10.1/v", "10.1/old"):
            _candidate(sa_sync_conn, doi)
        _resolved_only(sa_sync_conn, "10.1/r")
        _verdict(sa_sync_conn, "10.1/v", "gold", days_ago=1)
        _resolved_only(sa_sync_conn, "10.1/old", days_ago=999)

        unpaywall = _to_query(sa_sync_conn, UNPAYWALL)
        doi_org = _to_query(sa_sync_conn, DOI_ORG)

        assert {"10.1/r", "10.1/old"} <= unpaywall
        assert "10.1/v" not in unpaywall
        assert {"10.1/v", "10.1/old"} <= doi_org
        assert "10.1/r" not in doi_org

    def test_doi_datacite_ecartes_d_unpaywall_seulement(self, sa_sync_conn):
        """Un préfixe DataCite écarte le DOI d'Unpaywall ; un préfixe d'une autre agence ou pas encore résolu le garde. doi.org reçoit tous les DOI."""
        insert_doi_prefix(sa_sync_conn, "10.9001", ra="DataCite")
        insert_doi_prefix(sa_sync_conn, "10.9002", ra="mEDRA")
        for doi in ("10.9001/x", "10.9002/y", "10.9003/z"):
            _candidate(sa_sync_conn, doi)

        unpaywall = _to_query(sa_sync_conn, UNPAYWALL)
        doi_org = _to_query(sa_sync_conn, DOI_ORG)

        assert {"10.9002/y", "10.9003/z"} <= unpaywall
        assert "10.9001/x" not in unpaywall
        assert {"10.9001/x", "10.9002/y", "10.9003/z"} <= doi_org

    def test_respecte_le_plafond(self, sa_sync_conn):
        for i in range(3):
            _candidate(sa_sync_conn, f"10.1/{i}")
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


class TestEnqueuePublications:
    def test_les_publications_de_ces_doi_entrent_en_file(self, sa_sync_conn):
        concerned = insert_publication(sa_sync_conn, doi="10.1/p")
        insert_publication(sa_sync_conn, doi="10.1/autre")

        queued_count = OaStatusStore(sa_sync_conn).enqueue_publications(["10.1/p", "10.1/z"])

        assert queued_count == 1
        assert queued(sa_sync_conn, Queue.PUBLICATIONS) == {concerned}
