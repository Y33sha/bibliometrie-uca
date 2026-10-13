"""Tests de caractérisation des services des revues et des éditeurs : édition, fusion, requalification."""

from datetime import UTC, datetime
from functools import partial

import pytest
from sqlalchemy import text

from application.ports.repositories.journal_repository import JournalIssnInput, JournalUpdate
from application.ports.repositories.publisher_repository import PublisherUpdate
from application.services.journals.core import (
    merge_journals,
    requalify_publications_for_journal,
    update_journal,
)
from application.services.publishers.core import (
    merge_publishers,
    update_publisher,
)
from domain.errors import (
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.journals.issns import IssnSupport, JournalIssn
from domain.journals.journal import JournalType, OaModel
from domain.merge import MergedEntity
from infrastructure.repositories import (
    journal_repository,
    publisher_repository,
)
from pipeline.transformation.publishing.journals.journal_merge import JournalRecompute
from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries
from pipeline.transformation.publishing.pub_counts import PubCountRecompute
from pipeline.transformation.publishing.publishers.publishers import PublisherGatewayQueries
from tests.integration.helpers.journals import (
    insert_doi_prefix,
    insert_journal_with_issns,
    insert_monograph,
    insert_publisher,
    issn_columns,
    mark_checked_in_sudoc,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.sources import insert_source_publication

# Revue « Nature » par défaut, sans devise d'APC.
_journal = partial(insert_journal_with_issns, title="Nature", apc_currency=None)

# Date de vérification Sudoc des tests.
_NOW = datetime(2026, 1, 1, tzinfo=UTC)

# Notice OpenAlex de 2024, de titre « T ».
_openalex_notice = partial(insert_source_publication, source="openalex", title="T", pub_year=2024)


@pytest.fixture
def repo(sa_sync_conn):
    return journal_repository(sa_sync_conn)


@pytest.fixture
def gateway(sa_sync_conn):
    return JournalGatewayQueries(sa_sync_conn)


@pytest.fixture
def publisher_repo(sa_sync_conn):
    return publisher_repository(sa_sync_conn)


@pytest.fixture
def publisher_gateway(sa_sync_conn):
    return PublisherGatewayQueries(sa_sync_conn)


@pytest.fixture
def recompute():
    return JournalRecompute()


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un text() SELECT sync et retourne result.first() (Row ou None)."""
    return conn.execute(text(sql_text), params).first()


# ── Helpers ──────────────────────────────────────────────────────


# ── find_by_id (hydratation aggregates) ────────────────────────────


class TestPublisherFindById:
    def test_returns_none_if_missing(self, publisher_repo):
        assert publisher_repo.find_by_id(999999) is None

    def test_hydrates(self, sa_sync_conn, publisher_repo):
        pub_id = insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P123")
        p = publisher_repo.find_by_id(pub_id)
        assert p is not None
        assert p.id == pub_id
        assert p.name == "Elsevier"
        assert p.openalex_id == "P123"


class TestJournalFindById:
    def test_returns_none_if_missing(self, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal(self, sa_sync_conn, repo):
        jid = _journal(sa_sync_conn)
        j = repo.find_by_id(jid)
        assert j is not None
        assert j.id == jid
        assert j.title == "Nature"
        assert j.publisher_id is None
        assert j.apc_currency is None
        assert j.is_in_doaj is False

    def test_hydrates_full(self, sa_sync_conn, repo):
        pub_id = insert_publisher(sa_sync_conn, "PLOS")
        jid = _journal(
            sa_sync_conn,
            title="PLOS ONE",
            publisher_id=pub_id,
            openalex_id="S202381698",
            is_in_doaj=True,
            oa_model="full_oa",
            apc_amount=1700,
            apc_currency="USD",
            issn="1932-6203",
            eissn="1932-6203",
            issnl="1932-6203",
        )
        j = repo.find_by_id(jid)
        assert j is not None
        assert j.title == "PLOS ONE"
        assert j.publisher_id == pub_id
        assert j.issns == [
            JournalIssn(issn="1932-6203", support=IssnSupport.PRINT, linking=True),
        ]
        assert j.openalex_id == "S202381698"
        assert j.is_in_doaj is True
        assert j.oa_model == "full_oa"


class TestUpdateJournal:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_journal(999999, update=JournalUpdate(title="X"), repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        j = _journal(sa_sync_conn)
        with pytest.raises(ValidationError):
            update_journal(j, update=JournalUpdate(), repo=repo)

    def test_updates_title_and_normalizes(self, sa_sync_conn, repo):
        j = _journal(sa_sync_conn, title="Old Title")
        update_journal(j, update=JournalUpdate(title="Nature Medicine"), repo=repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT title, title_normalized FROM journals WHERE id = :id", id=j
        )
        assert row.title == "Nature Medicine"
        assert row.title_normalized == "nature medicine"

    def test_partial_update(self, sa_sync_conn, repo):
        """Les ISSN fournis remplacent ceux de la revue ; un ISSN gardé conserve sa date de vérification."""
        j = _journal(sa_sync_conn, issn="0028-0836")
        mark_checked_in_sudoc(sa_sync_conn, j)
        update_journal(
            j,
            update=JournalUpdate(
                issns=[
                    JournalIssnInput(issn="0028-0836", support=IssnSupport.PRINT),
                    JournalIssnInput(issn="1476-4687", support=IssnSupport.ELECTRONIC),
                ]
            ),
            repo=repo,
        )
        assert (
            _fetch_one(
                sa_sync_conn,
                "SELECT sudoc_checked_at FROM journal_issns WHERE journal_id = :id AND issn = '0028-0836'",
                id=j,
            ).sudoc_checked_at
            is not None
        )
        row = issn_columns(sa_sync_conn, j)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_normalizes_issn(self, sa_sync_conn, repo):
        j = _journal(sa_sync_conn)
        update_journal(
            j,
            update=JournalUpdate(
                issns=[JournalIssnInput(issn="14764687", support=IssnSupport.ELECTRONIC)]
            ),
            repo=repo,
        )
        row = issn_columns(sa_sync_conn, j)
        assert row.eissn == "1476-4687"

    def test_type_saisi_a_la_main_hors_de_portee_du_pipeline(self, sa_sync_conn, repo, gateway):
        """Un type saisi devient un champ saisi à la main : le typage des recueils d'actes ne le voit plus, et les écritures du pipeline s'abstiennent."""
        j = _journal(sa_sync_conn, title="2024 IEEE SENSORS")
        update_journal(j, update=JournalUpdate(journal_type=JournalType.JOURNAL), repo=repo)

        assert j not in {r.id for r in gateway.find_titles_of_non_proceedings_journals()}
        gateway.set_journal_type(j, JournalType.PROCEEDINGS)
        row = _fetch_one(
            sa_sync_conn,
            "SELECT journal_type::text AS journal_type, manual_fields FROM journals WHERE id = :id",
            id=j,
        )
        assert (row.journal_type, row.manual_fields) == ("journal", ["journal_type"])

    def test_champ_resoumis_sans_changement_non_marque(self, sa_sync_conn, repo):
        """Le formulaire renvoie tous les champs : seul un champ modifié devient saisi à la main."""
        j = _journal(sa_sync_conn, title="Same", journal_type="journal")
        update_journal(
            j, update=JournalUpdate(title="Same", journal_type=JournalType.JOURNAL), repo=repo
        )
        assert (
            _fetch_one(
                sa_sync_conn, "SELECT manual_fields FROM journals WHERE id = :id", id=j
            ).manual_fields
            == []
        )

    def test_apc_saisi_en_euros_hors_de_portee_du_pipeline(self, sa_sync_conn, repo, gateway):
        j = _journal(sa_sync_conn, apc_amount=1000, apc_currency="USD")
        update_journal(j, update=JournalUpdate(apc_amount=2499.99), repo=repo)

        gateway.update_journal_apc(j, apc_amount=3000, apc_currency="GBP")

        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency, manual_fields FROM journals WHERE id = :id",
            id=j,
        )
        assert (float(row.apc_amount), row.apc_currency, row.manual_fields) == (
            2499.99,
            "EUR",
            ["apc"],
        )

    def test_titre_et_issn_saisis_hors_de_portee_du_sudoc(self, sa_sync_conn, repo, gateway):
        """Des ISSN saisis à la main sortent de la vérification Sudoc et des ajouts par les notices ; un titre saisi reste."""
        j = _journal(sa_sync_conn, title="Old", issn="0028-0836")
        update_journal(
            j,
            update=JournalUpdate(
                title="New",
                issns=[JournalIssnInput(issn="1476-4687", support=IssnSupport.ELECTRONIC)],
            ),
            repo=repo,
        )

        assert j not in {r.id for r in gateway.find_journals_to_check_in_sudoc(also=[j])}
        gateway.add_journal_issns(j, [JournalIssn(issn="0028-0836", support=IssnSupport.PRINT)])
        gateway.record_sudoc_check(j, issns=[], released=[], checked_at=_NOW, title="Sudoc")

        row = _fetch_one(
            sa_sync_conn, "SELECT title, manual_fields FROM journals WHERE id = :id", id=j
        )
        assert (row.title, sorted(row.manual_fields)) == ("New", ["issns", "title"])
        assert issn_columns(sa_sync_conn, j).eissn == "1476-4687"
        assert issn_columns(sa_sync_conn, j).issn is None

    def test_modele_oa_vide_a_la_main_reste_vide(self, sa_sync_conn, repo, gateway):
        j = _journal(sa_sync_conn, oa_model="full_oa")
        update_journal(j, update=JournalUpdate(oa_model=None), repo=repo)

        gateway.enrich_journal(j, oa_model=OaModel.SUBSCRIPTION)

        row = _fetch_one(
            sa_sync_conn, "SELECT oa_model, manual_fields FROM journals WHERE id = :id", id=j
        )
        assert (row.oa_model, row.manual_fields) == (None, ["oa_model"])

    def test_rejects_invalid_issn(self, sa_sync_conn, repo):
        j = _journal(sa_sync_conn, issn="0028-0836")
        with pytest.raises(ValidationError):
            update_journal(
                j, update=JournalUpdate(issns=[JournalIssnInput(issn="1234-5678")]), repo=repo
            )
        row = issn_columns(sa_sync_conn, j)
        assert row.issn == "0028-0836"


class TestUpdatePublisher:
    def test_raises_not_found(self, sa_sync_conn, publisher_repo):
        with pytest.raises(NotFoundError):
            update_publisher(999999, update=PublisherUpdate(name="X"), repo=publisher_repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, publisher_repo):
        p = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError):
            update_publisher(p, update=PublisherUpdate(), repo=publisher_repo)

    def test_updates_name_and_normalizes(self, sa_sync_conn, publisher_repo):
        p = insert_publisher(sa_sync_conn, "Old Name")
        update_publisher(p, update=PublisherUpdate(name="Springer Nature"), repo=publisher_repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT name, name_normalized FROM publishers WHERE id = :id", id=p
        )
        assert row.name == "Springer Nature"
        assert row.name_normalized == "springer nature"


# ── merge_publishers ───────────────────────────────────────────────


class TestMergePublishers:
    @pytest.mark.parametrize(
        ("target_type", "source_type", "expected"),
        [("unknown", "commercial", "commercial"), ("media", "commercial", "media")],
    )
    def test_unknown_type_takes_source_type(
        self,
        sa_sync_conn,
        repo,
        publisher_repo,
        recompute,
        target_type,
        source_type,
        expected,
    ):
        target = insert_publisher(sa_sync_conn, "Target", publisher_type=target_type)
        source = insert_publisher(sa_sync_conn, "Source", publisher_type=source_type)
        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )
        row = _fetch_one(
            sa_sync_conn,
            "SELECT publisher_type::text AS publisher_type FROM publishers WHERE id = :id",
            id=target,
        )
        assert row.publisher_type == expected
        assert redirect_of(sa_sync_conn, MergedEntity.PUBLISHER, source) == target

    def test_raises_on_self_merge(self, sa_sync_conn, repo, publisher_repo, recompute):
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError, match="identiques"):
            merge_publishers(
                p_id,
                p_id,
                conn=sa_sync_conn,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                recompute=recompute,
                pub_count_recompute=PubCountRecompute(),
            )

    def test_raises_on_missing_target(self, sa_sync_conn, repo, publisher_repo, recompute):
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_publishers(
                999999,
                p_id,
                conn=sa_sync_conn,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                recompute=recompute,
                pub_count_recompute=PubCountRecompute(),
            )

    def test_raises_on_missing_source(self, sa_sync_conn, repo, publisher_repo, recompute):
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_publishers(
                p_id,
                999999,
                conn=sa_sync_conn,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                recompute=recompute,
                pub_count_recompute=PubCountRecompute(),
            )

    def test_transfers_journals_and_deletes_source(
        self, sa_sync_conn, repo, publisher_repo, recompute
    ):
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        j1 = _journal(sa_sync_conn, title="Journal 1", publisher_id=source)

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )

        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM publishers WHERE id = :id", id=source)
        ) is None
        row = _fetch_one(sa_sync_conn, "SELECT publisher_id FROM journals WHERE id = :id", id=j1)
        assert row.publisher_id == target

    def test_transfers_monographs(self, sa_sync_conn, repo, publisher_repo, recompute):
        """La monographie garde un éditeur, qui la retrouve par son titre."""
        target = insert_publisher(sa_sync_conn, "Presses universitaires de Rennes")
        source = insert_publisher(sa_sync_conn, "PUR")
        monograph = insert_monograph(sa_sync_conn, "Livre", publisher_id=source)

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT publisher_id FROM monographs WHERE id = :id", id=monograph
        )
        assert row.publisher_id == target

    def test_transfers_doi_prefixes(self, sa_sync_conn, repo, publisher_repo, recompute):
        """Régression : le préfixe DOI de l'éditeur absorbé perdait son éditeur, sans être résolu de nouveau."""
        target = insert_publisher(sa_sync_conn, "Elsevier BV")
        source = insert_publisher(sa_sync_conn, "Elsevier [1977-....]")
        insert_doi_prefix(
            sa_sync_conn, "10.99999", ra="Crossref", publisher_id=source, checked=True
        )

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT publisher_id FROM doi_prefixes WHERE prefix = '10.99999'"
        )
        assert row.publisher_id == target

    def test_merges_same_title_journals(self, sa_sync_conn, repo, publisher_repo, recompute):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _journal(sa_sync_conn, publisher_id=target, issn="0028-0836")
        js = _journal(sa_sync_conn, publisher_id=source, eissn="1476-4687")
        insert_publication(sa_sync_conn, journal_id=js)

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        row = issn_columns(sa_sync_conn, jt)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_merges_same_title_journals_with_only_source_openalex_id(
        self, sa_sync_conn, repo, publisher_repo, recompute
    ):
        """Cible sans openalex_id, source avec : la fusion doit déplacer
        l'openalex_id du source vers la cible sans violer UNIQUE(openalex_id)."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _journal(sa_sync_conn, publisher_id=target)
        js = _journal(sa_sync_conn, publisher_id=source, openalex_id="S4210225546")

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        row = _fetch_one(sa_sync_conn, "SELECT openalex_id FROM journals WHERE id = :id", id=jt)
        assert row.openalex_id == "S4210225546"

    def test_raises_blocked_error_on_issn_conflict(
        self, sa_sync_conn, repo, publisher_repo, recompute
    ):
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _journal(sa_sync_conn, publisher_id=target, issn="0028-0836")
        js = _journal(sa_sync_conn, publisher_id=source, issn="9999-9999")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                recompute=recompute,
                pub_count_recompute=PubCountRecompute(),
            )

        blockers = exc_info.value.blocking_journals
        assert len(blockers) == 1
        b = blockers[0]
        assert b["target_journal_id"] == jt
        assert b["source_journal_id"] == js
        assert b["target_title"] == "Nature"
        assert b["source_title"] == "Nature"
        assert "ISSN" in b["reason"]
        assert "0028-0836" in b["reason"] and "9999-9999" in b["reason"]

    def test_blocks_when_target_has_internal_duplicate_titles(
        self, sa_sync_conn, repo, publisher_repo, recompute
    ):
        """Si la cible a 2 journaux au même titre et la source en a 1, la fusion
        N→1 casserait. On flagge ces paires comme blockers."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        _journal(sa_sync_conn, publisher_id=target, issn="0028-0836")
        _journal(sa_sync_conn, publisher_id=target, eissn="1476-4687")
        _journal(sa_sync_conn, publisher_id=source)

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                recompute=recompute,
                pub_count_recompute=PubCountRecompute(),
            )

        blockers = exc_info.value.blocking_journals
        assert len(blockers) == 2
        for b in blockers:
            assert "doublon interne" in b["reason"]

    def test_collects_all_blockers_in_one_pass(self, sa_sync_conn, repo, publisher_repo, recompute):
        """Plusieurs paires de revues bloquantes → toutes remontées d'un coup."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        _journal(sa_sync_conn, title="Rev1", publisher_id=target, issn="1111-1111")
        _journal(sa_sync_conn, title="Rev1", publisher_id=source, issn="2222-2222")
        _journal(sa_sync_conn, title="Rev2", publisher_id=target, eissn="3333-3333")
        _journal(sa_sync_conn, title="Rev2", publisher_id=source, eissn="4444-4444")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                recompute=recompute,
                pub_count_recompute=PubCountRecompute(),
            )

        assert len(exc_info.value.blocking_journals) == 2

    def test_transfers_openalex_id_when_target_has_none(
        self, sa_sync_conn, repo, publisher_repo, recompute
    ):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source", openalex_id="P999")
        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P999"

    def test_keeps_target_openalex_id_when_both_set(
        self, sa_sync_conn, repo, publisher_repo, recompute
    ):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = insert_publisher(sa_sync_conn, "Target", openalex_id="P_TARGET")
        source = insert_publisher(sa_sync_conn, "Source", openalex_id="P_SOURCE")
        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            recompute=recompute,
            pub_count_recompute=PubCountRecompute(),
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P_TARGET"


# ── merge_journals ─────────────────────────────────────────────────


class TestMergeJournals:
    def test_raises_on_self_merge(self, sa_sync_conn, repo, recompute):
        j_id = _journal(sa_sync_conn)
        with pytest.raises(ValidationError, match="identiques"):
            merge_journals(
                j_id,
                j_id,
                conn=sa_sync_conn,
                repo=repo,
                recompute=recompute,
            )

    def test_raises_on_missing_target(self, sa_sync_conn, repo, recompute):
        j_id = _journal(sa_sync_conn)
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_journals(
                999999,
                j_id,
                conn=sa_sync_conn,
                repo=repo,
                recompute=recompute,
            )

    def test_raises_on_missing_source(self, sa_sync_conn, repo, recompute):
        j_id = _journal(sa_sync_conn)
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_journals(
                j_id,
                999999,
                conn=sa_sync_conn,
                repo=repo,
                recompute=recompute,
            )

    def test_transfers_publications(self, sa_sync_conn, repo, recompute):
        target = _journal(sa_sync_conn, title="Target")
        source = _journal(sa_sync_conn, title="Source")
        pub_id = insert_publication(sa_sync_conn, journal_id=source)
        # ≥1 source_publication : sinon `refresh_from_sources` (déclenché par la
        # requalification post-merge) supprimerait la publication comme orpheline.
        _openalex_notice(sa_sync_conn, pub_id, source_id="W-transfer", journal_id=source)

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            repo=repo,
            recompute=recompute,
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT journal_id FROM publications WHERE id = :id", id=pub_id
        )
        assert row.journal_id == target
        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=source)
        ) is None
        assert redirect_of(sa_sync_conn, MergedEntity.JOURNAL, source) == target

    def _merge(self, conn, repo, recompute, target, source):
        merge_journals(
            target,
            source,
            conn=conn,
            repo=repo,
            recompute=recompute,
        )

    def test_transfers_monographs(self, sa_sync_conn, repo, recompute):
        target = _journal(sa_sync_conn, title="Target")
        source = _journal(sa_sync_conn, title="Source")
        monograph = insert_monograph(sa_sync_conn, journal_id=source)

        self._merge(sa_sync_conn, repo, recompute, target, source)

        assert (
            _fetch_one(
                sa_sync_conn, "SELECT journal_id FROM monographs WHERE id = :id", id=monograph
            ).journal_id
            == target
        )

    def test_type_repris_garde_son_marqueur(self, sa_sync_conn, repo, recompute):
        target = _journal(sa_sync_conn, title="Target")
        source = _journal(sa_sync_conn, title="Source", journal_type="media")
        sa_sync_conn.execute(
            text("UPDATE journals SET manual_fields = '{journal_type}' WHERE id = :id"),
            {"id": source},
        )

        self._merge(sa_sync_conn, repo, recompute, target, source)

        row = _fetch_one(
            sa_sync_conn,
            "SELECT journal_type::text AS journal_type, manual_fields FROM journals WHERE id = :id",
            id=target,
        )
        assert (row.journal_type, row.manual_fields) == ("media", ["journal_type"])

    def test_apc_amount_and_currency_taken_together(self, sa_sync_conn, repo, recompute):
        """Sans APC, la cible prend le montant et la devise de la source."""
        target = _journal(sa_sync_conn, title="Target", apc_currency="EUR")
        source = _journal(sa_sync_conn, title="Source", apc_amount=100, apc_currency="USD")

        self._merge(sa_sync_conn, repo, recompute, target, source)

        row = _fetch_one(
            sa_sync_conn, "SELECT apc_amount, apc_currency FROM journals WHERE id = :id", id=target
        )
        assert (row.apc_amount, row.apc_currency) == (100, "USD")

    @pytest.mark.parametrize(
        ("target_type", "source_type", "expected"),
        [("unknown", "media", "media"), ("journal", "media", "journal")],
    )
    def test_unknown_type_takes_source_type(
        self, sa_sync_conn, repo, recompute, target_type, source_type, expected
    ):
        target = _journal(sa_sync_conn, title="Target", journal_type=target_type)
        source = _journal(sa_sync_conn, title="Source", journal_type=source_type)

        self._merge(sa_sync_conn, repo, recompute, target, source)

        row = _fetch_one(
            sa_sync_conn,
            "SELECT journal_type::text AS journal_type FROM journals WHERE id = :id",
            id=target,
        )
        assert row.journal_type == expected

    def test_unites_malformed_issns_and_resets_sudoc_check(self, sa_sync_conn, repo, recompute):
        """La cible reçoit les valeurs mal formées de la source et redevient à vérifier dans le Sudoc."""
        target = _journal(
            sa_sync_conn, title="Target", rejected=("1234-5678",), rejected_status="malformed"
        )
        mark_checked_in_sudoc(sa_sync_conn, target)
        source = _journal(
            sa_sync_conn,
            title="Source",
            rejected=("1234-5678", "(Internet)"),
            rejected_status="malformed",
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            repo=repo,
            recompute=recompute,
        )

        row = issn_columns(sa_sync_conn, target)
        assert row.rejected_issns == ["(Internet)", "1234-5678"]
        assert row.sudoc_checked_at is None

    def test_source_issns_join_the_target(self, sa_sync_conn, repo, recompute):
        """Titre précédent absorbé par le titre suivant : l'ISSN du titre précédent rejoint la cible, qui garde son propre ISSN."""
        target = _journal(sa_sync_conn, title="BMC Primary Care", eissn="2731-4553")
        source = _journal(
            sa_sync_conn,
            title="BMC Family Practice",
            eissn="1471-2296",
            rejected=("2731-4553",),
            rejected_status="related_title",
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            repo=repo,
            recompute=recompute,
        )

        row = issn_columns(sa_sync_conn, target)
        assert row.eissn == "2731-4553"
        assert row.rejected_issns == ["1471-2296"]

    def test_enriches_target_metadata(self, sa_sync_conn, repo, recompute):
        target = _journal(sa_sync_conn, title="Target")
        source = _journal(
            sa_sync_conn, title="Source", is_in_doaj=True, issn="1234-5678", eissn="9999-0000"
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            repo=repo,
            recompute=recompute,
        )

        row = issn_columns(sa_sync_conn, target)
        row.is_in_doaj = _fetch_one(
            sa_sync_conn, "SELECT is_in_doaj FROM journals WHERE id = :id", id=target
        ).is_in_doaj
        assert row.issn == "1234-5678"
        assert row.eissn == "9999-0000"
        assert row.is_in_doaj is True

    def test_does_not_overwrite_existing_fields(self, sa_sync_conn, repo, recompute):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = _journal(sa_sync_conn, title="Target", issn="0028-0836")
        source = _journal(sa_sync_conn, title="Source", issn="1234-5678")

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            repo=repo,
            recompute=recompute,
        )

        row = issn_columns(sa_sync_conn, target)
        assert row.issn == "0028-0836"

    def test_requalifies_absorbed_publications_against_target_type(
        self, sa_sync_conn, repo, recompute
    ):
        """Fusionner une revue dans un média retype ses publications en `media`.

        Régression : avant ce hook, le merge repointait `journal_id` mais laissait
        les `doc_type` des publications absorbées inchangés.
        """
        media = _journal(sa_sync_conn, title="Le Monde")
        revue = _journal(sa_sync_conn, title="Revue X")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": media}
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": revue}
        )
        pub = insert_publication(sa_sync_conn, journal_id=revue)
        sa_sync_conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": pub}
        )
        _openalex_notice(
            sa_sync_conn, pub, source_id="W-merge-requalif", doc_type="article", journal_id=revue
        )

        merge_journals(
            media,
            revue,
            conn=sa_sync_conn,
            repo=repo,
            recompute=recompute,
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT doc_type, journal_id FROM publications WHERE id = :id", id=pub
        )
        assert row.journal_id == media
        assert row.doc_type == "media"


