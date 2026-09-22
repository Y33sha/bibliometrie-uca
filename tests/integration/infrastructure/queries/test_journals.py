"""Tests d'intégration de `PgJournalGatewayQueries` : files d'enrichissement et index DOAJ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from domain.journals.doi_namespaces import DoiNamespace
from domain.journals.issns import IssnStatus, IssnSupport, JournalIssn
from domain.journals.journal import JournalType
from infrastructure.pipeline.journals import PgJournalGatewayQueries


@pytest.fixture
def repo(sa_sync_conn):
    return PgJournalGatewayQueries(sa_sync_conn)


def _add_issn(
    conn,
    journal_id,
    issn,
    *,
    support=None,
    linking=False,
    status=IssnStatus.ACTIVE,
    checked=False,
):
    conn.execute(
        text("""
            INSERT INTO journal_issns (issn, journal_id, support, linking, status, sudoc_checked_at)
            VALUES (:issn, :jid, CAST(:support AS issn_support), :linking,
                    CAST(:status AS issn_status), CASE WHEN :checked THEN now() END)
        """),
        {
            "issn": issn,
            "jid": journal_id,
            "support": support,
            "linking": linking,
            "status": status,
            "checked": checked,
        },
    )


def _create_journal(
    conn,
    *,
    title="J",
    openalex_id=None,
    issn=None,
    eissn=None,
    issnl=None,
    imported_at=None,
    checked=False,
):
    journal_id = conn.execute(
        text("""
            INSERT INTO journals (title, title_normalized, openalex_id, doaj_imported_at)
            VALUES (:title, lower(:title), :openalex_id, :imported_at)
            RETURNING id
        """),
        {"title": title, "openalex_id": openalex_id, "imported_at": imported_at},
    ).scalar_one()
    if issn:
        _add_issn(conn, journal_id, issn, support="print", linking=issn == issnl, checked=checked)
    if eissn:
        _add_issn(
            conn, journal_id, eissn, support="electronic", linking=eissn == issnl, checked=checked
        )
    if issnl and issnl not in (issn, eissn):
        _add_issn(conn, journal_id, issnl, linking=True, checked=checked)
    return journal_id


def _create_record(conn, journal_id, *, doi):
    conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, journal_id, doi)"
            " VALUES ('hal', :sid, 'Article', :jid, :doi)"
        ),
        {"sid": f"sp-{journal_id}-{doi}", "jid": journal_id, "doi": doi},
    )


def _issns(conn, journal_id):
    return {
        r.issn: (r.support, r.linking, r.status, r.sudoc_checked_at)
        for r in conn.execute(
            text(
                "SELECT issn, support::text, linking, status::text, sudoc_checked_at"
                " FROM journal_issns WHERE journal_id IS NOT DISTINCT FROM :id"
            ),
            {"id": journal_id},
        )
    }


class TestSudocCheck:
    def test_queue_holds_journals_with_an_unchecked_issn(self, sa_sync_conn, repo):
        with_issn = _create_journal(sa_sync_conn, issn="0028-0836")
        without_issn = _create_journal(sa_sync_conn)
        malformed_only = _create_journal(sa_sync_conn)
        _add_issn(sa_sync_conn, malformed_only, "1950-2051", status=IssnStatus.MALFORMED)
        checked = _create_journal(sa_sync_conn, issn="1476-4687", checked=True)
        rows = {r.id: r for r in repo.find_journals_to_check_in_sudoc()}
        assert with_issn in rows
        assert rows[malformed_only].issns == (
            JournalIssn(issn="1950-2051", status=IssnStatus.MALFORMED),
        )
        assert without_issn not in rows
        assert checked not in rows

    def test_queue_holds_journals_whose_records_carry_an_unknown_issn(self, sa_sync_conn, repo):
        """Une revue vérifiée revient dans la file quand un de ses enregistrements, quelle que soit sa source, porte un ISSN absent de ses ISSN. La valeur reçue est normalisée ; une valeur invalide est ignorée."""
        journal_id = _create_journal(sa_sync_conn, issn="0149-5992", checked=True)
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, journal_id, biblio)"
                " VALUES (:source, :sid, 'Article', :jid, CAST(:biblio AS jsonb))"
            ),
            [
                {
                    "source": "hal",
                    "sid": f"sp-issn-{journal_id}",
                    "jid": journal_id,
                    "biblio": '{"journal": {"issn": "19355548", "eissn": "0149-5992"}}',
                },
                {
                    "source": "openalex",
                    "sid": f"sp-issn-bad-{journal_id}",
                    "jid": journal_id,
                    "biblio": '{"journal": {"issn": "1234-5678"}}',
                },
            ],
        )
        rows = {r.id: r for r in repo.find_journals_to_check_in_sudoc()}
        assert rows[journal_id].document_issns == ("1935-5548",)

    def test_queue_ignores_records_whose_issns_the_journal_carries(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, issn="0149-5992", checked=True)
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, journal_id, biblio)"
                " VALUES ('scanr', :sid, 'Article', :jid, CAST(:biblio AS jsonb))"
            ),
            {
                "sid": f"sp-own-{journal_id}",
                "jid": journal_id,
                "biblio": '{"journal": {"issn": "01495992"}}',
            },
        )
        assert journal_id not in {r.id for r in repo.find_journals_to_check_in_sudoc()}

    def test_queue_ignores_record_issns_checked_without_journal(self, sa_sync_conn, repo):
        """Un ISSN d'une autre publication, déjà vérifié et gardé sans revue, ne ramène pas la revue dans la file."""
        journal_id = _create_journal(sa_sync_conn, issn="1254-7867", checked=True)
        _add_issn(sa_sync_conn, None, "2750-6185", support="electronic", checked=True)
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, journal_id, biblio)"
                " VALUES ('hal', :sid, 'Article', :jid, CAST(:biblio AS jsonb))"
            ),
            {
                "sid": f"sp-other-{journal_id}",
                "jid": journal_id,
                "biblio": '{"journal": {"issn": "2750-6185"}}',
            },
        )
        assert journal_id not in {r.id for r in repo.find_journals_to_check_in_sudoc()}

    def test_find_by_issn_reaches_inactive_issns(self, sa_sync_conn, repo):
        """Un ISSN inactif sert au rapprochement ; une revue où il est actif passe avant ; une valeur mal formée n'en sert pas."""
        holding = _create_journal(sa_sync_conn, issn="0305-1048")
        _add_issn(sa_sync_conn, holding, "1362-4954", status=IssnStatus.RELATED_TITLE)
        _add_issn(sa_sync_conn, holding, "1950-2051", status=IssnStatus.MALFORMED)
        assert repo.find_journal_by_issn_any("1362-4954") == holding
        assert repo.find_journal_by_issn_any("1950-2051") is None
        carrying = _create_journal(sa_sync_conn, eissn="1362-4954")
        assert repo.find_journal_by_issn_any("1362-4954") == carrying

    def test_merge_groups_hold_checked_journals_sharing_an_issnl(self, sa_sync_conn, repo):
        """La revue qui porte le plus de publications vient en tête du groupe ; une revue non vérifiée en est exclue."""
        keeper = _create_journal(sa_sync_conn, issnl="2999-0001", checked=True)
        absorbed = _create_journal(sa_sync_conn, issnl="2999-0001", checked=True)
        unchecked = _create_journal(sa_sync_conn, issnl="2999-0001")
        sa_sync_conn.execute(
            text("UPDATE journals SET pub_count = 3 WHERE id = :id"), {"id": keeper}
        )
        groups = {g.key: g.journal_ids for g in repo.find_journals_sharing_issnl()}
        assert groups["2999-0001"] == (keeper, absorbed)
        assert unchecked not in groups["2999-0001"]

    def test_shared_active_issn_groups_hold_titles(self, sa_sync_conn, repo):
        keeper = _create_journal(sa_sync_conn, title="BMJ", eissn="2999-0002", checked=True)
        other = _create_journal(
            sa_sync_conn, title="BMJ British Medical Journal", issn="2999-0002", checked=True
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET pub_count = 4 WHERE id = :id"), {"id": keeper}
        )
        groups = {g.issn: g.journals for g in repo.find_journals_sharing_active_issn()}
        assert [j.id for j in groups["2999-0002"]] == [keeper, other]
        assert [j.title for j in groups["2999-0002"]] == ["BMJ", "BMJ British Medical Journal"]

    def test_same_title_duplicates(self, sa_sync_conn, repo):
        """Seules les paires dont les enregistrements partagent un préfixe DOI sont retenues ; une revue vide ou deux revues à ISSN restent hors de la règle."""
        with_issn = _create_journal(sa_sync_conn, title="Revue test même préfixe", issn="2999-0003")
        without_issn = _create_journal(sa_sync_conn, title="Revue test même préfixe")
        _create_record(sa_sync_conn, with_issn, doi="10.9999/a")
        _create_record(sa_sync_conn, without_issn, doi="10.9999/b")
        full = _create_journal(sa_sync_conn, title="Revue test doublon vide", issn="2999-0006")
        _create_journal(sa_sync_conn, title="Revue test doublon vide")
        _create_record(sa_sync_conn, full, doi="10.9999/c")
        _create_journal(sa_sync_conn, title="Revue test homonymes à ISSN", issn="2999-0004")
        _create_journal(sa_sync_conn, title="Revue test homonymes à ISSN", issn="2999-0005")
        active_a = _create_journal(sa_sync_conn, title="Revue test actives distinctes")
        active_b = _create_journal(sa_sync_conn, title="Revue test actives distinctes")
        _create_record(sa_sync_conn, active_a, doi="10.1111/x")
        _create_record(sa_sync_conn, active_b, doi="10.2222/y")
        groups = {g.key: g.journal_ids for g in repo.find_same_title_duplicates()}
        assert set(groups["revue test même préfixe"]) == {with_issn, without_issn}
        assert "revue test doublon vide" not in groups
        assert "revue test homonymes à issn" not in groups
        assert "revue test actives distinctes" not in groups

    def test_same_title_duplicates_ignore_empty_normalized_titles(self, sa_sync_conn, repo):
        """Un titre grec et un titre cyrillique se normalisent en chaîne vide : ils ne forment pas une paire."""
        for title in ("Παιδαγωγικά ρεύματα στο Αιγαίο", "Теория вероятностей и ее применения"):
            journal_id = sa_sync_conn.execute(
                text("INSERT INTO journals (title, title_normalized) VALUES (:t, '') RETURNING id"),
                {"t": title},
            ).scalar_one()
            _create_record(sa_sync_conn, journal_id, doi=f"10.9999/vide-{journal_id}")
        assert "" not in {g.key for g in repo.find_same_title_duplicates()}

    def test_journals_sharing_an_inactive_issn(self, sa_sync_conn, repo):
        """L'ISSN inactif de l'une est actif dans l'autre ; la revue dont le premier document est le plus tardif vient en tête, même quand l'ancien titre reçoit encore des documents récents. Une revue non vérifiée reste hors de la règle."""
        earlier = _create_journal(
            sa_sync_conn, title="Revue test ancien titre", issn="2999-0012", checked=True
        )
        later = _create_journal(
            sa_sync_conn, title="Revue test nouveau titre", eissn="2999-0013", checked=True
        )
        unchecked = _create_journal(sa_sync_conn, title="Revue test non vérifiée", issn="2999-0014")
        _add_issn(sa_sync_conn, earlier, "2999-0013", status=IssnStatus.RELATED_TITLE, checked=True)
        _add_issn(sa_sync_conn, later, "2999-0014", status=IssnStatus.RELATED_TITLE, checked=True)
        for journal_id, year in ((earlier, 2018), (earlier, 2026), (later, 2022), (later, 2025)):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO source_publications (source, source_id, title, journal_id, pub_year)"
                    " VALUES ('hal', :sid, 'Article', :jid, :year)"
                ),
                {"sid": f"sp-rejete-{journal_id}-{year}", "jid": journal_id, "year": year},
            )
        groups = {g.key: g.journal_ids for g in repo.find_journals_sharing_an_inactive_issn()}
        assert groups["2999-0013"] == (later, earlier)
        assert "2999-0014" not in groups
        assert unchecked not in {i for ids in groups.values() for i in ids}

    def test_journals_sharing_a_publication(self, sa_sync_conn, repo):
        """Deux revues que les enregistrements d'une publication portent forment une paire."""
        full = _create_journal(sa_sync_conn, title="Journal test complet", issn="2999-0009")
        abbreviated = _create_journal(sa_sync_conn, title="J.Test Compl.")
        publication_id = sa_sync_conn.execute(
            text("INSERT INTO publications (title, pub_year) VALUES ('Article', 2024) RETURNING id")
        ).scalar_one()
        for journal_id in (full, abbreviated):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO source_publications"
                    " (source, source_id, title, journal_id, publication_id)"
                    " VALUES ('hal', :sid, 'Article', :jid, :pid)"
                ),
                {"sid": f"sp-publication-{journal_id}", "jid": journal_id, "pid": publication_id},
            )
        pairs = [
            p
            for p in repo.find_journals_sharing_a_publication()
            if {p.first.id, p.second.id} & {full, abbreviated}
        ]
        assert [(p.first.id, p.second.id, p.publications) for p in pairs] == [
            (full, abbreviated, 1)
        ]
        assert pairs[0].first.issns == frozenset({"2999-0009"})
        assert pairs[0].second.title == "J.Test Compl."

    def test_delete_empty_journals_spares_records_and_apc_payments(self, sa_sync_conn, repo):
        """Une revue vide est supprimée ; ses ISSN restent sans revue, sauf un ISSN déjà gardé sans revue."""
        empty = _create_journal(sa_sync_conn, title="Revue test vide", issn="2999-0007")
        _add_issn(sa_sync_conn, empty, "2999-0015", support="electronic")
        _add_issn(sa_sync_conn, None, "2999-0015", support="electronic", checked=True)
        with_record = _create_journal(sa_sync_conn, title="Revue test avec enregistrement")
        _create_record(sa_sync_conn, with_record, doi="10.9999/d")
        with_payment = _create_journal(sa_sync_conn, title="Revue test avec paiement")
        sa_sync_conn.execute(
            text("INSERT INTO apc_payments (journal_id) VALUES (:jid)"), {"jid": with_payment}
        )
        deleted = {j.id: j for j in repo.delete_empty_journals()}
        assert deleted[empty].title == "Revue test vide"
        assert deleted[empty].issns == ("2999-0007", "2999-0015")
        assert with_record not in deleted
        assert with_payment not in deleted
        orphans = _issns(sa_sync_conn, None)
        assert orphans["2999-0007"][:3] == ("print", False, "active")
        assert orphans["2999-0015"][3] is not None

    def test_describe_journals(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, title="Revue test décrite", eissn="2999-0008")
        summary = repo.describe_journals([journal_id])[journal_id]
        assert (summary.title, summary.publisher, summary.issns) == (
            "Revue test décrite",
            None,
            ("2999-0008",),
        )

    def test_record_writes_issns_and_date(self, sa_sync_conn, repo):
        """Les ISSN de la revue sont ceux de la vérification, datés ; un ISSN écarté reste sans revue."""
        journal_id = _create_journal(sa_sync_conn, issn="1476-4687", issnl="0028-0836")
        _add_issn(sa_sync_conn, journal_id, "0007-0920")
        at = datetime(2026, 9, 15, tzinfo=UTC)
        repo.record_sudoc_check(
            journal_id,
            issns=(
                JournalIssn(issn="0028-0836", support=IssnSupport.PRINT, linking=True),
                JournalIssn(issn="1476-4687", support=IssnSupport.ELECTRONIC),
            ),
            released=(JournalIssn(issn="0007-0920", support=IssnSupport.PRINT),),
            checked_at=at,
        )
        assert _issns(sa_sync_conn, journal_id) == {
            "0028-0836": ("print", True, "active", at),
            "1476-4687": ("electronic", False, "active", at),
        }
        assert _issns(sa_sync_conn, None)["0007-0920"] == ("print", False, "active", at)

    def test_record_writes_reference_title_and_its_name_form(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, title="ICORES 2023", issn="2184-4372")
        repo.record_sudoc_check(
            journal_id,
            issns=(JournalIssn(issn="2184-4372", support=IssnSupport.PRINT),),
            released=(),
            checked_at=datetime(2026, 9, 21, tzinfo=UTC),
            title="ICORES",
        )
        title, forms = sa_sync_conn.execute(
            text(
                "SELECT j.title, array_agg(f.form_normalized) FROM journals j"
                " JOIN journal_name_forms f ON f.journal_id = j.id WHERE j.id = :id GROUP BY j.title"
            ),
            {"id": journal_id},
        ).one()
        assert (title, forms) == ("ICORES", ["icores"])

    def test_queue_holds_the_journals_asked_for(self, sa_sync_conn, repo):
        journal_id = _create_journal(
            sa_sync_conn, title="ICORES 2023", issn="2184-4372", checked=True
        )
        assert journal_id not in {r.id for r in repo.find_journals_to_check_in_sudoc()}
        assert journal_id in {r.id for r in repo.find_journals_to_check_in_sudoc(also=[journal_id])}
        assert (journal_id, "ICORES 2023", JournalType.UNKNOWN) in (
            repo.find_titles_of_journals_with_issn()
        )


