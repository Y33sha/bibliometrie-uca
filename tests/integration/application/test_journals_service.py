"""Tests de caractérisation pour application/journals/core.py et
application/publishers/core.py.

Couvre les fonctions sync (find_or_create_*, update_journal_apc — utilisées
par le pipeline) et les fonctions async (update_journal, update_publisher,
merge_*).
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from application.ports.repositories.journal_repository import JournalIssnInput, JournalUpdate
from application.ports.repositories.publisher_repository import PublisherUpdate
from application.services.journals.core import (
    find_or_create_journal,
    merge_journals,
    requalify_publications_for_journal,
    update_journal,
    update_journal_apc,
)
from application.services.publishers.core import (
    find_or_create_publisher,
    merge_publishers,
    update_publisher,
)
from domain.errors import (
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.journals.issns import IssnSupport, JournalIssn
from infrastructure.pipeline.journals import PgJournalGatewayQueries
from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)

# Stateless (connexion passée aux méthodes) → une instance module suffit.
_CORRECTION_QUERIES = PgMetadataCorrectionQueries()


@pytest.fixture
def repo(sa_sync_conn):
    return journal_repository(sa_sync_conn)


@pytest.fixture
def gateway(sa_sync_conn):
    return PgJournalGatewayQueries(sa_sync_conn)


@pytest.fixture
def publisher_repo(sa_sync_conn):
    return publisher_repository(sa_sync_conn)


@pytest.fixture
def publisher_gateway(sa_sync_conn):
    return PgPublisherGatewayQueries(sa_sync_conn)


@pytest.fixture
def publication_repo(sa_sync_conn):
    return publication_repository(sa_sync_conn)


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un text() SELECT sync et retourne result.first() (Row ou None)."""
    return conn.execute(text(sql_text), params).first()


# ── Helpers ──────────────────────────────────────────────────────


def _insert_publisher(conn, name="Elsevier", openalex_id=None):
    return conn.execute(
        text(
            "INSERT INTO publishers (name, name_normalized, openalex_id) "
            "VALUES (:name, lower(:name), :oa_id) RETURNING id"
        ),
        {"name": name, "oa_id": openalex_id},
    ).scalar_one()


def _add_issn(conn, journal_id, issn, *, support=None, linking=False, status="active"):
    conn.execute(
        text(
            "INSERT INTO journal_issns (issn, journal_id, support, linking, status) "
            "VALUES (:issn, :jid, CAST(:support AS issn_support), :linking, "
            "        CAST(:status AS issn_status))"
        ),
        {"issn": issn, "jid": journal_id, "support": support, "linking": linking, "status": status},
    )


def _mark_checked_in_sudoc(conn, journal_id: int) -> None:
    conn.execute(
        text("UPDATE journal_issns SET sudoc_checked_at = now() WHERE journal_id = :id"),
        {"id": journal_id},
    )


def _columns(conn, journal_id: int) -> SimpleNamespace:
    """Premier ISSN papier et électronique actifs, ISSN-L, autres valeurs, et date de vérification si tous les ISSN sont vérifiés."""
    rows = conn.execute(
        text(
            "SELECT issn, support::text AS support, linking, status::text AS status, "
            "sudoc_checked_at FROM journal_issns WHERE journal_id = :id ORDER BY id"
        ),
        {"id": journal_id},
    ).all()

    def first(support):
        return next((r.issn for r in rows if r.status == "active" and r.support == support), None)

    issn, eissn = first("print"), first("electronic")
    issnl = next((r.issn for r in rows if r.linking), None)
    checked = [r.sudoc_checked_at for r in rows]
    return SimpleNamespace(
        issn=issn,
        eissn=eissn,
        issnl=issnl,
        rejected_issns=sorted(r.issn for r in rows if r.issn not in (issn, eissn, issnl)),
        sudoc_checked_at=min(checked) if checked and all(checked) else None,
    )