# ── requalify_publications_for_journal (persistance SP + auto-cicatrisation) ──


class TestRequalifyPublicationsForJournal:
    def _seed(self, conn):
        """Journal 'journal' + une publication 'article' attestée par une SP 'article'."""
        journal = _journal(conn, title="Revue X")
        conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": journal}
        )
        pub = insert_publication(conn, journal_id=journal)
        conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": pub}
        )
        sp = _openalex_notice(
            conn, pub, source_id="W-requalif", doc_type="article", journal_id=journal
        )
        return journal, pub, sp

    def test_persists_sp_correction_and_retypes_publication(self, sa_sync_conn, recompute):
        journal, pub, sp = self._seed(sa_sync_conn)
        # Le caller a déjà basculé le type (comme update_journal).
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": journal}
        )

        count = requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            recompute=recompute,
        )
        assert count == 1

        sp_row = _fetch_one(
            sa_sync_conn,
            "SELECT doc_type, raw_metadata FROM source_publications WHERE id = :id",
            id=sp,
        )
        # La colonne SP est persistée (ce que lira le matcher), avec le brut réversible.
        assert sp_row.doc_type == "media"
        assert sp_row.raw_metadata == {
            "doc_type": {"raw": "article", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
        }
        pub_row = _fetch_one(
            sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=pub
        )
        assert pub_row.doc_type == "media"

    def test_self_heals_when_type_reverts(self, sa_sync_conn, recompute):
        journal, pub, sp = self._seed(sa_sync_conn)
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": journal}
        )
        requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            recompute=recompute,
        )

        # Le type revient à 'journal' : la correction doit être défaite, le brut restauré.
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": journal}
        )
        count = requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            recompute=recompute,
        )
        assert count == 1

        sp_row = _fetch_one(
            sa_sync_conn,
            "SELECT doc_type, raw_metadata FROM source_publications WHERE id = :id",
            id=sp,
        )
        assert sp_row.doc_type == "article"
        assert sp_row.raw_metadata == {}
        pub_row = _fetch_one(
            sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=pub
        )
        assert pub_row.doc_type == "article"