class TestAddJournalIssns:
    def test_adds_new_issns_and_fills_a_missing_support(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, checked=True)
        _add_issn(sa_sync_conn, journal_id, "0028-0836", checked=True)
        repo.add_journal_issns(
            journal_id,
            [
                JournalIssn(issn="0028-0836", support=IssnSupport.PRINT, linking=True),
                JournalIssn(issn="1476-4687", support=IssnSupport.ELECTRONIC),
            ],
        )
        issns = _issns(sa_sync_conn, journal_id)
        assert issns["0028-0836"][:3] == ("print", True, "active")
        assert issns["0028-0836"][3] is not None
        assert issns["1476-4687"] == ("electronic", False, "active", None)

    def test_claims_an_issn_kept_without_journal(self, sa_sync_conn, repo):
        _add_issn(sa_sync_conn, None, "2750-6185", support="electronic", checked=True)
        journal_id = _create_journal(sa_sync_conn, title="Spotlight")
        repo.add_journal_issns(journal_id, [JournalIssn(issn="2750-6185")])
        assert "2750-6185" not in _issns(sa_sync_conn, None)
        assert _issns(sa_sync_conn, journal_id)["2750-6185"][:3] == ("electronic", False, "active")

    def test_keeps_the_existing_issnl(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, issn="0028-0836", issnl="0028-0836")
        repo.add_journal_issns(journal_id, [JournalIssn(issn="1476-4687", linking=True)])
        issns = _issns(sa_sync_conn, journal_id)
        assert (issns["0028-0836"][1], issns["1476-4687"][1]) == (True, False)


