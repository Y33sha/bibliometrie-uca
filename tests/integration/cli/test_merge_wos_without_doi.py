"""Oneshot `merge_wos_without_doi` : paires d'un enregistrement source WoS sans DOI et d'une publication de même revue, même année et même première page."""

from interfaces.cli.oneshot.merge_wos_without_doi import Pair, find_pairs
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_serial
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_PAGES = {"first_page": "237", "last_page": "250"}


def _record(conn, serial, *, source, source_id, title, last_name="stolz", biblio=None, doi=None):
    """Sème une publication d'un seul enregistrement source de l'année 2025, à un auteur de nom de famille `last_name`, et renvoie la publication."""
    publication = insert_publication(conn, title, publication_year=2025)
    source_record = insert_source_record(
        conn,
        publication,
        source=source,
        source_id=source_id,
        title=title,
        publication_year=2025,
        serial_id=serial,
        biblio=_PAGES if biblio is None else biblio,
        doi=doi,
    )
    insert_source_contribution(
        conn,
        source_record,
        source=source,
        raw_last_name=last_name.capitalize(),
        raw_first_name="Michael",
        author_name_normalized=f"michael {last_name}",
    )
    return publication


def test_un_article_traduit_est_apparie(sa_sync_conn):
    """Cas réel : WoS donne en anglais le titre d'un article en français."""
    conn = sa_sync_conn
    serial = insert_serial(conn, "Cahiers de civilisation médiévale")
    wos = _record(conn, serial, source="wos", source_id="WOS:1", title="An archeology of exclusion")
    hal = _record(
        conn, serial, source="hal", source_id="hal-1", title="Une archéologie de l'exclusion"
    )

    pairs, outcomes = find_pairs(conn)

    assert pairs == [Pair("WOS:1", "An archeology of exclusion", wos, hal)]
    assert not outcomes


def test_sans_auteur_commun_la_paire_est_ecartee(sa_sync_conn):
    conn = sa_sync_conn
    serial = insert_serial(conn, "J")
    _record(conn, serial, source="wos", source_id="WOS:1", title="Editorial")
    _record(conn, serial, source="hal", source_id="hal-1", title="Éditorial", last_name="martin")

    assert find_pairs(conn) == ([], {"aucun auteur commun": 1})


def test_deux_publications_en_face_la_paire_est_ecartee(sa_sync_conn):
    conn = sa_sync_conn
    serial = insert_serial(conn, "J")
    _record(conn, serial, source="wos", source_id="WOS:1", title="A")
    _record(conn, serial, source="hal", source_id="hal-1", title="B")
    _record(conn, serial, source="crossref", source_id="10.1/c", title="C", doi="10.1/c")

    assert find_pairs(conn) == ([], {"plusieurs publications en face": 1})


def test_dernieres_pages_differentes_aucune_paire(sa_sync_conn):
    conn = sa_sync_conn
    serial = insert_serial(conn, "J")
    _record(conn, serial, source="wos", source_id="WOS:1", title="A")
    _record(
        conn,
        serial,
        source="hal",
        source_id="hal-1",
        title="B",
        biblio={"first_page": "237", "last_page": "238"},
    )

    assert find_pairs(conn) == ([], {})


def test_un_enregistrement_wos_a_doi_est_ignore(sa_sync_conn):
    conn = sa_sync_conn
    serial = insert_serial(conn, "J")
    _record(conn, serial, source="wos", source_id="WOS:1", title="A", doi="10.1/a")
    _record(conn, serial, source="hal", source_id="hal-1", title="B")

    assert find_pairs(conn) == ([], {})
