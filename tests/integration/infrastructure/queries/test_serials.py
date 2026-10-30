"""Tests d'intégration du SQL des revues : store et étapes de `publishing`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial

import pytest
from sqlalchemy import text

from domain.serials.doi_namespaces import DoiNamespace
from domain.serials.issns import IssnStatus, IssnSupport, SerialIssn
from domain.serials.serial import SerialType
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from pipeline.transformation.publishing.serials.check_serials_in_sudoc import (
    find_serials_to_check_in_sudoc,
    find_titles_of_serials_with_issn,
    record_sudoc_check,
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
from pipeline.transformation.publishing.serials.merge_duplicate_serials import (
    find_same_title_duplicates,
    find_serials_sharing_a_publication,
    find_serials_sharing_active_issn,
    find_serials_sharing_an_inactive_issn,
    find_serials_sharing_issnl,
)
from pipeline.transformation.publishing.serials.store import SerialStore
from pipeline.transformation.publishing.serials.type_proceedings_serials import (
    find_record_types_of_unknown_serials,
    find_titles_of_non_proceedings_serials,
)
from tests.integration.helpers.publications import insert_apc_payment, insert_publication
from tests.integration.helpers.serials import (
    insert_serial,
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
                "SELECT issn, support::text, linking, status::text, sudoc_checked_at"
                " FROM serial_issns WHERE serial_id IS NOT DISTINCT FROM :id"
            ),
            {"id": serial_id},
        )
    }


class TestSudocCheck:
    def test_queue_holds_serials_with_an_unchecked_issn(self, sa_sync_conn, repo):
        with_issn = _serial(sa_sync_conn, issn="0028-0836")
        without_issn = _serial(sa_sync_conn)
        malformed_only = _serial(sa_sync_conn)
        insert_serial_issn(
            sa_sync_conn, malformed_only, issn="1950-2051", status=IssnStatus.MALFORMED
        )
        checked = _serial(sa_sync_conn, issn="1476-4687", sudoc_checked=True)
        rows = {r.id: r for r in find_serials_to_check_in_sudoc(sa_sync_conn)}
        assert with_issn in rows
        assert rows[malformed_only].issns == (
            SerialIssn(issn="1950-2051", status=IssnStatus.MALFORMED),
        )
        assert without_issn not in rows
        assert checked not in rows

    def test_queue_holds_serials_whose_records_carry_an_unknown_issn(self, sa_sync_conn, repo):
        """Une revue vérifiée revient dans la file quand un de ses enregistrements sources, quelle que soit sa source, contient un ISSN absent de ses ISSN. La valeur reçue est normalisée ; une valeur invalide est ignorée."""
        serial_id = _serial(sa_sync_conn, issn="0149-5992", sudoc_checked=True)
        _article(
            sa_sync_conn,
            source_id=f"sp-issn-{serial_id}",
            serial_id=serial_id,
            biblio={"journal": {"issn": "19355548", "eissn": "0149-5992"}},
        )
        _article(
            sa_sync_conn,
            source="openalex",
            source_id=f"sp-issn-bad-{serial_id}",
            serial_id=serial_id,
            biblio={"journal": {"issn": "1234-5678"}},
        )
        rows = {r.id: r for r in find_serials_to_check_in_sudoc(sa_sync_conn)}
        assert rows[serial_id].document_issns == ("1935-5548",)

    def test_queue_ignores_records_whose_issns_the_serial_carries(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn, issn="0149-5992", sudoc_checked=True)
        _article(
            sa_sync_conn,
            source="scanr",
            source_id=f"sp-own-{serial_id}",
            serial_id=serial_id,
            biblio={"journal": {"issn": "01495992"}},
        )
        assert serial_id not in {r.id for r in find_serials_to_check_in_sudoc(sa_sync_conn)}

    def test_queue_ignores_record_issns_checked_without_serial(self, sa_sync_conn, repo):
        """Un ISSN d'une autre publication, déjà vérifié et gardé sans revue, ne ramène pas la revue dans la file."""
        serial_id = _serial(sa_sync_conn, issn="1254-7867", sudoc_checked=True)
        insert_serial_issn(
            sa_sync_conn, None, issn="2750-6185", support="electronic", sudoc_checked=True
        )
        _article(
            sa_sync_conn,
            source_id=f"sp-other-{serial_id}",
            serial_id=serial_id,
            biblio={"journal": {"issn": "2750-6185"}},
        )
        assert serial_id not in {r.id for r in find_serials_to_check_in_sudoc(sa_sync_conn)}

    def test_find_by_issn_reaches_inactive_issns(self, sa_sync_conn, repo):
        """Un ISSN inactif sert à retrouver la revue ; une revue où il est actif passe avant ; une valeur mal formée ne sert pas."""
        holding = _serial(sa_sync_conn, issn="0305-1048")
        insert_serial_issn(sa_sync_conn, holding, issn="1362-4954", status=IssnStatus.RELATED_TITLE)
        insert_serial_issn(sa_sync_conn, holding, issn="1950-2051", status=IssnStatus.MALFORMED)
        assert repo.find_serial_by_issn_any("1362-4954") == holding
        assert repo.find_serial_by_issn_any("1950-2051") is None
        carrying = _serial(sa_sync_conn, eissn="1362-4954")
        assert repo.find_serial_by_issn_any("1362-4954") == carrying

    def test_merge_groups_hold_checked_serials_sharing_an_issnl(self, sa_sync_conn, repo):
        """La revue qui a le plus de publications vient en tête du groupe ; une revue non vérifiée en est exclue."""
        keeper = _serial(sa_sync_conn, issnl="2999-0001", sudoc_checked=True)
        absorbed = _serial(sa_sync_conn, issnl="2999-0001", sudoc_checked=True)
        unchecked = _serial(sa_sync_conn, issnl="2999-0001")
        sa_sync_conn.execute(
            text("UPDATE serials SET publication_count = 3 WHERE id = :id"), {"id": keeper}
        )
        groups = {g.key: g.serial_ids for g in find_serials_sharing_issnl(sa_sync_conn)}
        assert groups["2999-0001"] == (keeper, absorbed)
        assert unchecked not in groups["2999-0001"]

    def test_shared_active_issn_groups_hold_titles(self, sa_sync_conn, repo):
        keeper = _serial(sa_sync_conn, title="BMJ", eissn="2999-0002", sudoc_checked=True)
        other = _serial(
            sa_sync_conn, title="BMJ British Medical Journal", issn="2999-0002", sudoc_checked=True
        )
        sa_sync_conn.execute(
            text("UPDATE serials SET publication_count = 4 WHERE id = :id"), {"id": keeper}
        )
        groups = {g.issn: g.serials for g in find_serials_sharing_active_issn(sa_sync_conn)}
        assert [j.id for j in groups["2999-0002"]] == [keeper, other]
        assert [j.title for j in groups["2999-0002"]] == ["BMJ", "BMJ British Medical Journal"]

    def test_same_title_duplicates(self, sa_sync_conn, repo):
        """Seules les paires dont les enregistrements sources partagent un préfixe DOI sont retenues ; une revue vide ou deux revues à ISSN restent hors de la règle."""
        with_issn = _serial(sa_sync_conn, title="Revue test même préfixe", issn="2999-0003")
        without_issn = _serial(sa_sync_conn, title="Revue test même préfixe")
        _article(
            sa_sync_conn,
            source_id=f"sp-{with_issn}-10.9999/a",
            doi="10.9999/a",
            serial_id=with_issn,
        )
        _article(
            sa_sync_conn,
            source_id=f"sp-{without_issn}-10.9999/b",
            doi="10.9999/b",
            serial_id=without_issn,
        )
        full = _serial(sa_sync_conn, title="Revue test doublon vide", issn="2999-0006")
        _serial(sa_sync_conn, title="Revue test doublon vide")
        _article(sa_sync_conn, source_id=f"sp-{full}-10.9999/c", doi="10.9999/c", serial_id=full)
        _serial(sa_sync_conn, title="Revue test homonymes à ISSN", issn="2999-0004")
        _serial(sa_sync_conn, title="Revue test homonymes à ISSN", issn="2999-0005")
        active_a = _serial(sa_sync_conn, title="Revue test actives distinctes")
        active_b = _serial(sa_sync_conn, title="Revue test actives distinctes")
        _article(
            sa_sync_conn, source_id=f"sp-{active_a}-10.1111/x", doi="10.1111/x", serial_id=active_a
        )
        _article(
            sa_sync_conn, source_id=f"sp-{active_b}-10.2222/y", doi="10.2222/y", serial_id=active_b
        )
        groups = {g.key: g.serial_ids for g in find_same_title_duplicates(sa_sync_conn)}
        assert set(groups["revue test même préfixe"]) == {with_issn, without_issn}
        assert "revue test doublon vide" not in groups
        assert "revue test homonymes à issn" not in groups
        assert "revue test actives distinctes" not in groups

    def test_same_title_duplicates_ignore_empty_normalized_titles(self, sa_sync_conn, repo):
        """Un titre grec et un titre cyrillique se normalisent en chaîne vide : ils ne forment pas une paire."""
        for title in ("Παιδαγωγικά ρεύματα στο Αιγαίο", "Теория вероятностей и ее применения"):
            serial_id = insert_serial(sa_sync_conn, title, title_normalized="")
            _article(
                sa_sync_conn,
                source_id=f"sp-{serial_id}-10.9999/vide-{serial_id}",
                doi=f"10.9999/vide-{serial_id}",
                serial_id=serial_id,
            )
        assert "" not in {g.key for g in find_same_title_duplicates(sa_sync_conn)}

    def test_serials_sharing_an_inactive_issn(self, sa_sync_conn, repo):
        """L'ISSN inactif de l'une est actif dans l'autre ; la revue au premier enregistrement source le plus tardif vient en tête, même quand l'ancien titre reçoit encore des enregistrements sources récents. Une revue non vérifiée reste hors de la règle."""
        earlier = _serial(
            sa_sync_conn, title="Revue test ancien titre", issn="2999-0012", sudoc_checked=True
        )
        later = _serial(
            sa_sync_conn, title="Revue test nouveau titre", eissn="2999-0013", sudoc_checked=True
        )
        unchecked = _serial(sa_sync_conn, title="Revue test non vérifiée", issn="2999-0014")
        insert_serial_issn(
            sa_sync_conn,
            earlier,
            issn="2999-0013",
            status=IssnStatus.RELATED_TITLE,
            sudoc_checked=True,
        )
        insert_serial_issn(
            sa_sync_conn,
            later,
            issn="2999-0014",
            status=IssnStatus.RELATED_TITLE,
            sudoc_checked=True,
        )
        for serial_id, year in ((earlier, 2018), (earlier, 2026), (later, 2022), (later, 2025)):
            _article(
                sa_sync_conn,
                source_id=f"sp-rejete-{serial_id}-{year}",
                publication_year=year,
                serial_id=serial_id,
            )
        groups = {g.key: g.serial_ids for g in find_serials_sharing_an_inactive_issn(sa_sync_conn)}
        assert groups["2999-0013"] == (later, earlier)
        assert "2999-0014" not in groups
        assert unchecked not in {i for ids in groups.values() for i in ids}

    def test_serials_sharing_a_publication(self, sa_sync_conn, repo):
        """Deux revues désignées par les enregistrements sources d'une même publication forment une paire."""
        full = _serial(sa_sync_conn, title="Journal test complet", issn="2999-0009")
        abbreviated = _serial(sa_sync_conn, title="J.Test Compl.")
        publication_id = insert_publication(
            sa_sync_conn, "Article", normalize_title=False, doc_type=None
        )
        for serial_id in (full, abbreviated):
            _article(
                sa_sync_conn,
                publication_id,
                source_id=f"sp-publication-{serial_id}",
                serial_id=serial_id,
            )
        pairs = [
            p
            for p in find_serials_sharing_a_publication(sa_sync_conn)
            if {p.first.id, p.second.id} & {full, abbreviated}
        ]
        assert [(p.first.id, p.second.id, p.publications) for p in pairs] == [
            (full, abbreviated, 1)
        ]
        assert pairs[0].first.issns == frozenset({"2999-0009"})
        assert pairs[0].second.title == "J.Test Compl."

    def test_delete_empty_serials_spares_records_and_apc_payments(self, sa_sync_conn, repo):
        """Une revue vide est supprimée ; ses ISSN restent sans revue, sauf un ISSN déjà gardé sans revue."""
        empty = _serial(sa_sync_conn, title="Revue test vide", issn="2999-0007")
        insert_serial_issn(sa_sync_conn, empty, issn="2999-0015", support="electronic")
        insert_serial_issn(
            sa_sync_conn, None, issn="2999-0015", support="electronic", sudoc_checked=True
        )
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
        assert deleted[empty].issns == ("2999-0007", "2999-0015")
        assert with_record not in deleted
        assert with_payment not in deleted
        orphans = _issns(sa_sync_conn, None)
        assert orphans["2999-0007"][:3] == ("print", False, "active")
        assert orphans["2999-0015"][3] is not None

    def test_describe_serials(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn, title="Revue test décrite", eissn="2999-0008")
        summary = repo.describe_serials([serial_id])[serial_id]
        assert (summary.title, summary.publisher, summary.issns) == (
            "Revue test décrite",
            None,
            ("2999-0008",),
        )

    def test_record_writes_issns_and_date(self, sa_sync_conn, repo):
        """Les ISSN de la revue sont ceux de la vérification, datés ; un ISSN écarté reste sans revue."""
        serial_id = _serial(sa_sync_conn, issn="1476-4687", issnl="0028-0836")
        insert_serial_issn(sa_sync_conn, serial_id, issn="0007-0920")
        at = datetime(2026, 9, 15, tzinfo=UTC)
        record_sudoc_check(
            sa_sync_conn,
            serial_id,
            issns=(
                SerialIssn(issn="0028-0836", support=IssnSupport.PRINT, linking=True),
                SerialIssn(issn="1476-4687", support=IssnSupport.ELECTRONIC),
            ),
            released=(SerialIssn(issn="0007-0920", support=IssnSupport.PRINT),),
            checked_at=at,
        )
        assert _issns(sa_sync_conn, serial_id) == {
            "0028-0836": ("print", True, "active", at),
            "1476-4687": ("electronic", False, "active", at),
        }
        assert _issns(sa_sync_conn, None)["0007-0920"] == ("print", False, "active", at)

    def test_record_writes_reference_title_and_its_name_form(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn, title="ICORES 2023", issn="2184-4372")
        record_sudoc_check(
            sa_sync_conn,
            serial_id,
            issns=(SerialIssn(issn="2184-4372", support=IssnSupport.PRINT),),
            released=(),
            checked_at=datetime(2026, 9, 21, tzinfo=UTC),
            title="ICORES",
        )
        title, forms = sa_sync_conn.execute(
            text(
                "SELECT j.title, array_agg(f.form_normalized) FROM serials j"
                " JOIN serial_name_forms f ON f.serial_id = j.id WHERE j.id = :id GROUP BY j.title"
            ),
            {"id": serial_id},
        ).one()
        assert (title, forms) == ("ICORES", ["icores"])

    def test_queue_holds_the_serials_asked_for(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn, title="ICORES 2023", issn="2184-4372", sudoc_checked=True)
        assert serial_id not in {r.id for r in find_serials_to_check_in_sudoc(sa_sync_conn)}
        assert serial_id in {
            r.id for r in find_serials_to_check_in_sudoc(sa_sync_conn, also=[serial_id])
        }
        assert (serial_id, "ICORES 2023", SerialType.UNKNOWN) in (
            find_titles_of_serials_with_issn(sa_sync_conn)
        )