class TestFindJournalsOfUnknownType:
    def test_returns_id_and_openalex_id(self, sa_sync_conn, repo):
        _create_journal(sa_sync_conn, openalex_id="S1")  # journal_type 'unknown' par défaut
        rows = repo.find_journals_of_unknown_type()
        assert rows
        for journal_id, oa_id in rows:
            assert isinstance(journal_id, int)
            assert isinstance(oa_id, str)

    def test_returns_only_unknown_type_with_openalex(self, sa_sync_conn, repo):
        needs = _create_journal(sa_sync_conn, openalex_id="S1")
        typed = _create_journal(sa_sync_conn, openalex_id="S2")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": typed}
        )
        _create_journal(sa_sync_conn, openalex_id=None)  # pas d'openalex_id

        ids = [jid for jid, _ in repo.find_journals_of_unknown_type()]
        assert needs in ids
        assert typed not in ids  # déjà typé → sorti de la file

    def test_respects_limit(self, sa_sync_conn, repo):
        for i in range(3):
            _create_journal(sa_sync_conn, openalex_id=f"S{i}")
        assert len(repo.find_journals_of_unknown_type(limit=2)) == 2

    def test_limit_zero_is_unlimited(self, sa_sync_conn, repo):
        for i in range(2):
            _create_journal(sa_sync_conn, openalex_id=f"S{i}")
        assert len(repo.find_journals_of_unknown_type(limit=0)) >= 2


