"""Tests d'intégration pour `pipeline.transformation.dois.lookups` : DOI à soumettre à Unpaywall et à doi.org, réponses, publications mises en file."""

from itertools import count

from sqlalchemy import text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from pipeline.transformation.dois.lookups import DOI_ORG, UNPAYWALL, Answer, DoiAnswerStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.serials import insert_doi_prefix
from tests.integration.helpers.sources import insert_source_record

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
            "INSERT INTO dois (doi, registered_url, resolved_at, registered)"
            " VALUES (:doi, 'https://x', now() - make_interval(days => :d), TRUE)"
        ),
        {"doi": doi, "d": days_ago},
    )


def _to_query(conn, service=UNPAYWALL) -> set[str]:
    return set(DoiAnswerStore(conn).fetch_dois_to_query(service, staleness_days=STALENESS))


class TestPublicationDois:
    """Unpaywall reçoit le DOI de chaque publication."""

    def test_le_doi_d_une_publication_est_interroge(self, sa_sync_conn):
        insert_publication(sa_sync_conn, doi="10.1/publication")

        assert "10.1/publication" in _to_query(sa_sync_conn)

    def test_un_doi_absent_des_publications_est_ecarte(self, sa_sync_conn):
        _record_with_dois(sa_sync_conn, insert_publication(sa_sync_conn), "10.1/seul")

        assert "10.1/seul" not in _to_query(sa_sync_conn)


class TestKnownDois:
    """doi.org reçoit tous les DOI connus (vue `known_dois`), et la forme sans version des DOI à suffixe de version."""

    def test_un_doi_secondaire_parmi_d_autres_est_interroge(self, sa_sync_conn):
        _record_with_dois(sa_sync_conn, insert_publication(sa_sync_conn), "10.1/a", "10.1/b")

        assert {"10.1/a", "10.1/b"} <= _to_query(sa_sync_conn, DOI_ORG)

    def test_la_cible_d_une_relation_est_interrogee(self, sa_sync_conn):
        publication = _candidate(sa_sync_conn, "10.1/source")
        sa_sync_conn.execute(
            text(
                "INSERT INTO publication_relations"
                " (from_publication_id, target_doi, relation_type, source)"
                " VALUES (:p, '10.1/cible', 'is_preprint_of', 'datacite')"
            ),
            {"p": publication},
        )

        assert "10.1/cible" in _to_query(sa_sync_conn, DOI_ORG)

    def test_la_forme_sans_version_est_interrogee(self, sa_sync_conn):
        _candidate(sa_sync_conn, "10.6084/m9.figshare.123.v2")

        assert {"10.6084/m9.figshare.123.v2", "10.6084/m9.figshare.123"} <= _to_query(
            sa_sync_conn, DOI_ORG
        )


class TestDoisToQuery:
    def test_seuls_les_doi_sans_verdict_ou_perimes(self, sa_sync_conn):
        """La péremption regarde seulement la date du verdict, nul compris."""
        for doi in ("10.1/n", "10.1/s", "10.1/f", "10.1/absent"):
            _candidate(sa_sync_conn, doi)
        _verdict(sa_sync_conn, "10.1/s", "gold", days_ago=999)
        _verdict(sa_sync_conn, "10.1/f", "gold", days_ago=1)
        _verdict(sa_sync_conn, "10.1/absent", None, days_ago=1)
        store = DoiAnswerStore(sa_sync_conn)

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
            for d in DoiAnswerStore(sa_sync_conn).fetch_dois_to_query(
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
        dois = DoiAnswerStore(sa_sync_conn).fetch_dois_to_query(
            DOI_ORG, limit=2, staleness_days=STALENESS
        )
        assert len(dois) == 2


class TestAnswers:
    def test_reponses_en_table_nul_compris(self, sa_sync_conn):
        _verdict(sa_sync_conn, "10.1/t", "gold", days_ago=1)
        _verdict(sa_sync_conn, "10.1/u", None, days_ago=1)
        _resolved_only(sa_sync_conn, "10.1/r")
        store = DoiAnswerStore(sa_sync_conn)
        dois = ["10.1/t", "10.1/u", "10.1/r", "10.1/z"]

        assert store.fetch_answers(UNPAYWALL, dois) == {"10.1/t": "gold", "10.1/u": None}
        assert store.fetch_answers(DOI_ORG, dois) == {"10.1/r": "https://x"}

    def test_une_reponse_reecrit_la_precedente_du_meme_service(self, sa_sync_conn):
        _verdict(sa_sync_conn, "10.1/v", "closed", days_ago=999)
        store = DoiAnswerStore(sa_sync_conn)
        store.record_answers(
            UNPAYWALL, [Answer("10.1/v", "gold", found=True), Answer("10.1/w", None, found=False)]
        )
        store.record_answers(DOI_ORG, [Answer("10.1/v", "https://e.org/v.pdf", found=True)])
        rows = sa_sync_conn.execute(
            text(
                "SELECT doi, unpaywall_oa_status::text, registered_url,"
                " unpaywall_checked_at > now() - interval '1 minute',"
                " resolved_at IS NOT NULL, registered"
                " FROM dois WHERE doi IN ('10.1/v', '10.1/w') ORDER BY doi"
            )
        ).all()
        assert [tuple(r) for r in rows] == [
            ("10.1/v", "gold", "https://e.org/v.pdf", True, True, True),
            ("10.1/w", None, None, True, False, None),
        ]

    def test_doi_org_distingue_le_doi_inconnu_du_doi_connu_sans_url(self, sa_sync_conn):
        DoiAnswerStore(sa_sync_conn).record_answers(
            DOI_ORG,
            [Answer("10.1/inconnu", None, found=False), Answer("10.1/sans-url", None, found=True)],
        )
        rows = sa_sync_conn.execute(
            text(
                "SELECT doi, registered, registered_url FROM dois"
                " WHERE doi IN ('10.1/inconnu', '10.1/sans-url') ORDER BY doi"
            )
        ).all()
        assert [tuple(r) for r in rows] == [
            ("10.1/inconnu", False, None),
            ("10.1/sans-url", True, None),
        ]


class TestEnqueuePublications:
    def test_les_publications_de_ces_doi_entrent_en_file(self, sa_sync_conn):
        concerned = insert_publication(sa_sync_conn, doi="10.1/p")
        insert_publication(sa_sync_conn, doi="10.1/autre")

        queued_count = DoiAnswerStore(sa_sync_conn).enqueue_publications(["10.1/p", "10.1/z"])

        assert queued_count == 1
        assert queued(sa_sync_conn, Queue.PUBLICATIONS) == {concerned}