def _insert_journal(conn, title="Nature", publisher_id=None, **kwargs):
    journal_id = conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, "
            "                      publisher_id, openalex_id, apc_amount, apc_currency, "
            "                      is_in_doaj, oa_model) "
            "VALUES (:title, lower(:title), "
            "        :pub_id, :oa_id, :apc_amount, :apc_currency, "
            "        :is_in_doaj, :oa_model) RETURNING id"
        ),
        {
            "title": title,
            "pub_id": publisher_id,
            "oa_id": kwargs.get("openalex_id"),
            "apc_amount": kwargs.get("apc_amount"),
            "apc_currency": kwargs.get("apc_currency"),
            "is_in_doaj": kwargs.get("is_in_doaj", False),
            "oa_model": kwargs.get("oa_model"),
        },
    ).scalar_one()
    issn, eissn, issnl = kwargs.get("issn"), kwargs.get("eissn"), kwargs.get("issnl")
    if issn:
        _add_issn(conn, journal_id, issn, support="print", linking=issn == issnl)
    if eissn and eissn != issn:
        _add_issn(conn, journal_id, eissn, support="electronic", linking=eissn == issnl)
    if issnl and issnl not in (issn, eissn):
        _add_issn(conn, journal_id, issnl, linking=True)
    for value in kwargs.get("rejected", ()):
        _add_issn(conn, journal_id, value, status=kwargs.get("rejected_status", "unverified"))
    return journal_id


def _insert_publication(conn, title="Pub", pub_year=2024, journal_id=None):
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, journal_id) "
            "VALUES (:title, :year, :j_id) RETURNING id"
        ),
        {"title": title, "year": pub_year, "j_id": journal_id},
    ).scalar_one()


# ── find_by_id (hydratation aggregates) ────────────────────────────


class TestPublisherFindById:
    def test_returns_none_if_missing(self, publisher_repo):
        assert publisher_repo.find_by_id(999999) is None

    def test_hydrates(self, sa_sync_conn, publisher_repo):
        pub_id = _insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P123")
        p = publisher_repo.find_by_id(pub_id)
        assert p is not None
        assert p.id == pub_id
        assert p.name == "Elsevier"
        assert p.openalex_id == "P123"