class TestTitlesOfNonProceedingsJournals:
    def test_recueils_exclus_et_issn_signale(self, sa_sync_conn, repo):
        with_issnl = _create_journal(sa_sync_conn, title="NuFACT 2022", issnl="1234-5679")
        proceedings = _create_journal(sa_sync_conn, title="ESAFORM 2021")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'proceedings' WHERE id = :id"),
            {"id": proceedings},
        )

        rows = {r.id: r for r in repo.find_titles_of_non_proceedings_journals()}

        assert rows[with_issnl].has_issn is True
        assert proceedings not in rows


class TestRecordTypesOfUnknownJournals:
    def test_type_brut_avant_correction(self, sa_sync_conn, repo):
        """Un document retypé par la correction est compté avec son type de source."""
        jid = _create_journal(sa_sync_conn)
        sa_sync_conn.execute(
            text("""
                INSERT INTO source_publications (source, source_id, title, journal_id, doc_type, raw_metadata)
                VALUES ('crossref', '10.1/a', 'A', :jid, 'conference_paper',
                        '{"doc_type": {"raw": "book-chapter", "corrected_by": "X"}}'),
                       ('hal', 'hal-1', 'B', :jid, 'COMM', '{}')
            """),
            {"jid": jid},
        )

        rows = [r for r in repo.find_record_types_of_unknown_journals() if r.journal_id == jid]

        assert rows[0].records == (("crossref", "book-chapter"), ("hal", "COMM"))

    def test_revues_typees_et_vides_exclues(self, sa_sync_conn, repo):
        typed = _create_journal(sa_sync_conn)
        empty = _create_journal(sa_sync_conn)
        _create_record(sa_sync_conn, typed, doi="10.1/b")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": typed}
        )

        ids = {r.journal_id for r in repo.find_record_types_of_unknown_journals()}

        assert typed not in ids
        assert empty not in ids


