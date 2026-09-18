"""Tests d'intégration de `PgJournalGatewayQueries` : files d'enrichissement et index DOAJ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from infrastructure.pipeline.journals import PgJournalGatewayQueries


@pytest.fixture
def repo(sa_sync_conn):
    return PgJournalGatewayQueries(sa_sync_conn)


def _create_journal(
    conn, *, title="J", openalex_id=None, issn=None, eissn=None, issnl=None, imported_at=None
):
    return conn.execute(
        text("""
            INSERT INTO journals (title, title_normalized, openalex_id,
                                  issn, eissn, issnl, doaj_imported_at)
            VALUES (:title, lower(:title), :openalex_id, :issn, :eissn, :issnl, :imported_at)
            RETURNING id
        """),
        {
            "title": title,
            "openalex_id": openalex_id,
            "issn": issn,
            "eissn": eissn,
            "issnl": issnl,
            "imported_at": imported_at,
        },
    ).scalar_one()


def _create_record(conn, journal_id, *, doi):
    conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, journal_id, doi)"
            " VALUES ('hal', :sid, 'Article', :jid, :doi)"
        ),
        {"sid": f"sp-{journal_id}-{doi}", "jid": journal_id, "doi": doi},
    )


class TestSudocCheck:
    def test_queue_holds_unchecked_journals_with_an_issn(self, sa_sync_conn, repo):
        with_issn = _create_journal(sa_sync_conn, issn="0028-0836")
        without_issn = _create_journal(sa_sync_conn)
        rejected_only = _create_journal(sa_sync_conn)
        checked = _create_journal(sa_sync_conn, issn="1476-4687")
        sa_sync_conn.execute(
            text("UPDATE journals SET rejected_issns = '{1950-2051}' WHERE id = :id"),
            {"id": rejected_only},
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET sudoc_checked_at = now() WHERE id = :id"), {"id": checked}
        )
        rows = {r.id: r for r in repo.find_journals_to_check_in_sudoc()}
        assert with_issn in rows
        assert rows[rejected_only].rejected_issns == ("1950-2051",)
        assert without_issn not in rows
        assert checked not in rows

    def test_queue_holds_journals_whose_records_carry_an_unknown_issn(self, sa_sync_conn, repo):
        """Une revue vérifiée revient dans la file quand un de ses enregistrements porte un ISSN absent de ses ISSN."""
        journal_id = _create_journal(sa_sync_conn, issn="0149-5992")
        sa_sync_conn.execute(
            text("UPDATE journals SET sudoc_checked_at = now() WHERE id = :id"), {"id": journal_id}
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, journal_id, external_ids)"
                " VALUES ('hal', :sid, 'Article', :jid, CAST(:ids AS jsonb))"
            ),
            {
                "sid": f"sp-issn-{journal_id}",
                "jid": journal_id,
                "ids": '{"issn": ["1935-5548", "0149-5992"]}',
            },
        )
        rows = {r.id: r for r in repo.find_journals_to_check_in_sudoc()}
        assert rows[journal_id].document_issns == ("1935-5548",)

    def test_find_by_issn_reaches_rejected_issns(self, sa_sync_conn, repo):
        """Un ISSN rejeté sert au rapprochement ; une revue qui le porte dans ses colonnes passe avant."""
        rejecting = _create_journal(sa_sync_conn, issn="0305-1048")
        sa_sync_conn.execute(
            text("UPDATE journals SET rejected_issns = '{1362-4954}' WHERE id = :id"),
            {"id": rejecting},
        )
        assert repo.find_journal_by_issn_any("1362-4954") == rejecting
        carrying = _create_journal(sa_sync_conn, eissn="1362-4954")
        assert repo.find_journal_by_issn_any("1362-4954") == carrying

    def test_merge_groups_hold_checked_journals_sharing_an_issnl(self, sa_sync_conn, repo):
        """La revue qui porte le plus de publications vient en tête du groupe ; une revue non vérifiée en est exclue."""
        keeper = _create_journal(sa_sync_conn, issnl="2999-0001")
        absorbed = _create_journal(sa_sync_conn, issnl="2999-0001")
        unchecked = _create_journal(sa_sync_conn, issnl="2999-0001")
        sa_sync_conn.execute(
            text("UPDATE journals SET sudoc_checked_at = now() WHERE id = ANY(:ids)"),
            {"ids": [keeper, absorbed]},
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET pub_count = 3 WHERE id = :id"), {"id": keeper}
        )
        groups = {g.key: g.journal_ids for g in repo.find_journals_sharing_issnl()}
        assert groups["2999-0001"] == (keeper, absorbed)
        assert unchecked not in groups["2999-0001"]

    def test_shared_column_issn_groups_hold_titles(self, sa_sync_conn, repo):
        keeper = _create_journal(sa_sync_conn, title="BMJ", eissn="2999-0002")
        other = _create_journal(sa_sync_conn, title="BMJ British Medical Journal", issn="2999-0002")
        sa_sync_conn.execute(
            text("UPDATE journals SET sudoc_checked_at = now() WHERE id = ANY(:ids)"),
            {"ids": [keeper, other]},
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET pub_count = 4 WHERE id = :id"), {"id": keeper}
        )
        groups = {g.issn: g.journals for g in repo.find_journals_sharing_column_issn()}
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

    def test_journals_sharing_a_rejected_issn(self, sa_sync_conn, repo):
        """L'ISSN rejeté de l'une est dans les colonnes de l'autre ; la revue publiée le plus récemment vient en tête. Une revue non vérifiée reste hors de la règle."""
        earlier = _create_journal(sa_sync_conn, title="Revue test ancien titre", issn="2999-0012")
        later = _create_journal(sa_sync_conn, title="Revue test nouveau titre", eissn="2999-0013")
        unchecked = _create_journal(sa_sync_conn, title="Revue test non vérifiée", issn="2999-0014")
        sa_sync_conn.execute(
            text(
                "UPDATE journals SET rejected_issns = :r WHERE id = :id",
            ),
            [
                {"r": ["2999-0013"], "id": earlier},
                {"r": ["2999-0014"], "id": later},
            ],
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET sudoc_checked_at = now() WHERE id = ANY(:ids)"),
            {"ids": [earlier, later]},
        )
        for journal_id, year in ((earlier, 2020), (later, 2025)):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO source_publications (source, source_id, title, journal_id, pub_year)"
                    " VALUES ('hal', :sid, 'Article', :jid, :year)"
                ),
                {"sid": f"sp-rejete-{journal_id}", "jid": journal_id, "year": year},
            )
        groups = {g.key: g.journal_ids for g in repo.find_journals_sharing_a_rejected_issn()}
        assert groups["2999-0013"] == (later, earlier)
        assert "2999-0014" not in groups
        assert unchecked not in {i for ids in groups.values() for i in ids}

    def test_journals_sharing_a_publication(self, sa_sync_conn, repo):
        """Deux revues que les enregistrements d'une publication portent forment une paire ; une revue rattachée par le préfixe du DOI reste hors de la paire."""
        full = _create_journal(sa_sync_conn, title="Journal test complet", issn="2999-0009")
        abbreviated = _create_journal(sa_sync_conn, title="J.Test Compl.")
        by_prefix = _create_journal(sa_sync_conn, title="Revue test par préfixe")
        publication_id = sa_sync_conn.execute(
            text("INSERT INTO publications (title, pub_year) VALUES ('Article', 2024) RETURNING id")
        ).scalar_one()
        stash = '{"journal_id": {"raw": null, "corrected_by": "JOURNAL_BY_DOI_PREFIX"}}'
        for journal_id, raw_metadata in ((full, "{}"), (abbreviated, "{}"), (by_prefix, stash)):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO source_publications"
                    " (source, source_id, title, journal_id, publication_id, raw_metadata)"
                    " VALUES ('hal', :sid, 'Article', :jid, :pid, CAST(:raw AS jsonb))"
                ),
                {
                    "sid": f"sp-publication-{journal_id}",
                    "jid": journal_id,
                    "pid": publication_id,
                    "raw": raw_metadata,
                },
            )
        pairs = [
            p
            for p in repo.find_journals_sharing_a_publication()
            if {p.first.id, p.second.id} & {full, abbreviated, by_prefix}
        ]
        assert [(p.first.id, p.second.id, p.publications) for p in pairs] == [
            (full, abbreviated, 1)
        ]
        assert pairs[0].first.issns == frozenset({"2999-0009"})
        assert pairs[0].second.title == "J.Test Compl."

    def test_delete_empty_journals_spares_records_and_apc_payments(self, sa_sync_conn, repo):
        empty = _create_journal(sa_sync_conn, title="Revue test vide", issn="2999-0007")
        with_record = _create_journal(sa_sync_conn, title="Revue test avec enregistrement")
        _create_record(sa_sync_conn, with_record, doi="10.9999/d")
        with_payment = _create_journal(sa_sync_conn, title="Revue test avec paiement")
        sa_sync_conn.execute(
            text("INSERT INTO apc_payments (journal_id) VALUES (:jid)"), {"jid": with_payment}
        )
        deleted = {j.id: j for j in repo.delete_empty_journals()}
        assert deleted[empty].title == "Revue test vide"
        assert deleted[empty].issn == "2999-0007"
        assert with_record not in deleted
        assert with_payment not in deleted

    def test_describe_journals(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, title="Revue test décrite", eissn="2999-0008")
        summary = repo.describe_journals([journal_id])[journal_id]
        assert (summary.title, summary.publisher, summary.issn, summary.eissn) == (
            "Revue test décrite",
            None,
            None,
            "2999-0008",
        )

    def test_record_writes_issns_and_date(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, issn="1476-4687", issnl="0028-0836")
        at = datetime(2026, 9, 15, tzinfo=UTC)
        repo.record_sudoc_check(
            journal_id,
            issn="0028-0836",
            eissn="1476-4687",
            issnl="0028-0836",
            rejected_issns=(),
            checked_at=at,
        )
        row = sa_sync_conn.execute(
            text(
                "SELECT issn, eissn, issnl, rejected_issns, sudoc_checked_at "
                "FROM journals WHERE id = :id"
            ),
            {"id": journal_id},
        ).one()
        assert tuple(row) == ("0028-0836", "1476-4687", "0028-0836", [], at)


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


class TestJournalIssnIndex:
    def test_exposes_all_issn_fields(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn, issn="1111-1111", eissn="2222-2222")
        ours = [r for r in repo.find_journal_issn_index() if r.id == jid]
        assert ours and ours[0].issn == "1111-1111" and ours[0].eissn == "2222-2222"

    def test_excludes_journals_with_no_issn(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn)  # les trois formes nulles
        assert jid not in [r.id for r in repo.find_journal_issn_index()]


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
