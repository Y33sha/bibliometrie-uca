"""Tests de caractérisation des services des revues et des éditeurs : édition, fusion, requalification."""

from datetime import UTC, datetime
from functools import partial

import pytest
from sqlalchemy import text

from application.ports.repositories.publisher_repository import PublisherUpdate
from application.ports.repositories.serial_repository import SerialIssnInput, SerialUpdate
from domain.errors import (
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.merge import MergedEntity
from domain.serials.issns import IssnSupport, SerialIssn
from domain.serials.serial import OaModel, SerialType
from infrastructure.repositories import (
    publisher_repository,
    serial_repository,
)
from interfaces.api import deps
from pipeline.transformation.publishing.publishers.store import PublisherStore
from pipeline.transformation.publishing.serials.check_serials_in_sudoc import (
    find_serials_to_check_in_sudoc,
    record_sudoc_check,
)
from pipeline.transformation.publishing.serials.enrich_serials_from_openalex import (
    update_serial_apc,
)
from pipeline.transformation.publishing.serials.serial_merge import SerialRecompute
from pipeline.transformation.publishing.serials.store import SerialStore
from pipeline.transformation.publishing.serials.type_proceedings_serials import (
    find_titles_of_non_proceedings_serials,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.serials import (
    insert_doi_prefix,
    insert_monograph,
    insert_publisher,
    insert_serial_with_issns,
    issn_columns,
    mark_checked_in_sudoc,
)
from tests.integration.helpers.sources import insert_source_record

# Revue « Nature » par défaut, sans devise d'APC.
_serial = partial(insert_serial_with_issns, title="Nature", apc_currency=None)

# Date de vérification Sudoc des tests.
_NOW = datetime(2026, 1, 1, tzinfo=UTC)

# Enregistrement source OpenAlex de 2024, de titre « T ».
_openalex_source_record = partial(
    insert_source_record, source="openalex", title="T", publication_year=2024
)


@pytest.fixture
def repo(sa_sync_conn):
    return serial_repository(sa_sync_conn)


@pytest.fixture
def gateway(sa_sync_conn):
    return SerialStore(sa_sync_conn)


@pytest.fixture
def publisher_repo(sa_sync_conn):
    return publisher_repository(sa_sync_conn)


@pytest.fixture
def publisher_store(sa_sync_conn):
    return PublisherStore(sa_sync_conn)


@pytest.fixture
def recompute(sa_sync_conn):
    return SerialRecompute(sa_sync_conn)


@pytest.fixture
def serial_service(sa_sync_conn):
    return deps.serial_service(sa_sync_conn)


@pytest.fixture
def publisher_service(sa_sync_conn):
    return deps.publisher_service(sa_sync_conn)


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un text() SELECT sync et retourne result.first() (Row ou None)."""
    return conn.execute(text(sql_text), params).first()


# ── Helpers ──────────────────────────────────────────────────────


# ── find_by_id (hydratation aggregates) ────────────────────────────


class TestPublisherFindById:
    def test_returns_none_if_missing(self, publisher_repo):
        assert publisher_repo.find_by_id(999999) is None

    def test_hydrates(self, sa_sync_conn, publisher_repo):
        publication_id = insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P123")
        p = publisher_repo.find_by_id(publication_id)
        assert p is not None
        assert p.id == publication_id
        assert p.name == "Elsevier"
        assert p.openalex_id == "P123"


class TestSerialFindById:
    def test_returns_none_if_missing(self, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal(self, sa_sync_conn, repo):
        jid = _serial(sa_sync_conn)
        j = repo.find_by_id(jid)
        assert j is not None
        assert j.id == jid
        assert j.title == "Nature"
        assert j.publisher_id is None
        assert j.apc_currency is None
        assert j.is_in_doaj is False

    def test_hydrates_full(self, sa_sync_conn, repo):
        publication_id = insert_publisher(sa_sync_conn, "PLOS")
        jid = _serial(
            sa_sync_conn,
            title="PLOS ONE",
            publisher_id=publication_id,
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
        assert j.publisher_id == publication_id
        assert j.issns == [
            SerialIssn(issn="1932-6203", support=IssnSupport.PRINT, linking=True),
        ]
        assert j.openalex_id == "S202381698"
        assert j.is_in_doaj is True
        assert j.oa_model == "full_oa"


class TestUpdateSerial:
    def test_raises_not_found(self, sa_sync_conn, serial_service):
        with pytest.raises(NotFoundError):
            serial_service.update_serial(999999, update=SerialUpdate(title="X"))

    def test_raises_on_empty_fields(self, sa_sync_conn, serial_service):
        j = _serial(sa_sync_conn)
        with pytest.raises(ValidationError):
            serial_service.update_serial(j, update=SerialUpdate())

    def test_updates_title_and_normalizes(self, sa_sync_conn, serial_service):
        j = _serial(sa_sync_conn, title="Old Title")
        serial_service.update_serial(j, update=SerialUpdate(title="Nature Medicine"))
        row = _fetch_one(
            sa_sync_conn, "SELECT title, title_normalized FROM serials WHERE id = :id", id=j
        )
        assert row.title == "Nature Medicine"
        assert row.title_normalized == "nature medicine"

    def test_partial_update(self, sa_sync_conn, serial_service):
        """Les ISSN fournis remplacent ceux de la revue ; un ISSN gardé conserve sa date de vérification."""
        j = _serial(sa_sync_conn, issn="0028-0836")
        mark_checked_in_sudoc(sa_sync_conn, j)
        serial_service.update_serial(
            j,
            update=SerialUpdate(
                issns=[
                    SerialIssnInput(issn="0028-0836", support=IssnSupport.PRINT),
                    SerialIssnInput(issn="1476-4687", support=IssnSupport.ELECTRONIC),
                ]
            ),
        )
        assert (
            _fetch_one(
                sa_sync_conn,
                "SELECT sudoc_checked_at FROM serial_issns WHERE serial_id = :id AND issn = '0028-0836'",
                id=j,
            ).sudoc_checked_at
            is not None
        )
        row = issn_columns(sa_sync_conn, j)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_normalizes_issn(self, sa_sync_conn, serial_service):
        j = _serial(sa_sync_conn)
        serial_service.update_serial(
            j,
            update=SerialUpdate(
                issns=[SerialIssnInput(issn="14764687", support=IssnSupport.ELECTRONIC)]
            ),
        )
        row = issn_columns(sa_sync_conn, j)
        assert row.eissn == "1476-4687"

    def test_type_saisi_a_la_main_hors_de_portee_du_pipeline(
        self, sa_sync_conn, gateway, serial_service
    ):
        """Un type saisi devient un champ saisi à la main : le typage des recueils d'actes ne le voit plus, et les écritures du pipeline s'abstiennent."""
        j = _serial(sa_sync_conn, title="2024 IEEE SENSORS")
        serial_service.update_serial(j, update=SerialUpdate(serial_type=SerialType.JOURNAL))

        assert j not in {r.id for r in find_titles_of_non_proceedings_serials(sa_sync_conn)}
        gateway.set_serial_type(j, SerialType.PROCEEDINGS)
        row = _fetch_one(
            sa_sync_conn,
            "SELECT serial_type::text AS serial_type, manual_fields FROM serials WHERE id = :id",
            id=j,
        )
        assert (row.serial_type, row.manual_fields) == ("journal", ["serial_type"])

    def test_champ_resoumis_sans_changement_non_marque(self, sa_sync_conn, serial_service):
        """Le formulaire renvoie tous les champs : seul un champ modifié devient saisi à la main."""
        j = _serial(sa_sync_conn, title="Same", serial_type="journal")
        serial_service.update_serial(
            j, update=SerialUpdate(title="Same", serial_type=SerialType.JOURNAL)
        )
        assert (
            _fetch_one(
                sa_sync_conn, "SELECT manual_fields FROM serials WHERE id = :id", id=j
            ).manual_fields
            == []
        )

    def test_apc_saisi_en_euros_hors_de_portee_du_pipeline(
        self, sa_sync_conn, gateway, serial_service
    ):
        j = _serial(sa_sync_conn, apc_amount=1000, apc_currency="USD")
        serial_service.update_serial(j, update=SerialUpdate(apc_amount=2499.99))

        update_serial_apc(sa_sync_conn, j, apc_amount=3000, apc_currency="GBP")

        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency, manual_fields FROM serials WHERE id = :id",
            id=j,
        )
        assert (float(row.apc_amount), row.apc_currency, row.manual_fields) == (
            2499.99,
            "EUR",
            ["apc"],
        )

    def test_titre_et_issn_saisis_hors_de_portee_du_sudoc(
        self, sa_sync_conn, gateway, serial_service
    ):
        """Des ISSN saisis à la main sortent de la vérification Sudoc et des ajouts par les notices Sudoc ; un titre saisi reste."""
        j = _serial(sa_sync_conn, title="Old", issn="0028-0836")
        serial_service.update_serial(
            j,
            update=SerialUpdate(
                title="New",
                issns=[SerialIssnInput(issn="1476-4687", support=IssnSupport.ELECTRONIC)],
            ),
        )

        assert j not in {r.id for r in find_serials_to_check_in_sudoc(sa_sync_conn, also=[j])}
        gateway.add_serial_issns(j, [SerialIssn(issn="0028-0836", support=IssnSupport.PRINT)])
        record_sudoc_check(sa_sync_conn, j, issns=[], released=[], checked_at=_NOW, title="Sudoc")

        row = _fetch_one(
            sa_sync_conn, "SELECT title, manual_fields FROM serials WHERE id = :id", id=j
        )
        assert (row.title, sorted(row.manual_fields)) == ("New", ["issns", "title"])
        assert issn_columns(sa_sync_conn, j).eissn == "1476-4687"
        assert issn_columns(sa_sync_conn, j).issn is None

    def test_modele_oa_vide_a_la_main_reste_vide(self, sa_sync_conn, gateway, serial_service):
        j = _serial(sa_sync_conn, oa_model="full_oa")
        serial_service.update_serial(j, update=SerialUpdate(oa_model=None))

        gateway.enrich_serial(j, oa_model=OaModel.SUBSCRIPTION)

        row = _fetch_one(
            sa_sync_conn, "SELECT oa_model, manual_fields FROM serials WHERE id = :id", id=j
        )
        assert (row.oa_model, row.manual_fields) == (None, ["oa_model"])

    def test_rejects_invalid_issn(self, sa_sync_conn, serial_service):
        j = _serial(sa_sync_conn, issn="0028-0836")
        with pytest.raises(ValidationError):
            serial_service.update_serial(
                j, update=SerialUpdate(issns=[SerialIssnInput(issn="1234-5678")])
            )
        row = issn_columns(sa_sync_conn, j)
        assert row.issn == "0028-0836"


class TestUpdatePublisher:
    def test_raises_not_found(self, sa_sync_conn, publisher_service):
        with pytest.raises(NotFoundError):
            publisher_service.update_publisher(999999, update=PublisherUpdate(name="X"))

    def test_raises_on_empty_fields(self, sa_sync_conn, publisher_service):
        p = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError):
            publisher_service.update_publisher(p, update=PublisherUpdate())

    def test_updates_name_and_normalizes(self, sa_sync_conn, publisher_service):
        p = insert_publisher(sa_sync_conn, "Old Name")
        publisher_service.update_publisher(p, update=PublisherUpdate(name="Springer Nature"))
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
        self, sa_sync_conn, target_type, source_type, expected, publisher_service
    ):
        target = insert_publisher(sa_sync_conn, "Target", publisher_type=target_type)
        source = insert_publisher(sa_sync_conn, "Source", publisher_type=source_type)
        publisher_service.merge_publishers(target, source)
        row = _fetch_one(
            sa_sync_conn,
            "SELECT publisher_type::text AS publisher_type FROM publishers WHERE id = :id",
            id=target,
        )
        assert row.publisher_type == expected
        assert redirect_of(sa_sync_conn, MergedEntity.PUBLISHER, source) == target

    def test_raises_on_self_merge(self, sa_sync_conn, publisher_service):
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError, match="identiques"):
            publisher_service.merge_publishers(p_id, p_id)

    def test_raises_on_missing_target(self, sa_sync_conn, publisher_service):
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="introuvable"):
            publisher_service.merge_publishers(999999, p_id)

    def test_raises_on_missing_source(self, sa_sync_conn, publisher_service):
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="introuvable"):
            publisher_service.merge_publishers(p_id, 999999)

    def test_transfers_serials_and_deletes_source(self, sa_sync_conn, publisher_service):
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        j1 = _serial(sa_sync_conn, title="Journal 1", publisher_id=source)

        publisher_service.merge_publishers(target, source)

        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM publishers WHERE id = :id", id=source)
        ) is None
        row = _fetch_one(sa_sync_conn, "SELECT publisher_id FROM serials WHERE id = :id", id=j1)
        assert row.publisher_id == target

    def test_transfers_monographs(self, sa_sync_conn, publisher_service):
        """La monographie garde un éditeur, qui la retrouve par son titre."""
        target = insert_publisher(sa_sync_conn, "Presses universitaires de Rennes")
        source = insert_publisher(sa_sync_conn, "PUR")
        monograph = insert_monograph(sa_sync_conn, "Livre", publisher_id=source)

        publisher_service.merge_publishers(target, source)

        row = _fetch_one(
            sa_sync_conn, "SELECT publisher_id FROM monographs WHERE id = :id", id=monograph
        )
        assert row.publisher_id == target

    def test_transfers_doi_prefixes(self, sa_sync_conn, publisher_service):
        """Régression : le préfixe DOI de l'éditeur absorbé perdait son éditeur, sans être résolu de nouveau."""
        target = insert_publisher(sa_sync_conn, "Elsevier BV")
        source = insert_publisher(sa_sync_conn, "Elsevier [1977-....]")
        insert_doi_prefix(
            sa_sync_conn, "10.99999", ra="Crossref", publisher_id=source, checked=True
        )

        publisher_service.merge_publishers(target, source)

        row = _fetch_one(
            sa_sync_conn, "SELECT publisher_id FROM doi_prefixes WHERE prefix = '10.99999'"
        )
        assert row.publisher_id == target

    def test_merges_same_title_serials(self, sa_sync_conn, publisher_service):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _serial(sa_sync_conn, publisher_id=target, issn="0028-0836")
        js = _serial(sa_sync_conn, publisher_id=source, eissn="1476-4687")
        insert_publication(sa_sync_conn, serial_id=js)

        publisher_service.merge_publishers(target, source)

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM serials WHERE id = :id", id=js)) is None
        row = issn_columns(sa_sync_conn, jt)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_merges_same_title_serials_with_only_source_openalex_id(
        self, sa_sync_conn, publisher_service
    ):
        """Cible sans openalex_id, source avec : la fusion doit déplacer
        l'openalex_id du source vers la cible sans violer UNIQUE(openalex_id)."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _serial(sa_sync_conn, publisher_id=target)
        js = _serial(sa_sync_conn, publisher_id=source, openalex_id="S4210225546")

        publisher_service.merge_publishers(target, source)

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM serials WHERE id = :id", id=js)) is None
        row = _fetch_one(sa_sync_conn, "SELECT openalex_id FROM serials WHERE id = :id", id=jt)
        assert row.openalex_id == "S4210225546"

    def test_raises_blocked_error_on_issn_conflict(self, sa_sync_conn, publisher_service):
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _serial(sa_sync_conn, publisher_id=target, issn="0028-0836")
        js = _serial(sa_sync_conn, publisher_id=source, issn="9999-9999")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            publisher_service.merge_publishers(target, source)

        blockers = exc_info.value.blocking_serials
        assert len(blockers) == 1
        b = blockers[0]
        assert b["target_serial_id"] == jt
        assert b["source_serial_id"] == js
        assert b["target_title"] == "Nature"
        assert b["source_title"] == "Nature"
        assert "ISSN" in b["reason"]
        assert "0028-0836" in b["reason"] and "9999-9999" in b["reason"]

    def test_blocks_when_target_has_internal_duplicate_titles(
        self, sa_sync_conn, publisher_service
    ):
        """Si la cible a 2 journaux au même titre et la source en a 1, la fusion
        N→1 casserait. On flagge ces paires comme blockers."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        _serial(sa_sync_conn, publisher_id=target, issn="0028-0836")
        _serial(sa_sync_conn, publisher_id=target, eissn="1476-4687")
        _serial(sa_sync_conn, publisher_id=source)

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            publisher_service.merge_publishers(target, source)

        blockers = exc_info.value.blocking_serials
        assert len(blockers) == 2
        for b in blockers:
            assert "doublon interne" in b["reason"]

    def test_collects_all_blockers_in_one_pass(self, sa_sync_conn, publisher_service):
        """Plusieurs paires de revues bloquantes → toutes remontées d'un coup."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        _serial(sa_sync_conn, title="Rev1", publisher_id=target, issn="1111-1111")
        _serial(sa_sync_conn, title="Rev1", publisher_id=source, issn="2222-2222")
        _serial(sa_sync_conn, title="Rev2", publisher_id=target, eissn="3333-3333")
        _serial(sa_sync_conn, title="Rev2", publisher_id=source, eissn="4444-4444")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            publisher_service.merge_publishers(target, source)

        assert len(exc_info.value.blocking_serials) == 2

    def test_transfers_openalex_id_when_target_has_none(self, sa_sync_conn, publisher_service):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source", openalex_id="P999")
        publisher_service.merge_publishers(target, source)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P999"

    def test_keeps_target_openalex_id_when_both_set(self, sa_sync_conn, publisher_service):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = insert_publisher(sa_sync_conn, "Target", openalex_id="P_TARGET")
        source = insert_publisher(sa_sync_conn, "Source", openalex_id="P_SOURCE")
        publisher_service.merge_publishers(target, source)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P_TARGET"


# ── merge_serials ─────────────────────────────────────────────────


class TestMergeSerials:
    def test_raises_on_self_merge(self, sa_sync_conn, serial_service):
        j_id = _serial(sa_sync_conn)
        with pytest.raises(ValidationError, match="identiques"):
            serial_service.merge_serials(j_id, j_id)

    def test_raises_on_missing_target(self, sa_sync_conn, serial_service):
        j_id = _serial(sa_sync_conn)
        with pytest.raises(NotFoundError, match="introuvable"):
            serial_service.merge_serials(999999, j_id)

    def test_raises_on_missing_source(self, sa_sync_conn, serial_service):
        j_id = _serial(sa_sync_conn)
        with pytest.raises(NotFoundError, match="introuvable"):
            serial_service.merge_serials(j_id, 999999)

    def test_transfers_publications(self, sa_sync_conn, serial_service):
        target = _serial(sa_sync_conn, title="Target")
        source = _serial(sa_sync_conn, title="Source")
        publication_id = insert_publication(sa_sync_conn, serial_id=source)
        # ≥1 source_record : sinon `refresh_from_sources` (déclenché par la
        # requalification post-merge) supprimerait la publication comme orpheline.
        _openalex_source_record(
            sa_sync_conn, publication_id, source_id="W-transfer", serial_id=source
        )

        serial_service.merge_serials(target, source)

        row = _fetch_one(
            sa_sync_conn, "SELECT serial_id FROM publications WHERE id = :id", id=publication_id
        )
        assert row.serial_id == target
        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM serials WHERE id = :id", id=source)
        ) is None
        assert redirect_of(sa_sync_conn, MergedEntity.SERIAL, source) == target

    def test_transfers_monographs(self, sa_sync_conn, serial_service):
        target = _serial(sa_sync_conn, title="Target")
        source = _serial(sa_sync_conn, title="Source")
        monograph = insert_monograph(sa_sync_conn, serial_id=source)

        serial_service.merge_serials(target, source)

        assert (
            _fetch_one(
                sa_sync_conn, "SELECT serial_id FROM monographs WHERE id = :id", id=monograph
            ).serial_id
            == target
        )

    def test_type_repris_garde_son_marqueur(self, sa_sync_conn, serial_service):
        target = _serial(sa_sync_conn, title="Target")
        source = _serial(sa_sync_conn, title="Source", serial_type="media")
        sa_sync_conn.execute(
            text("UPDATE serials SET manual_fields = '{serial_type}' WHERE id = :id"),
            {"id": source},
        )

        serial_service.merge_serials(target, source)

        row = _fetch_one(
            sa_sync_conn,
            "SELECT serial_type::text AS serial_type, manual_fields FROM serials WHERE id = :id",
            id=target,
        )
        assert (row.serial_type, row.manual_fields) == ("media", ["serial_type"])

    def test_apc_amount_and_currency_taken_together(self, sa_sync_conn, serial_service):
        """Sans APC, la cible prend le montant et la devise de la source."""
        target = _serial(sa_sync_conn, title="Target", apc_currency="EUR")
        source = _serial(sa_sync_conn, title="Source", apc_amount=100, apc_currency="USD")

        serial_service.merge_serials(target, source)

        row = _fetch_one(
            sa_sync_conn, "SELECT apc_amount, apc_currency FROM serials WHERE id = :id", id=target
        )
        assert (row.apc_amount, row.apc_currency) == (100, "USD")

    @pytest.mark.parametrize(
        ("target_type", "source_type", "expected"),
        [("unknown", "media", "media"), ("journal", "media", "journal")],
    )
    def test_unknown_type_takes_source_type(
        self, sa_sync_conn, serial_service, target_type, source_type, expected
    ):
        target = _serial(sa_sync_conn, title="Target", serial_type=target_type)
        source = _serial(sa_sync_conn, title="Source", serial_type=source_type)

        serial_service.merge_serials(target, source)

        row = _fetch_one(
            sa_sync_conn,
            "SELECT serial_type::text AS serial_type FROM serials WHERE id = :id",
            id=target,
        )
        assert row.serial_type == expected

    def test_unites_malformed_issns_and_resets_sudoc_check(self, sa_sync_conn, serial_service):
        """La cible reçoit les valeurs mal formées de la source et redevient à vérifier dans le Sudoc."""
        target = _serial(
            sa_sync_conn, title="Target", rejected=("1234-5678",), rejected_status="malformed"
        )
        mark_checked_in_sudoc(sa_sync_conn, target)
        source = _serial(
            sa_sync_conn,
            title="Source",
            rejected=("1234-5678", "(Internet)"),
            rejected_status="malformed",
        )

        serial_service.merge_serials(target, source)

        row = issn_columns(sa_sync_conn, target)
        assert row.rejected_issns == ["(Internet)", "1234-5678"]
        assert row.sudoc_checked_at is None

    def test_source_issns_join_the_target(self, sa_sync_conn, serial_service):
        """Titre précédent absorbé par le titre suivant : l'ISSN du titre précédent rejoint la cible, qui garde son propre ISSN."""
        target = _serial(sa_sync_conn, title="BMC Primary Care", eissn="2731-4553")
        source = _serial(
            sa_sync_conn,
            title="BMC Family Practice",
            eissn="1471-2296",
            rejected=("2731-4553",),
            rejected_status="related_title",
        )

        serial_service.merge_serials(target, source)

        row = issn_columns(sa_sync_conn, target)
        assert row.eissn == "2731-4553"
        assert row.rejected_issns == ["1471-2296"]

    def test_enriches_target_metadata(self, sa_sync_conn, serial_service):
        target = _serial(sa_sync_conn, title="Target")
        source = _serial(
            sa_sync_conn, title="Source", is_in_doaj=True, issn="1234-5678", eissn="9999-0000"
        )

        serial_service.merge_serials(target, source)

        row = issn_columns(sa_sync_conn, target)
        row.is_in_doaj = _fetch_one(
            sa_sync_conn, "SELECT is_in_doaj FROM serials WHERE id = :id", id=target
        ).is_in_doaj
        assert row.issn == "1234-5678"
        assert row.eissn == "9999-0000"
        assert row.is_in_doaj is True

    def test_does_not_overwrite_existing_fields(self, sa_sync_conn, serial_service):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = _serial(sa_sync_conn, title="Target", issn="0028-0836")
        source = _serial(sa_sync_conn, title="Source", issn="1234-5678")

        serial_service.merge_serials(target, source)

        row = issn_columns(sa_sync_conn, target)
        assert row.issn == "0028-0836"

    def test_requalifies_absorbed_publications_against_target_type(
        self, sa_sync_conn, serial_service
    ):
        """Fusionner une revue dans un média retype ses publications en `media`.

        Régression : avant ce hook, le merge repointait `serial_id` mais laissait
        les `doc_type` des publications absorbées inchangés.
        """
        media = _serial(sa_sync_conn, title="Le Monde")
        revue = _serial(sa_sync_conn, title="Revue X")
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'media' WHERE id = :id"), {"id": media}
        )
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'journal' WHERE id = :id"), {"id": revue}
        )
        publication = insert_publication(sa_sync_conn, serial_id=revue)
        sa_sync_conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": publication}
        )
        _openalex_source_record(
            sa_sync_conn,
            publication,
            source_id="W-merge-requalif",
            doc_type="article",
            serial_id=revue,
        )

        serial_service.merge_serials(media, revue)

        row = _fetch_one(
            sa_sync_conn,
            "SELECT doc_type, serial_id FROM publications WHERE id = :id",
            id=publication,
        )
        assert row.serial_id == media
        assert row.doc_type == "media"