class TestDoiNamespaces:
    def test_revue_posee_par_son_espace_exclue_des_temoins(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn)
        _create_record(sa_sync_conn, journal_id, doi="10.9001/abc.1")
        _create_record(sa_sync_conn, journal_id, doi="10.9001/abc.2")
        sa_sync_conn.execute(
            text(
                "UPDATE source_publications SET raw_metadata = CAST(:raw AS jsonb) WHERE doi = :doi"
            ),
            {"raw": '{"journal_id": {"raw": null, "corrected_by": "X"}}', "doi": "10.9001/abc.2"},
        )
        pairs = [p for p in repo.find_doi_journal_pairs() if p.journal_id == journal_id]
        assert [(p.doi, p.journal_type) for p in pairs] == [("10.9001/abc.1", JournalType.UNKNOWN)]

    def test_store_vide_puis_ecrit(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn)
        repo.store_doi_namespaces([DoiNamespace("10.9001/old.", journal_id, 5, 1.0)])
        repo.store_doi_namespaces([DoiNamespace("10.9001/abc.", journal_id, 8, 0.95)])
        rows = sa_sync_conn.execute(
            text("SELECT namespace, journal_id, dois, share FROM journal_doi_namespaces")
        ).all()
        assert [tuple(r) for r in rows] == [("10.9001/abc.", journal_id, 8, 0.95)]


