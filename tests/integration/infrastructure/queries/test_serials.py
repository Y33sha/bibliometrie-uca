"""Tests d'intégration du SQL des revues : store et étapes de `publishing`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial

import pytest
from sqlalchemy import text

from domain.serials.doi_namespaces import DoiNamespace
from domain.serials.issn_facts import IssnFacts, IssnLink, IssnLinkType, SudocReading
from domain.serials.issns import IssnStatus, IssnSupport
from domain.serials.serial import SerialType
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from pipeline.transformation.publishing.serials.check_issns_in_sudoc import (
    find_issns_to_check,
    record_sudoc_reading,
)
from pipeline.transformation.publishing.serials.delete_empty_serials import delete_empty_serials
from pipeline.transformation.publishing.serials.enrich_serials_from_doaj import (
    doaj_last_import_at,
    find_serial_issn_index,
    reset_is_in_doaj,
)
from pipeline.transformation.publishing.serials.enrich_serials_from_openalex import (
    find_serials_of_unknown_type,
)
from pipeline.transformation.publishing.serials.learn_serial_doi_namespaces import (
    find_doi_serial_pairs,
    store_doi_namespaces,
)
from pipeline.transformation.publishing.serials.store import SerialStore
from pipeline.transformation.publishing.serials.type_proceedings_serials import (
    find_record_types_of_unknown_serials,
    find_titles_of_non_proceedings_serials,
)
from tests.integration.helpers.publications import insert_apc_payment
from tests.integration.helpers.serials import (
    insert_serial_issn,
    insert_serial_with_issns,
)
from tests.integration.helpers.sources import insert_source_record

# Revue « J » par défaut.
_serial = partial(insert_serial_with_issns, title="J")

# Enregistrement source de titre « Article ».
_article = partial(insert_source_record, title="Article")


@pytest.fixture
def repo(sa_sync_conn):
    return SerialStore(sa_sync_conn)


def _issns(conn, serial_id):
    return {
        r.issn: (r.support, r.linking, r.status, r.sudoc_checked_at)
        for r in conn.execute(
            text(
                "SELECT issn, support::text, issn = issnl AS linking, status::text, sudoc_checked_at"
                " FROM serial_issns WHERE serial_id IS NOT DISTINCT FROM :id"
            ),
            {"id": serial_id},
        )
    }


class TestSudocCheck:
    def test_issns_jamais_verifies(self, sa_sync_conn, repo):
        _serial(sa_sync_conn, issn="0028-0836")
        _serial(sa_sync_conn, issn="1476-4687", sudoc_checked=True)
        issns = find_issns_to_check(sa_sync_conn)
        assert "0028-0836" in issns
        assert "1476-4687" not in issns

    def test_lecture_ecrit_les_faits_les_liens_et_le_titre(self, sa_sync_conn, repo):
        insert_serial_issn(sa_sync_conn, None, issn="0028-0836")
        reading = SudocReading(
            (
                IssnFacts("0028-0836", "0028-0836", IssnSupport.PRINT, IssnStatus.ACTIVE),
                IssnFacts("0302-2889", "0028-0836", None, IssnStatus.CANCELLED),
            ),
            (IssnLink("0028-0836", "1476-4687", IssnLinkType.CONTINUED_BY),),
            "Nature",
            ("1754-6656",),
        )
        record_sudoc_reading(sa_sync_conn, "0028-0836", reading, datetime.now(UTC))
        rows = {
            r.issn: r
            for r in sa_sync_conn.execute(
                text(
                    "SELECT issn, issnl, support::text, status::text, sudoc_checked_at, serial_id"
                    " FROM serial_issns WHERE issn IN ('0028-0836', '0302-2889', '1754-6656')"
                )
            )
        }
        assert (rows["0028-0836"].issnl, rows["0028-0836"].support) == ("0028-0836", "print")
        assert rows["0028-0836"].sudoc_checked_at is not None
        assert (rows["0302-2889"].issnl, rows["0302-2889"].status) == ("0028-0836", "cancelled")
        assert rows["1754-6656"].sudoc_checked_at is None
        serial_id = rows["0028-0836"].serial_id
        assert (
            sa_sync_conn.execute(
                text("SELECT title FROM serials WHERE id = :id"), {"id": serial_id}
            ).scalar_one()
            == "Nature"
        )
        assert sa_sync_conn.execute(
            text("SELECT issn, linked_issn, link_type::text FROM issn_links")
        ).all() == [("0028-0836", "1476-4687", "continued_by")]

    def test_delete_empty_serials_spares_issns_records_and_apc_payments(self, sa_sync_conn, repo):
        """Une revue à ISSN reste, même sans enregistrement source : son titre est le titre Sudoc de son ISSN-L."""
        empty = _serial(sa_sync_conn, title="Revue test vide")
        with_issn = _serial(sa_sync_conn, title="Revue test à ISSN", issn="2999-0007")
        with_record = _serial(sa_sync_conn, title="Revue test avec enregistrement")
        _article(
            sa_sync_conn,
            source_id=f"sp-{with_record}-10.9999/d",
            doi="10.9999/d",
            serial_id=with_record,
        )
        with_payment = _serial(sa_sync_conn, title="Revue test avec paiement")
        insert_apc_payment(sa_sync_conn, serial_id=with_payment, open_access_fee=True)
        deleted = {j.id: j for j in delete_empty_serials(sa_sync_conn)}
        assert deleted[empty].title == "Revue test vide"
        assert not deleted.keys() & {with_issn, with_record, with_payment}

    def test_describe_serials(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn, title="Revue test décrite", eissn="2999-0008")
        summary = repo.describe_serials([serial_id])[serial_id]
        assert (summary.title, summary.publisher, summary.issns) == (
            "Revue test décrite",
            None,
            ("2999-0008",),
        )


class TestFindSerialsOfUnknownType:
    def test_returns_id_and_openalex_id(self, sa_sync_conn, repo):
        _serial(sa_sync_conn, openalex_id="S1")  # serial_type 'unknown' par défaut
        rows = find_serials_of_unknown_type(sa_sync_conn)
        assert rows
        for serial_id, oa_id in rows:
            assert isinstance(serial_id, int)
            assert isinstance(oa_id, str)

    def test_returns_only_unknown_type_with_openalex(self, sa_sync_conn, repo):
        needs = _serial(sa_sync_conn, openalex_id="S1")
        typed = _serial(sa_sync_conn, openalex_id="S2")
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'journal' WHERE id = :id"), {"id": typed}
        )
        _serial(sa_sync_conn)  # pas d'openalex_id

        ids = [jid for jid, _ in find_serials_of_unknown_type(sa_sync_conn)]
        assert needs in ids
        assert typed not in ids  # déjà typé → sorti de la file

    def test_respects_limit(self, sa_sync_conn, repo):
        for i in range(3):
            _serial(sa_sync_conn, openalex_id=f"S{i}")
        assert len(find_serials_of_unknown_type(sa_sync_conn, limit=2)) == 2

    def test_limit_zero_is_unlimited(self, sa_sync_conn, repo):
        for i in range(2):
            _serial(sa_sync_conn, openalex_id=f"S{i}")
        assert len(find_serials_of_unknown_type(sa_sync_conn, limit=0)) >= 2


class TestTitlesOfNonProceedingsSerials:
    def test_recueils_exclus_et_issn_signale(self, sa_sync_conn, repo):
        with_issnl = _serial(sa_sync_conn, title="NuFACT 2022", issnl="1234-5679")
        proceedings = _serial(sa_sync_conn, title="ESAFORM 2021")
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'proceedings' WHERE id = :id"),
            {"id": proceedings},
        )

        rows = {r.id: r for r in find_titles_of_non_proceedings_serials(sa_sync_conn)}

        assert rows[with_issnl].has_issn is True
        assert proceedings not in rows


class TestRecordTypesOfUnknownSerials:
    def test_type_brut_avant_correction(self, sa_sync_conn, repo):
        """Un enregistrement source retypé par la correction est compté avec son type de source."""
        jid = _serial(sa_sync_conn)
        insert_source_record(
            sa_sync_conn,
            source="crossref",
            source_id="10.1/a",
            title="A",
            doc_type="conference_paper",
            raw_doc_type="book-chapter",
            serial_id=jid,
            corrections={"doc_type": {"raw": "book_chapter", "corrected_by": "X"}},
        )
        insert_source_record(
            sa_sync_conn,
            source_id="hal-1",
            title="B",
            doc_type="conference_paper",
            raw_doc_type="COMM",
            serial_id=jid,
        )

        rows = [r for r in find_record_types_of_unknown_serials(sa_sync_conn) if r.serial_id == jid]

        assert rows[0].records == (("crossref", "book-chapter"), ("hal", "COMM"))

    def test_revues_typees_et_vides_exclues(self, sa_sync_conn, repo):
        typed = _serial(sa_sync_conn)
        empty = _serial(sa_sync_conn)
        _article(sa_sync_conn, source_id=f"sp-{typed}-10.1/b", doi="10.1/b", serial_id=typed)
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'journal' WHERE id = :id"), {"id": typed}
        )

        ids = {r.serial_id for r in find_record_types_of_unknown_serials(sa_sync_conn)}

        assert typed not in ids
        assert empty not in ids


class TestDoiNamespaces:
    def test_revue_posee_par_son_espace_exclue_des_temoins(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn)
        _article(
            sa_sync_conn,
            source_id=f"sp-{serial_id}-10.9001/abc.1",
            doi="10.9001/abc.1",
            serial_id=serial_id,
        )
        _article(
            sa_sync_conn,
            source_id=f"sp-{serial_id}-10.9001/abc.2",
            doi="10.9001/abc.2",
            serial_id=serial_id,
        )
        sa_sync_conn.execute(
            text(
                "UPDATE source_records SET corrections = CAST(:raw AS jsonb) WHERE source_id = :sid"
            ),
            {
                "raw": '{"serial_id": {"raw": null, "corrected_by": "X"}}',
                "sid": f"sp-{serial_id}-10.9001/abc.2",
            },
        )
        pairs = [p for p in find_doi_serial_pairs(sa_sync_conn) if p.serial_id == serial_id]
        assert [(p.doi, p.serial_type) for p in pairs] == [("10.9001/abc.1", SerialType.UNKNOWN)]

    def test_doi_secondaire_d_agregateur_exclu_des_temoins(self, sa_sync_conn, repo):
        """Seuls le DOI `derived` d'un work OpenAlex et les DOI des autres sources votent pour la revue ; un DOI `secondary` d'OpenAlex (copie de repository Apollo, `10.17863/cam.`) est exclu."""
        serial_id = _serial(sa_sync_conn)
        secondary = SourceIdentifierRole.SECONDARY
        _article(
            sa_sync_conn,
            source="openalex",
            source_id="W1",
            serial_id=serial_id,
            identifiers=[SourceIdentifier(SourceIdentifierType.DOI, "10.17863/cam.1", secondary)],
        )
        _article(
            sa_sync_conn,
            source="hal",
            source_id="hal-1",
            serial_id=serial_id,
            identifiers=[SourceIdentifier(SourceIdentifierType.DOI, "10.9001/abc.1", secondary)],
        )
        _article(
            sa_sync_conn,
            source="openalex",
            source_id="W2",
            serial_id=serial_id,
            identifiers=[
                SourceIdentifier(
                    SourceIdentifierType.DOI, "10.9001/abc.2", SourceIdentifierRole.DERIVED
                ),
                SourceIdentifier(SourceIdentifierType.DOI, "10.17863/cam.2", secondary),
            ],
        )
        pairs = [p for p in find_doi_serial_pairs(sa_sync_conn) if p.serial_id == serial_id]
        assert sorted(p.doi for p in pairs) == ["10.9001/abc.1", "10.9001/abc.2"]

    def test_store_vide_puis_ecrit(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn)
        store_doi_namespaces(sa_sync_conn, [DoiNamespace("10.9001/old.", serial_id, 5, 1.0)])
        store_doi_namespaces(sa_sync_conn, [DoiNamespace("10.9001/abc.", serial_id, 8, 0.95)])
        rows = sa_sync_conn.execute(
            text("SELECT namespace, serial_id, dois, share FROM serial_doi_namespaces")
        ).all()
        assert [tuple(r) for r in rows] == [("10.9001/abc.", serial_id, 8, 0.95)]


class TestSerialIssnIndex:
    def test_exposes_every_issn(self, sa_sync_conn, repo):
        jid = _serial(sa_sync_conn, issn="1111-1111", eissn="2222-2222")
        insert_serial_issn(sa_sync_conn, jid, issn="3333-3333", status=IssnStatus.CANCELLED)
        ours = [r.issn for r in find_serial_issn_index(sa_sync_conn) if r.serial_id == jid]
        assert ours == ["1111-1111", "2222-2222", "3333-3333"]

    def test_excludes_serials_with_no_issn(self, sa_sync_conn, repo):
        jid = _serial(sa_sync_conn)
        assert jid not in [r.serial_id for r in find_serial_issn_index(sa_sync_conn)]


class TestDoajImport:
    def test_reset_is_in_doaj_clears_true_flags(self, sa_sync_conn, repo):
        jid = _serial(sa_sync_conn, issn="3333-3333")
        sa_sync_conn.execute(
            text("UPDATE serials SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        assert reset_is_in_doaj(sa_sync_conn) >= 1
        assert (
            sa_sync_conn.execute(
                text("SELECT is_in_doaj FROM serials WHERE id = :id"), {"id": jid}
            ).scalar_one()
            is False
        )

    def test_last_import_at_returns_a_value_when_imported(self, sa_sync_conn, repo):
        d = datetime.now(UTC) - timedelta(days=3)
        _serial(sa_sync_conn, issn="4444-4444", doaj_imported_at=d)
        last = doaj_last_import_at(sa_sync_conn)
        assert last is not None and last >= d - timedelta(seconds=1)