class TestAddSerialIssns:
    def test_adds_new_issns_and_fills_a_missing_support(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn, sudoc_checked=True)
        insert_serial_issn(sa_sync_conn, serial_id, issn="0028-0836", sudoc_checked=True)
        repo.add_serial_issns(
            serial_id,
            [
                SerialIssn(issn="0028-0836", support=IssnSupport.PRINT, linking=True),
                SerialIssn(issn="1476-4687", support=IssnSupport.ELECTRONIC),
            ],
        )
        issns = _issns(sa_sync_conn, serial_id)
        assert issns["0028-0836"][:3] == ("print", True, "active")
        assert issns["0028-0836"][3] is not None
        assert issns["1476-4687"] == ("electronic", False, "active", None)

    def test_claims_an_issn_kept_without_serial(self, sa_sync_conn, repo):
        insert_serial_issn(
            sa_sync_conn, None, issn="2750-6185", support="electronic", sudoc_checked=True
        )
        serial_id = _serial(sa_sync_conn, title="Spotlight")
        repo.add_serial_issns(serial_id, [SerialIssn(issn="2750-6185")])
        assert "2750-6185" not in _issns(sa_sync_conn, None)
        assert _issns(sa_sync_conn, serial_id)["2750-6185"][:3] == ("electronic", False, "active")

    def test_keeps_the_existing_issnl(self, sa_sync_conn, repo):
        serial_id = _serial(sa_sync_conn, issn="0028-0836", issnl="0028-0836")
        repo.add_serial_issns(serial_id, [SerialIssn(issn="1476-4687", linking=True)])
        issns = _issns(sa_sync_conn, serial_id)
        assert (issns["0028-0836"][1], issns["1476-4687"][1]) == (True, False)


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
    def test_exposes_every_valid_issn(self, sa_sync_conn, repo):
        jid = _serial(sa_sync_conn, issn="1111-1111", eissn="2222-2222")
        insert_serial_issn(sa_sync_conn, jid, issn="3333-3333", status=IssnStatus.RELATED_TITLE)
        insert_serial_issn(sa_sync_conn, jid, issn="(Internet)", status=IssnStatus.MALFORMED)
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
