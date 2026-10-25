"""Tests d'intégration du « trouver ou créer » des éditeurs et des revues (`pipeline/transformation/publishing/find_or_create.py`)."""

from functools import partial
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from domain.serials.issns import source_issns
from pipeline.transformation.publishing.find_or_create import (
    find_or_create_publisher,
    find_or_create_serial,
)
from pipeline.transformation.publishing.publishers.store import PublisherStore
from pipeline.transformation.publishing.serials.enrich_serials_from_openalex import (
    update_serial_apc,
)
from pipeline.transformation.publishing.serials.store import SerialStore
from tests.integration.helpers.serials import (
    insert_publisher,
    insert_serial_with_issns,
    issn_columns,
    mark_checked_in_sudoc,
)

# Revue « Nature » par défaut, sans devise d'APC.
_serial = partial(insert_serial_with_issns, title="Nature", apc_currency=None)


@pytest.fixture
def gateway(sa_sync_conn):
    return SerialStore(sa_sync_conn)


@pytest.fixture
def publisher_store(sa_sync_conn):
    return PublisherStore(sa_sync_conn)


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un SELECT et retourne sa première ligne, ou `None`."""
    return conn.execute(text(sql_text), params).first()


def _find_or_create(title, *, issn=None, eissn=None, issnl=None, **kwargs):
    """`find_or_create_serial` avec un ISSN papier, un ISSN en ligne et un ISSN-L."""
    issns = source_issns(print_issn=issn, electronic_issn=eissn, linking=issnl)
    return find_or_create_serial(title, issns=issns, **kwargs)


# ── find_or_create_publisher ───────────────────────────────────────


class TestFindOrCreatePublisher:
    def test_returns_none_on_empty_name(self, sa_sync_conn, publisher_store):
        assert find_or_create_publisher(None, repo=publisher_store) is None
        assert find_or_create_publisher("", repo=publisher_store) is None

    def test_creates_new_publisher(self, sa_sync_conn, publisher_store):
        publisher_id = find_or_create_publisher("Elsevier", repo=publisher_store)
        assert publisher_id is not None
        row = _fetch_one(
            sa_sync_conn, "SELECT name FROM publishers WHERE id = :id", id=publisher_id
        )
        assert row.name == "Elsevier"

    def test_finds_existing_by_openalex_id(self, sa_sync_conn, publisher_store):
        existing = insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P4310310871")
        found = find_or_create_publisher(
            "Elsevier BV", openalex_id="P4310310871", repo=publisher_store
        )
        assert found == existing

    def test_un_nom_encode_rejoint_le_meme_editeur_que_le_nom_en_clair(
        self, sa_sync_conn, publisher_store
    ):
        """Régression : même cause et même correction que pour les revues (cf. `TestFindOrCreateSerial`)."""
        premier = find_or_create_publisher("Taylor & Francis", repo=publisher_store)
        second = find_or_create_publisher("TAYLOR &amp; FRANCIS", repo=publisher_store)
        assert second == premier

    def test_finds_existing_by_name_form(self, sa_sync_conn, publisher_store):
        existing = find_or_create_publisher("Elsevier", repo=publisher_store)
        found = find_or_create_publisher("elsevier", repo=publisher_store)
        assert found == existing

    def test_variantes_de_nom_rejoignent_le_meme_editeur(self, sa_sync_conn, publisher_store):
        """Cas réels : formes juridiques, dates et « on behalf of » ajoutés par les sources."""
        elsevier = find_or_create_publisher("Elsevier BV", repo=publisher_store)
        for variant in (
            "Elsevier [1977-....]",
            "Elsevier Ltd.",
            "Elsevier on behalf of the American College of Cardiology Foundation",
        ):
            assert find_or_create_publisher(variant, repo=publisher_store) == elsevier
        row = _fetch_one(sa_sync_conn, "SELECT name FROM publishers WHERE id = :id", id=elsevier)
        assert row.name == "Elsevier BV"

    def test_attaches_openalex_id_if_missing(self, sa_sync_conn, publisher_store):
        existing = find_or_create_publisher("Elsevier", repo=publisher_store)
        find_or_create_publisher("Elsevier", openalex_id="P123", repo=publisher_store)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=existing
        )
        assert row.openalex_id == "P123"


# ── find_or_create_serial ─────────────────────────────────────────


class TestFindOrCreateSerial:
    def test_returns_none_on_empty_title(self, sa_sync_conn, gateway):
        assert _find_or_create(None, repo=gateway) is None
        assert _find_or_create("", repo=gateway) is None

    def test_creates_new_serial(self, sa_sync_conn, gateway):
        j_id = _find_or_create("Nature", issn="0028-0836", repo=gateway)
        row = _fetch_one(sa_sync_conn, "SELECT title FROM serials WHERE id = :id", id=j_id)
        row = SimpleNamespace(title=row.title, issn=issn_columns(sa_sync_conn, j_id).issn)
        assert row.title == "Nature"
        assert row.issn == "0028-0836"

    def test_un_titre_encode_rejoint_le_meme_serial_que_le_titre_en_clair(
        self, sa_sync_conn, gateway
    ):
        """Régression : le titre affiché et la clé de rapprochement dérivent de la même valeur.

        Les sources livrent le même titre tantôt en clair, tantôt avec des entités HTML. Tant
        que la clé se calculait sur le titre reçu et le titre affiché sur sa mise à plat, les
        deux formes avaient des clés distinctes (`... amp ...`) et la revue naissait en deux
        exemplaires — quatre cas relevés en base.
        """
        premier = _find_or_create("Wood & Fire Safety", repo=gateway)
        second = _find_or_create("Wood &amp; Fire Safety", repo=gateway)
        assert second == premier
        row = _fetch_one(
            sa_sync_conn,
            "SELECT title, title_normalized FROM serials WHERE id = :id",
            id=premier,
        )
        assert row.title == "Wood & Fire Safety"
        assert "amp" not in row.title_normalized

    def test_finds_by_openalex_id(self, sa_sync_conn, gateway):
        existing = _serial(sa_sync_conn, openalex_id="S137773608")
        found = _find_or_create("Nature Journal", openalex_id="S137773608", repo=gateway)
        assert found == existing

    def test_finds_by_issn(self, sa_sync_conn, gateway):
        existing = _serial(sa_sync_conn, issn="0028-0836")
        found = _find_or_create("Nature Variant", issn="0028-0836", repo=gateway)
        assert found == existing

    def test_finds_by_eissn(self, sa_sync_conn, gateway):
        existing = _serial(sa_sync_conn, eissn="1476-4687")
        found = _find_or_create("Nature", eissn="1476-4687", repo=gateway)
        assert found == existing

    def test_finds_by_issnl(self, sa_sync_conn, gateway):
        existing = _serial(sa_sync_conn, issnl="0028-0836")
        found = _find_or_create("Other Title", issnl="0028-0836", repo=gateway)
        assert found == existing

    def test_finds_by_name_form(self, sa_sync_conn, gateway):
        _find_or_create("Nature", repo=gateway)
        found = _find_or_create("nature", repo=gateway)
        n = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS n FROM serials WHERE title_normalized = 'nature'")
        ).scalar_one()
        assert n == 1
        assert found is not None

    def test_enriches_metadata_on_match(self, sa_sync_conn, gateway, publisher_store):
        """Une revue trouvée par ISSN reçoit l'ISSN qu'elle n'a pas. L'éditeur du document s'enregistre avec la forme de nom, la revue n'en reçoit pas."""
        existing = _serial(sa_sync_conn, issn="0028-0836")
        publisher_id = find_or_create_publisher("Springer", repo=publisher_store)
        _find_or_create(
            "Nature",
            issn="0028-0836",
            eissn="1476-4687",
            publisher_id=publisher_id,
            repo=gateway,
        )
        assert issn_columns(sa_sync_conn, existing).eissn == "1476-4687"
        assert (
            _fetch_one(
                sa_sync_conn, "SELECT publisher_id FROM serials WHERE id = :id", id=existing
            ).publisher_id
            is None
        )
        assert (
            _fetch_one(
                sa_sync_conn,
                "SELECT count(*) AS n FROM serial_name_forms WHERE serial_id = :id AND publisher_id = :p",
                id=existing,
                p=publisher_id,
            ).n
            == 1
        )

    def test_normalizes_issn_on_create(self, sa_sync_conn, gateway):
        j_id = _find_or_create("Nature", issn="00280836", eissn="1476-4687", repo=gateway)
        row = issn_columns(sa_sync_conn, j_id)
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
        row = issn_columns(sa_sync_conn, j_id)
        assert row.issn is None
        assert row.eissn == "1476-4687"
        assert row.rejected_issns == ["(Internet)"]
        assert "ISSN mal formé (revue 'Nature') : '(Internet)'" in caplog.text

    def test_rejected_issns_accumulate_without_duplicates(self, sa_sync_conn, gateway):
        """Les ISSN invalides s'ajoutent à ceux de la revue trouvée, sans doublon."""
        j_id = _find_or_create("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        _find_or_create("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        _find_or_create("Nature", issn="0028-0836", issnl="1234-5678", repo=gateway)
        row = issn_columns(sa_sync_conn, j_id)
        assert row.rejected_issns == ["1234-5678", "1476-4688"]

    def test_known_issn_is_not_copied_into_a_free_column(self, sa_sync_conn, gateway):
        """Une source qui donne comme ISSN papier l'ISSN électronique d'une revue vérifiée ne défait pas son rangement."""
        j_id = _serial(sa_sync_conn, eissn="1476-4687")
        mark_checked_in_sudoc(sa_sync_conn, j_id)
        _find_or_create("Nature", issn="1476-4687", repo=gateway)
        row = issn_columns(sa_sync_conn, j_id)
        assert row.issn is None
        assert row.eissn == "1476-4687"
        assert row.sudoc_checked_at is not None

    def test_issnl_value_can_fill_the_issn_column(self, sa_sync_conn, gateway):
        """Régression : l'ISSN-L est l'ISSN de l'un des supports, il peut donc aussi figurer dans `issn`."""
        j_id = _serial(sa_sync_conn, issnl="0028-0836")
        _find_or_create("Nature", issn="0028-0836", repo=gateway)
        row = issn_columns(sa_sync_conn, j_id)
        assert (row.issn, row.issnl) == ("0028-0836", "0028-0836")

    def test_rejected_issn_is_not_copied_into_a_column(self, sa_sync_conn, gateway):
        """Un ISSN rejeté (ici un CD-ROM) retrouve la revue sans revenir dans une colonne."""
        j_id = _serial(sa_sync_conn, issn="0305-1048", rejected=("1362-4954",))
        mark_checked_in_sudoc(sa_sync_conn, j_id)
        found = _find_or_create("Other title", eissn="1362-4954", repo=gateway)
        row = issn_columns(sa_sync_conn, j_id)
        assert found == j_id
        assert row.eissn is None
        assert row.sudoc_checked_at is not None

    def test_new_issn_makes_the_serial_to_check_again(self, sa_sync_conn, gateway):
        j_id = _serial(sa_sync_conn, eissn="1476-4687")
        mark_checked_in_sudoc(sa_sync_conn, j_id)
        _find_or_create("Nature", issn="0028-0836", eissn="1476-4687", repo=gateway)
        row = issn_columns(sa_sync_conn, j_id)
        assert row.issn == "0028-0836"
        assert row.sudoc_checked_at is None

    def test_new_rejected_issn_makes_the_serial_to_check_again(self, sa_sync_conn, gateway):
        j_id = _serial(sa_sync_conn, issn="0028-0836")
        mark_checked_in_sudoc(sa_sync_conn, j_id)
        _find_or_create("Nature", issn="0028-0836", eissn="1476-4688", repo=gateway)
        row = issn_columns(sa_sync_conn, j_id)
        assert row.rejected_issns == ["1476-4688"]
        assert row.sudoc_checked_at is None


# ── SerialStore.update_serial_apc ─────────────────────────────────────────────


class TestUpdateSerialApc:
    def test_updates_fields(self, sa_sync_conn, gateway):
        j_id = _serial(sa_sync_conn)
        update_serial_apc(sa_sync_conn, j_id, apc_amount=3000.0, apc_currency="EUR")
        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency FROM serials WHERE id = :id",
            id=j_id,
        )
        assert float(row.apc_amount) == 3000.0
        assert row.apc_currency == "EUR"

    def test_coalesce_preserves_existing_and_leaves_is_in_doaj(self, sa_sync_conn, gateway):
        """Sans nouvelle valeur, l'APC existant est conservé ; `is_in_doaj` (autorité
        DOAJ) n'est jamais touché par l'enrichissement APC."""
        j_id = _serial(sa_sync_conn, is_in_doaj=True, apc_amount=2000.0, apc_currency="USD")
        update_serial_apc(sa_sync_conn, j_id, apc_currency="EUR")
        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency, is_in_doaj FROM serials WHERE id = :id",
            id=j_id,
        )
        assert float(row.apc_amount) == 2000.0
        assert row.apc_currency == "EUR"
        assert row.is_in_doaj is True