class TestJournalIssnIndex:
    def test_exposes_every_valid_issn(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn, issn="1111-1111", eissn="2222-2222")
        _add_issn(sa_sync_conn, jid, "3333-3333", status=IssnStatus.RELATED_TITLE)
        _add_issn(sa_sync_conn, jid, "(Internet)", status=IssnStatus.MALFORMED)
        ours = [r.issn for r in repo.find_journal_issn_index() if r.journal_id == jid]
        assert ours == ["1111-1111", "2222-2222", "3333-3333"]

    def test_excludes_journals_with_no_issn(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn)
        assert jid not in [r.journal_id for r in repo.find_journal_issn_index()]


class TestDoajImport:
    def test_reset_is_in_doaj_clears_true_flags(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn, issn="3333-3333")
        sa_sync_conn.execute(
            text("UPDATE journals SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        assert repo.reset_is_in_doaj() >= 1
        assert (
            sa_sync_conn.execute(
                text("SELECT is_in_doaj FROM journals WHERE id = :id"), {"id": jid}
            ).scalar_one()
            is False
        )

    def test_last_import_at_returns_a_value_when_imported(self, sa_sync_conn, repo):
        d = datetime.now(UTC) - timedelta(days=3)
        _create_journal(sa_sync_conn, issn="4444-4444", imported_at=d)
        last = repo.doaj_last_import_at()
        assert last is not None and last >= d - timedelta(seconds=1)