class TestJournalFindById:
    def test_returns_none_if_missing(self, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal(self, sa_sync_conn, repo):
        jid = _insert_journal(sa_sync_conn, "Nature")
        j = repo.find_by_id(jid)
        assert j is not None
        assert j.id == jid
        assert j.title == "Nature"
        assert j.publisher_id is None
        assert j.apc_currency is None
        assert j.is_in_doaj is False

    def test_hydrates_full(self, sa_sync_conn, repo):
        pub_id = _insert_publisher(sa_sync_conn, "PLOS")
        jid = _insert_journal(
            sa_sync_conn,
            title="PLOS ONE",
            publisher_id=pub_id,
            issn="1932-6203",
            eissn="1932-6203",
            issnl="1932-6203",
            openalex_id="S202381698",
            apc_amount=1700,
            apc_currency="USD",
            is_in_doaj=True,
            oa_model="full_oa",
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


# ── find_or_create_publisher ───────────────────────────────────────


class TestFindOrCreatePublisher:
    def test_returns_none_on_empty_name(self, sa_sync_conn, publisher_gateway):
        assert find_or_create_publisher(None, repo=publisher_gateway) is None
        assert find_or_create_publisher("", repo=publisher_gateway) is None

    def test_creates_new_publisher(self, sa_sync_conn, publisher_gateway):
        pub_id = find_or_create_publisher("Elsevier", repo=publisher_gateway)
        assert pub_id is not None
        row = _fetch_one(sa_sync_conn, "SELECT name FROM publishers WHERE id = :id", id=pub_id)
        assert row.name == "Elsevier"

    def test_finds_existing_by_openalex_id(self, sa_sync_conn, publisher_gateway):
        existing = _insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P4310310871")
        found = find_or_create_publisher(
            "Elsevier BV", openalex_id="P4310310871", repo=publisher_gateway
        )
        assert found == existing

    def test_un_nom_encode_rejoint_le_meme_editeur_que_le_nom_en_clair(
        self, sa_sync_conn, publisher_gateway
    ):
        """Régression : même cause et même correction que pour les revues (cf. `TestFindOrCreateJournal`)."""
        premier = find_or_create_publisher("Taylor & Francis", repo=publisher_gateway)
        second = find_or_create_publisher("TAYLOR &amp; FRANCIS", repo=publisher_gateway)
        assert second == premier

    def test_finds_existing_by_name_form(self, sa_sync_conn, publisher_gateway):
        existing = find_or_create_publisher("Elsevier", repo=publisher_gateway)
        found = find_or_create_publisher("elsevier", repo=publisher_gateway)
        assert found == existing

    def test_variantes_de_nom_rejoignent_le_meme_editeur(self, sa_sync_conn, publisher_gateway):
        """Cas réels : formes juridiques, dates et « on behalf of » ajoutés par les sources."""
        elsevier = find_or_create_publisher("Elsevier BV", repo=publisher_gateway)
        for variant in (
            "Elsevier [1977-....]",
            "Elsevier Ltd.",
            "Elsevier on behalf of the American College of Cardiology Foundation",
        ):
            assert find_or_create_publisher(variant, repo=publisher_gateway) == elsevier
        row = _fetch_one(sa_sync_conn, "SELECT name FROM publishers WHERE id = :id", id=elsevier)
        assert row.name == "Elsevier BV"

    def test_attaches_openalex_id_if_missing(self, sa_sync_conn, publisher_gateway):
        existing = find_or_create_publisher("Elsevier", repo=publisher_gateway)
        find_or_create_publisher("Elsevier", openalex_id="P123", repo=publisher_gateway)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=existing
        )
        assert row.openalex_id == "P123"


# ── find_or_create_journal ─────────────────────────────────────────


class TestFindOrCreateJournal:
    def test_returns_none_on_empty_title(self, sa_sync_conn, gateway):
        assert find_or_create_journal(None, repo=gateway) is None
        assert find_or_create_journal("", repo=gateway) is None

    def test_creates_new_journal(self, sa_sync_conn, gateway):
        j_id = find_or_create_journal("Nature", issn="0028-0836", repo=gateway)
        row = _fetch_one(sa_sync_conn, "SELECT title FROM journals WHERE id = :id", id=j_id)
        row = SimpleNamespace(title=row.title, issn=_columns(sa_sync_conn, j_id).issn)
        assert row.title == "Nature"
        assert row.issn == "0028-0836"

    def test_un_titre_encode_rejoint_le_meme_journal_que_le_titre_en_clair(
        self, sa_sync_conn, gateway
    ):
        """Régression : le titre affiché et la clé de rapprochement dérivent de la même valeur.

        Les sources livrent le même titre tantôt en clair, tantôt avec des entités HTML. Tant
        que la clé se calculait sur le titre reçu et le titre affiché sur sa mise à plat, les
        deux formes portaient des clés distinctes (`... amp ...`) et la revue naissait en deux
        exemplaires — quatre cas relevés en base.
        """
        premier = find_or_create_journal("Wood & Fire Safety", repo=gateway)
        second = find_or_create_journal("Wood &amp; Fire Safety", repo=gateway)
        assert second == premier
        row = _fetch_one(
            sa_sync_conn,
            "SELECT title, title_normalized FROM journals WHERE id = :id",
            id=premier,
        )
        assert row.title == "Wood & Fire Safety"
        assert "amp" not in row.title_normalized

    def test_finds_by_openalex_id(self, sa_sync_conn, gateway):
        existing = _insert_journal(sa_sync_conn, "Nature", openalex_id="S137773608")
        found = find_or_create_journal("Nature Journal", openalex_id="S137773608", repo=gateway)
        assert found == existing

    def test_finds_by_issn(self, sa_sync_conn, gateway):
        existing = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        found = find_or_create_journal("Nature Variant", issn="0028-0836", repo=gateway)
        assert found == existing

    def test_finds_by_eissn(self, sa_sync_conn, gateway):
        existing = _insert_journal(sa_sync_conn, "Nature", eissn="1476-4687")
        found = find_or_create_journal("Nature", eissn="1476-4687", repo=gateway)
        assert found == existing

    def test_finds_by_issnl(self, sa_sync_conn, gateway):
        existing = _insert_journal(sa_sync_conn, "Nature", issnl="0028-0836")
        found = find_or_create_journal("Other Title", issnl="0028-0836", repo=gateway)
        assert found == existing

    def test_finds_by_name_form(self, sa_sync_conn, gateway):
        find_or_create_journal("Nature", repo=gateway)
        found = find_or_create_journal("nature", repo=gateway)
        n = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS n FROM journals WHERE title_normalized = 'nature'")
        ).scalar_one()
        assert n == 1
        assert found is not None

    def test_enriches_metadata_on_match(self, sa_sync_conn, gateway, publisher_gateway):
        """Si on trouve par ISSN, les champs vides (eissn, publisher_id) sont remplis."""
        existing = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        pub_id = find_or_create_publisher("Springer", repo=publisher_gateway)
        find_or_create_journal(
            "Nature",
            issn="0028-0836",
            eissn="1476-4687",
            publisher_id=pub_id,
            repo=gateway,
        )
        row = _columns(sa_sync_conn, existing)
        row.publisher_id = _fetch_one(
            sa_sync_conn, "SELECT publisher_id FROM journals WHERE id = :id", id=existing
        ).publisher_id
        assert row.eissn == "1476-4687"
        assert row.publisher_id == pub_id

    def test_normalizes_issn_on_create(self, sa_sync_conn, gateway):
        j_id = find_or_create_journal("Nature", issn="00280836", eissn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_finds_by_issn_under_another_form(self, sa_sync_conn, gateway):
        existing = find_or_create_journal("Nature", issn="0028-0836", repo=gateway)
        found = find_or_create_journal("Nature Variant", issn="ISSN 00280836", repo=gateway)
        assert found == existing

    def test_titles_emptied_by_normalization_do_not_match(self, sa_sync_conn, gateway):
        """Cas réel : un titre grec et un titre cyrillique se normalisent tous deux en chaîne vide."""
        greek = find_or_create_journal("Παιδαγωγικά ρεύματα στο Αιγαίο", repo=gateway)
        cyrillic = find_or_create_journal("Теория вероятностей и ее применения", repo=gateway)
        assert greek != cyrillic

    def test_invalid_issn_is_kept_aside_and_logged(self, sa_sync_conn, gateway, caplog):
        j_id = find_or_create_journal("Nature", issn="(Internet)", eissn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn is None
        assert row.eissn == "1476-4687"
        assert row.rejected_issns == ["(Internet)"]
        assert "ISSN mal formé (revue 'Nature') : issn = '(Internet)'" in caplog.text

    def test_rejected_issns_accumulate_without_duplicates(self, sa_sync_conn, gateway):
        """Les ISSN invalides s'ajoutent à ceux de la revue trouvée, sans doublon."""
        j_id = find_or_create_journal("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        find_or_create_journal("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        find_or_create_journal("Nature", issn="0028-0836", issnl="1234-5678", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.rejected_issns == ["1234-5678", "1476-4688"]

    def test_known_issn_is_not_copied_into_a_free_column(self, sa_sync_conn, gateway):
        """Une source qui donne comme ISSN papier l'ISSN électronique d'une revue vérifiée ne défait pas son rangement."""
        j_id = _insert_journal(sa_sync_conn, "Nature", eissn="1476-4687")
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        find_or_create_journal("Nature", issn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn is None
        assert row.eissn == "1476-4687"
        assert row.sudoc_checked_at is not None

    def test_issnl_value_can_fill_the_issn_column(self, sa_sync_conn, gateway):
        """Régression : l'ISSN-L est l'ISSN de l'un des supports, il peut donc aussi figurer dans `issn`."""
        j_id = _insert_journal(sa_sync_conn, "Nature", issnl="0028-0836")
        find_or_create_journal("Nature", issn="0028-0836", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert (row.issn, row.issnl) == ("0028-0836", "0028-0836")

    def test_rejected_issn_is_not_copied_into_a_column(self, sa_sync_conn, gateway):
        """Un ISSN rejeté (ici un CD-ROM) retrouve la revue sans revenir dans une colonne."""
        j_id = _insert_journal(sa_sync_conn, "Nature", issn="0305-1048", rejected=("1362-4954",))
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        found = find_or_create_journal("Other title", eissn="1362-4954", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert found == j_id
        assert row.eissn is None
        assert row.sudoc_checked_at is not None

    def test_new_issn_makes_the_journal_to_check_again(self, sa_sync_conn, gateway):
        j_id = _insert_journal(sa_sync_conn, "Nature", eissn="1476-4687")
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        find_or_create_journal("Nature", issn="0028-0836", eissn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn == "0028-0836"
        assert row.sudoc_checked_at is None

    def test_new_rejected_issn_makes_the_journal_to_check_again(self, sa_sync_conn, gateway):
        j_id = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        find_or_create_journal("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.rejected_issns == ["1476-4688"]
        assert row.sudoc_checked_at is None


# ── update_journal_apc ─────────────────────────────────────────────


class TestUpdateJournalApc:
    def test_updates_fields(self, sa_sync_conn, gateway):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        update_journal_apc(j_id, apc_amount=3000.0, apc_currency="EUR", repo=gateway)
        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency FROM journals WHERE id = :id",
            id=j_id,
        )
        assert float(row.apc_amount) == 3000.0
        assert row.apc_currency == "EUR"

    def test_coalesce_preserves_existing_and_leaves_is_in_doaj(self, sa_sync_conn, gateway):
        """Sans nouvelle valeur, l'APC existant est conservé ; `is_in_doaj` (autorité
        DOAJ) n'est jamais touché par l'enrichissement APC."""
        j_id = _insert_journal(
            sa_sync_conn, "Nature", apc_amount=2000.0, apc_currency="USD", is_in_doaj=True
        )
        update_journal_apc(j_id, apc_currency="EUR", repo=gateway)
        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency, is_in_doaj FROM journals WHERE id = :id",
            id=j_id,
        )
        assert float(row.apc_amount) == 2000.0
        assert row.apc_currency == "EUR"
        assert row.is_in_doaj is True


class TestUpdateJournal:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_journal(999999, update=JournalUpdate(title="X"), repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ValidationError):
            update_journal(j, update=JournalUpdate(), repo=repo)

    def test_updates_title_and_normalizes(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Old Title")
        update_journal(j, update=JournalUpdate(title="Nature Medicine"), repo=repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT title, title_normalized FROM journals WHERE id = :id", id=j
        )
        assert row.title == "Nature Medicine"
        assert row.title_normalized == "nature medicine"

    def test_partial_update(self, sa_sync_conn, repo):
        """Les ISSN fournis remplacent ceux de la revue ; un ISSN gardé conserve sa date de vérification."""
        j = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        _mark_checked_in_sudoc(sa_sync_conn, j)
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
        row = _columns(sa_sync_conn, j)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_normalizes_issn(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Nature")
        update_journal(
            j,
            update=JournalUpdate(
                issns=[JournalIssnInput(issn="14764687", support=IssnSupport.ELECTRONIC)]
            ),
            repo=repo,
        )
        row = _columns(sa_sync_conn, j)
        assert row.eissn == "1476-4687"

    def test_rejects_invalid_issn(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        with pytest.raises(ValidationError):
            update_journal(
                j, update=JournalUpdate(issns=[JournalIssnInput(issn="1234-5678")]), repo=repo
            )
        row = _columns(sa_sync_conn, j)
        assert row.issn == "0028-0836"


class TestUpdatePublisher:
    def test_raises_not_found(self, sa_sync_conn, publisher_repo):
        with pytest.raises(NotFoundError):
            update_publisher(999999, update=PublisherUpdate(name="X"), repo=publisher_repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, publisher_repo):
        p = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError):
            update_publisher(p, update=PublisherUpdate(), repo=publisher_repo)

    def test_updates_name_and_normalizes(self, sa_sync_conn, publisher_repo):
        p = _insert_publisher(sa_sync_conn, "Old Name")
        update_publisher(p, update=PublisherUpdate(name="Springer Nature"), repo=publisher_repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT name, name_normalized FROM publishers WHERE id = :id", id=p
        )
        assert row.name == "Springer Nature"
        assert row.name_normalized == "springer nature"


# ── merge_publishers ───────────────────────────────────────────────


class TestMergePublishers:
    def test_raises_on_self_merge(self, sa_sync_conn, repo, publisher_repo, publication_repo):
        p_id = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError, match="identiques"):
            merge_publishers(
                p_id,
                p_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                publication_repo=publication_repo,
            )

    def test_raises_on_missing_target(self, sa_sync_conn, repo, publisher_repo, publication_repo):
        p_id = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_publishers(
                999999,
                p_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                publication_repo=publication_repo,
            )

    def test_raises_on_missing_source(self, sa_sync_conn, repo, publisher_repo, publication_repo):
        p_id = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_publishers(
                p_id,
                999999,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                publication_repo=publication_repo,
            )

    def test_transfers_journals_and_deletes_source(
        self, sa_sync_conn, repo, publisher_repo, publication_repo
    ):
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        j1 = _insert_journal(sa_sync_conn, "Journal 1", publisher_id=source)

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            publication_repo=publication_repo,
        )

        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM publishers WHERE id = :id", id=source)
        ) is None
        row = _fetch_one(sa_sync_conn, "SELECT publisher_id FROM journals WHERE id = :id", id=j1)
        assert row.publisher_id == target

    def test_transfers_monographs(self, sa_sync_conn, repo, publisher_repo, publication_repo):
        """La monographie garde un éditeur, qui la retrouve par son titre."""
        target = _insert_publisher(sa_sync_conn, "Presses universitaires de Rennes")
        source = _insert_publisher(sa_sync_conn, "PUR")
        monograph = sa_sync_conn.execute(
            text(
                "INSERT INTO monographs (title, title_normalized, publisher_id)"
                " VALUES ('Livre', 'livre', :s) RETURNING id"
            ),
            {"s": source},
        ).scalar_one()

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            publication_repo=publication_repo,
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT publisher_id FROM monographs WHERE id = :id", id=monograph
        )
        assert row.publisher_id == target

    def test_transfers_doi_prefixes(self, sa_sync_conn, repo, publisher_repo, publication_repo):
        """Régression : le préfixe DOI de l'éditeur absorbé perdait son éditeur, sans être résolu de nouveau."""
        target = _insert_publisher(sa_sync_conn, "Elsevier BV")
        source = _insert_publisher(sa_sync_conn, "Elsevier [1977-....]")
        sa_sync_conn.execute(
            text(
                "INSERT INTO doi_prefixes (prefix, ra, publisher_id, publisher_checked_at)"
                " VALUES ('10.99999', 'Crossref', :s, now())"
            ),
            {"s": source},
        )

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            publication_repo=publication_repo,
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT publisher_id FROM doi_prefixes WHERE prefix = '10.99999'"
        )
        assert row.publisher_id == target

    def test_merges_same_title_journals(self, sa_sync_conn, repo, publisher_repo, publication_repo):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        jt = _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        js = _insert_journal(sa_sync_conn, "Nature", publisher_id=source, eissn="1476-4687")
        _insert_publication(sa_sync_conn, journal_id=js)

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            publication_repo=publication_repo,
        )

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        row = _columns(sa_sync_conn, jt)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_merges_same_title_journals_with_only_source_openalex_id(
        self, sa_sync_conn, repo, publisher_repo, publication_repo
    ):
        """Cible sans openalex_id, source avec : la fusion doit déplacer
        l'openalex_id du source vers la cible sans violer UNIQUE(openalex_id)."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        jt = _insert_journal(sa_sync_conn, "Nature", publisher_id=target)
        js = _insert_journal(sa_sync_conn, "Nature", publisher_id=source, openalex_id="S4210225546")

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            publication_repo=publication_repo,
        )

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        row = _fetch_one(sa_sync_conn, "SELECT openalex_id FROM journals WHERE id = :id", id=jt)
        assert row.openalex_id == "S4210225546"

    def test_raises_blocked_error_on_issn_conflict(
        self, sa_sync_conn, repo, publisher_repo, publication_repo
    ):
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        jt = _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        js = _insert_journal(sa_sync_conn, "Nature", publisher_id=source, issn="9999-9999")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                publication_repo=publication_repo,
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
        self, sa_sync_conn, repo, publisher_repo, publication_repo
    ):
        """Si la cible a 2 journaux au même titre et la source en a 1, la fusion
        N→1 casserait. On flagge ces paires comme blockers."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=target, eissn="1476-4687")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=source)

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                publication_repo=publication_repo,
            )

        blockers = exc_info.value.blocking_journals
        assert len(blockers) == 2
        for b in blockers:
            assert "doublon interne" in b["reason"]

    def test_collects_all_blockers_in_one_pass(
        self, sa_sync_conn, repo, publisher_repo, publication_repo
    ):
        """Plusieurs paires de revues bloquantes → toutes remontées d'un coup."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        _insert_journal(sa_sync_conn, "Rev1", publisher_id=target, issn="1111-1111")
        _insert_journal(sa_sync_conn, "Rev1", publisher_id=source, issn="2222-2222")
        _insert_journal(sa_sync_conn, "Rev2", publisher_id=target, eissn="3333-3333")
        _insert_journal(sa_sync_conn, "Rev2", publisher_id=source, eissn="4444-4444")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=publisher_repo,
                journal_repo=repo,
                publication_repo=publication_repo,
            )

        assert len(exc_info.value.blocking_journals) == 2

    def test_transfers_openalex_id_when_target_has_none(
        self, sa_sync_conn, repo, publisher_repo, publication_repo
    ):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = _insert_publisher(sa_sync_conn, "Target", openalex_id=None)
        source = _insert_publisher(sa_sync_conn, "Source", openalex_id="P999")
        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            publication_repo=publication_repo,
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P999"

    def test_keeps_target_openalex_id_when_both_set(
        self, sa_sync_conn, repo, publisher_repo, publication_repo
    ):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = _insert_publisher(sa_sync_conn, "Target", openalex_id="P_TARGET")
        source = _insert_publisher(sa_sync_conn, "Source", openalex_id="P_SOURCE")
        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=publisher_repo,
            journal_repo=repo,
            publication_repo=publication_repo,
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P_TARGET"


# ── merge_journals ─────────────────────────────────────────────────


class TestMergeJournals:
    def test_raises_on_self_merge(self, sa_sync_conn, repo, publication_repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ValidationError, match="identiques"):
            merge_journals(
                j_id,
                j_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                repo=repo,
                publication_repo=publication_repo,
            )

    def test_raises_on_missing_target(self, sa_sync_conn, repo, publication_repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_journals(
                999999,
                j_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                repo=repo,
                publication_repo=publication_repo,
            )

    def test_raises_on_missing_source(self, sa_sync_conn, repo, publication_repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(NotFoundError, match="introuvable"):
            merge_journals(
                j_id,
                999999,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                repo=repo,
                publication_repo=publication_repo,
            )

    def test_transfers_publications(self, sa_sync_conn, repo, publication_repo):
        target = _insert_journal(sa_sync_conn, "Target")
        source = _insert_journal(sa_sync_conn, "Source")
        pub_id = _insert_publication(sa_sync_conn, journal_id=source)
        # ≥1 source_publication : sinon `refresh_from_sources` (déclenché par la
        # requalification post-merge) supprimerait la publication comme orpheline.
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications "
                "(source, source_id, title, pub_year, journal_id, publication_id) "
                "VALUES ('openalex', 'W-transfer', 'T', 2024, :jid, :pid)"
            ),
            {"jid": source, "pid": pub_id},
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT journal_id FROM publications WHERE id = :id", id=pub_id
        )
        assert row.journal_id == target
        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=source)
        ) is None

    def test_unites_malformed_issns_and_resets_sudoc_check(
        self, sa_sync_conn, repo, publication_repo
    ):
        """La cible reçoit les valeurs mal formées de la source et redevient à vérifier dans le Sudoc."""
        target = _insert_journal(
            sa_sync_conn, "Target", rejected=("1234-5678",), rejected_status="malformed"
        )
        _mark_checked_in_sudoc(sa_sync_conn, target)
        source = _insert_journal(
            sa_sync_conn,
            "Source",
            rejected=("1234-5678", "(Internet)"),
            rejected_status="malformed",
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
        )

        row = _columns(sa_sync_conn, target)
        assert row.rejected_issns == ["(Internet)", "1234-5678"]
        assert row.sudoc_checked_at is None

    def test_source_issns_join_the_target(self, sa_sync_conn, repo, publication_repo):
        """Titre précédent absorbé par le titre suivant : l'ISSN du titre précédent rejoint la cible, qui garde son propre ISSN."""
        target = _insert_journal(sa_sync_conn, "BMC Primary Care", eissn="2731-4553")
        source = _insert_journal(
            sa_sync_conn,
            "BMC Family Practice",
            eissn="1471-2296",
            rejected=("2731-4553",),
            rejected_status="related_title",
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
        )

        row = _columns(sa_sync_conn, target)
        assert row.eissn == "2731-4553"
        assert row.rejected_issns == ["1471-2296"]

    def test_enriches_target_metadata(self, sa_sync_conn, repo, publication_repo):
        target = _insert_journal(sa_sync_conn, "Target")
        source = _insert_journal(
            sa_sync_conn, "Source", issn="1234-5678", eissn="9999-0000", is_in_doaj=True
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
        )

        row = _columns(sa_sync_conn, target)
        row.is_in_doaj = _fetch_one(
            sa_sync_conn, "SELECT is_in_doaj FROM journals WHERE id = :id", id=target
        ).is_in_doaj
        assert row.issn == "1234-5678"
        assert row.eissn == "9999-0000"
        assert row.is_in_doaj is True

    def test_does_not_overwrite_existing_fields(self, sa_sync_conn, repo, publication_repo):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = _insert_journal(sa_sync_conn, "Target", issn="0028-0836")
        source = _insert_journal(sa_sync_conn, "Source", issn="1234-5678")

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
        )

        row = _columns(sa_sync_conn, target)
        assert row.issn == "0028-0836"

    def test_requalifies_absorbed_publications_against_target_type(
        self, sa_sync_conn, repo, publication_repo
    ):
        """Fusionner une revue dans un média retype ses publications en `media`.

        Régression : avant ce hook, le merge repointait `journal_id` mais laissait
        les `doc_type` des publications absorbées inchangés.
        """
        media = _insert_journal(sa_sync_conn, "Le Monde")
        revue = _insert_journal(sa_sync_conn, "Revue X")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": media}
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": revue}
        )
        pub = _insert_publication(sa_sync_conn, journal_id=revue)
        sa_sync_conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": pub}
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications "
                "(source, source_id, title, pub_year, doc_type, journal_id, publication_id) "
                "VALUES ('openalex', 'W-merge-requalif', 'T', 2024, 'article', :jid, :pid)"
            ),
            {"jid": revue, "pid": pub},
        )

        merge_journals(
            media,
            revue,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
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
        journal = _insert_journal(conn, "Revue X")
        conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": journal}
        )
        pub = _insert_publication(conn, journal_id=journal)
        conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": pub}
        )
        sp = conn.execute(
            text(
                "INSERT INTO source_publications "
                "(source, source_id, title, pub_year, doc_type, journal_id, publication_id) "
                "VALUES ('openalex', 'W-requalif', 'T', 2024, 'article', :jid, :pid) RETURNING id"
            ),
            {"jid": journal, "pid": pub},
        ).scalar_one()
        return journal, pub, sp

    def test_persists_sp_correction_and_retypes_publication(self, sa_sync_conn, publication_repo):
        journal, pub, sp = self._seed(sa_sync_conn)
        # Le caller a déjà basculé le type (comme update_journal).
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": journal}
        )

        count = requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publication_repo=publication_repo,
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

    def test_self_heals_when_type_reverts(self, sa_sync_conn, publication_repo):
        journal, pub, sp = self._seed(sa_sync_conn)
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": journal}
        )
        requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publication_repo=publication_repo,
        )

        # Le type revient à 'journal' : la correction doit être défaite, le brut restauré.
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": journal}
        )
        count = requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publication_repo=publication_repo,
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