# ── requalify_publications_for_serial (persistance enregistrement source + auto-cicatrisation) ──


class TestRequalifyPublicationsForSerial:
    def _seed(self, conn):
        """Journal 'journal' + une publication 'article' attestée par un enregistrement source 'article'."""
        serial = _serial(conn, title="Revue X")
        conn.execute(
            text("UPDATE serials SET serial_type = 'journal' WHERE id = :id"), {"id": serial}
        )
        publication = insert_publication(conn, serial_id=serial)
        conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": publication}
        )
        source_record = _openalex_source_record(
            conn, publication, source_id="W-requalif", doc_type="article", serial_id=serial
        )
        return serial, publication, source_record

    def test_persists_source_record_correction_and_retypes_publication(
        self, sa_sync_conn, serial_service
    ):
        serial, publication, source_record = self._seed(sa_sync_conn)
        # Le caller a déjà basculé le type (comme update_serial).
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'media' WHERE id = :id"), {"id": serial}
        )

        count = serial_service.requalify_publications_for_serial(serial)
        assert count == 1

        source_record_row = _fetch_one(
            sa_sync_conn,
            "SELECT doc_type, corrections FROM source_records WHERE id = :id",
            id=source_record,
        )
        # La colonne enregistrement source est persistée (ce que lira le matcher), avec le brut réversible.
        assert source_record_row.doc_type == "media"
        assert source_record_row.corrections == {
            "doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
        }
        publication_row = _fetch_one(
            sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=publication
        )
        assert publication_row.doc_type == "media"

    def test_self_heals_when_type_reverts(self, sa_sync_conn, serial_service):
        serial, publication, source_record = self._seed(sa_sync_conn)
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'media' WHERE id = :id"), {"id": serial}
        )
        serial_service.requalify_publications_for_serial(serial)

        # Le type revient à 'journal' : la correction doit être défaite, le brut restauré.
        sa_sync_conn.execute(
            text("UPDATE serials SET serial_type = 'journal' WHERE id = :id"), {"id": serial}
        )
        count = serial_service.requalify_publications_for_serial(serial)
        assert count == 1

        source_record_row = _fetch_one(
            sa_sync_conn,
            "SELECT doc_type, corrections FROM source_records WHERE id = :id",
            id=source_record,
        )
        assert source_record_row.doc_type == "article"
        assert source_record_row.corrections == {}
        publication_row = _fetch_one(
            sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=publication
        )
        assert publication_row.doc_type == "article"
