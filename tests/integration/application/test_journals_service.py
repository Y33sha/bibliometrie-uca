"""Tests de caractérisation pour application/journals/core.py et
application/publishers/core.py.

Couvre les fonctions sync (find_or_create_*, update_journal_apc — utilisées
par le pipeline) et les fonctions async (update_journal, update_publisher,
merge_*).
"""

from functools import partial
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
from domain.journals.issns import IssnSupport, JournalIssn, source_issns
from infrastructure.pipeline.journals import PgJournalGatewayQueries
from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)
from tests.integration.helpers.journals import (
    insert_journal_with_issns,
    insert_monograph,
    insert_publisher,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_publication

# Revue « Nature » par défaut, sans devise d'APC.
_journal = partial(insert_journal_with_issns, title="Nature", apc_currency=None)

# Stateless (connexion passée aux méthodes) → une instance module suffit.
_CORRECTION_QUERIES = PgMetadataCorrectionQueries()

# Notice OpenAlex de 2024, de titre « T ».
_openalex_notice = partial(insert_source_publication, source="openalex", title="T", pub_year=2024)


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


def _find_or_create(title, *, issn=None, eissn=None, issnl=None, **kwargs):
    """`find_or_create_journal` avec un ISSN papier, un ISSN en ligne et un ISSN-L."""
    issns = source_issns(print_issn=issn, electronic_issn=eissn, linking=issnl)
    return find_or_create_journal(title, issns=issns, **kwargs)


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
        existing = insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P4310310871")
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
        assert _find_or_create(None, repo=gateway) is None
        assert _find_or_create("", repo=gateway) is None

    def test_creates_new_journal(self, sa_sync_conn, gateway):
        j_id = _find_or_create("Nature", issn="0028-0836", repo=gateway)
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
        premier = _find_or_create("Wood & Fire Safety", repo=gateway)
        second = _find_or_create("Wood &amp; Fire Safety", repo=gateway)
        assert second == premier
        row = _fetch_one(
            sa_sync_conn,
            "SELECT title, title_normalized FROM journals WHERE id = :id",
            id=premier,
        )
        assert row.title == "Wood & Fire Safety"
        assert "amp" not in row.title_normalized

    def test_finds_by_openalex_id(self, sa_sync_conn, gateway):
        existing = _journal(sa_sync_conn, openalex_id="S137773608")
        found = _find_or_create("Nature Journal", openalex_id="S137773608", repo=gateway)
        assert found == existing

    def test_finds_by_issn(self, sa_sync_conn, gateway):
        existing = _journal(sa_sync_conn, issn="0028-0836")
        found = _find_or_create("Nature Variant", issn="0028-0836", repo=gateway)
        assert found == existing

    def test_finds_by_eissn(self, sa_sync_conn, gateway):
        existing = _journal(sa_sync_conn, eissn="1476-4687")
        found = _find_or_create("Nature", eissn="1476-4687", repo=gateway)
        assert found == existing

    def test_finds_by_issnl(self, sa_sync_conn, gateway):
        existing = _journal(sa_sync_conn, issnl="0028-0836")
        found = _find_or_create("Other Title", issnl="0028-0836", repo=gateway)
        assert found == existing

    def test_finds_by_name_form(self, sa_sync_conn, gateway):
        _find_or_create("Nature", repo=gateway)
        found = _find_or_create("nature", repo=gateway)
        n = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS n FROM journals WHERE title_normalized = 'nature'")
        ).scalar_one()
        assert n == 1
        assert found is not None

    def test_enriches_metadata_on_match(self, sa_sync_conn, gateway, publisher_gateway):
        """Si on trouve par ISSN, les champs vides (eissn, publisher_id) sont remplis."""
        existing = _journal(sa_sync_conn, issn="0028-0836")
        pub_id = find_or_create_publisher("Springer", repo=publisher_gateway)
        _find_or_create(
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
        j_id = _find_or_create("Nature", issn="00280836", eissn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_finds_by_issn_under_another_form(self, sa_sync_conn, gateway):
        existing = _find_or_create("Nature", issn="0028-0836", repo=gateway)
        found = _find_or_create("Nature Variant", issn="ISSN 00280836", repo=gateway)
        assert found == existing

    def test_titles_emptied_by_normalization_do_not_match(self, sa_sync_conn, gateway):
        """Cas réel : un titre grec et un titre cyrillique se normalisent tous deux en chaîne vide."""
        greek = _find_or_create("Παιδαγωγικά ρεύματα στο Αιγαίο", repo=gateway)
        cyrillic = _find_or_create("Теория вероятностей и ее применения", repo=gateway)
        assert greek != cyrillic

    def test_invalid_issn_is_kept_aside_and_logged(self, sa_sync_conn, gateway, caplog):
        j_id = _find_or_create("Nature", issn="(Internet)", eissn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn is None
        assert row.eissn == "1476-4687"
        assert row.rejected_issns == ["(Internet)"]
        assert "ISSN mal formé (revue 'Nature') : '(Internet)'" in caplog.text

    def test_rejected_issns_accumulate_without_duplicates(self, sa_sync_conn, gateway):
        """Les ISSN invalides s'ajoutent à ceux de la revue trouvée, sans doublon."""
        j_id = _find_or_create("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        _find_or_create("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        _find_or_create("Nature", issn="0028-0836", issnl="1234-5678", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.rejected_issns == ["1234-5678", "1476-4688"]

    def test_known_issn_is_not_copied_into_a_free_column(self, sa_sync_conn, gateway):
        """Une source qui donne comme ISSN papier l'ISSN électronique d'une revue vérifiée ne défait pas son rangement."""
        j_id = _journal(sa_sync_conn, eissn="1476-4687")
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        _find_or_create("Nature", issn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn is None
        assert row.eissn == "1476-4687"
        assert row.sudoc_checked_at is not None

    def test_issnl_value_can_fill_the_issn_column(self, sa_sync_conn, gateway):
        """Régression : l'ISSN-L est l'ISSN de l'un des supports, il peut donc aussi figurer dans `issn`."""
        j_id = _journal(sa_sync_conn, issnl="0028-0836")
        _find_or_create("Nature", issn="0028-0836", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert (row.issn, row.issnl) == ("0028-0836", "0028-0836")

    def test_rejected_issn_is_not_copied_into_a_column(self, sa_sync_conn, gateway):
        """Un ISSN rejeté (ici un CD-ROM) retrouve la revue sans revenir dans une colonne."""
        j_id = _journal(sa_sync_conn, issn="0305-1048", rejected=("1362-4954",))
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        found = _find_or_create("Other title", eissn="1362-4954", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert found == j_id
        assert row.eissn is None
        assert row.sudoc_checked_at is not None

    def test_new_issn_makes_the_journal_to_check_again(self, sa_sync_conn, gateway):
        j_id = _journal(sa_sync_conn, eissn="1476-4687")
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        _find_or_create("Nature", issn="0028-0836", eissn="1476-4687", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.issn == "0028-0836"
        assert row.sudoc_checked_at is None

    def test_new_rejected_issn_makes_the_journal_to_check_again(self, sa_sync_conn, gateway):
        j_id = _journal(sa_sync_conn, issn="0028-0836")
        _mark_checked_in_sudoc(sa_sync_conn, j_id)
        _find_or_create("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        row = _columns(sa_sync_conn, j_id)
        assert row.rejected_issns == ["1476-4688"]
        assert row.sudoc_checked_at is None


# ── update_journal_apc ─────────────────────────────────────────────


class TestUpdateJournalApc:
    def test_updates_fields(self, sa_sync_conn, gateway):
        j_id = _journal(sa_sync_conn)
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
        j_id = _journal(sa_sync_conn, is_in_doaj=True, apc_amount=2000.0, apc_currency="USD")
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
        j = _journal(sa_sync_conn)
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
        j = _journal(sa_sync_conn, issn="0028-0836")
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
    def test_raises_on_self_merge(self, sa_sync_conn, repo, publisher_repo, publication_repo):
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
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
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
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
        p_id = insert_publisher(sa_sync_conn, "Elsevier")
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
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        j1 = _journal(sa_sync_conn, title="Journal 1", publisher_id=source)

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
        target = insert_publisher(sa_sync_conn, "Presses universitaires de Rennes")
        source = insert_publisher(sa_sync_conn, "PUR")
        monograph = insert_monograph(sa_sync_conn, "Livre", publisher_id=source)

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
        target = insert_publisher(sa_sync_conn, "Elsevier BV")
        source = insert_publisher(sa_sync_conn, "Elsevier [1977-....]")
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
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _journal(sa_sync_conn, publisher_id=target, issn="0028-0836")
        js = _journal(sa_sync_conn, publisher_id=source, eissn="1476-4687")
        insert_publication(sa_sync_conn, journal_id=js)

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
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _journal(sa_sync_conn, publisher_id=target)
        js = _journal(sa_sync_conn, publisher_id=source, openalex_id="S4210225546")

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
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source")
        jt = _journal(sa_sync_conn, publisher_id=target, issn="0028-0836")
        js = _journal(sa_sync_conn, publisher_id=source, issn="9999-9999")

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
        target = insert_publisher(sa_sync_conn, "Target")
        source = insert_publisher(sa_sync_conn, "Source", openalex_id="P999")
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
        target = insert_publisher(sa_sync_conn, "Target", openalex_id="P_TARGET")
        source = insert_publisher(sa_sync_conn, "Source", openalex_id="P_SOURCE")
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
        j_id = _journal(sa_sync_conn)
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
        j_id = _journal(sa_sync_conn)
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
        j_id = _journal(sa_sync_conn)
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
        target = _journal(
            sa_sync_conn, title="Target", rejected=("1234-5678",), rejected_status="malformed"
        )
        _mark_checked_in_sudoc(sa_sync_conn, target)
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
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
        )

        row = _columns(sa_sync_conn, target)
        assert row.rejected_issns == ["(Internet)", "1234-5678"]
        assert row.sudoc_checked_at is None

    def test_source_issns_join_the_target(self, sa_sync_conn, repo, publication_repo):
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
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            publication_repo=publication_repo,
        )

        row = _columns(sa_sync_conn, target)
        assert row.eissn == "2731-4553"
        assert row.rejected_issns == ["1471-2296"]

    def test_enriches_target_metadata(self, sa_sync_conn, repo, publication_repo):
        target = _journal(sa_sync_conn, title="Target")
        source = _journal(
            sa_sync_conn, title="Source", is_in_doaj=True, issn="1234-5678", eissn="9999-0000"
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
        target = _journal(sa_sync_conn, title="Target", issn="0028-0836")
        source = _journal(sa_sync_conn, title="Source", issn="1234-5678")

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
