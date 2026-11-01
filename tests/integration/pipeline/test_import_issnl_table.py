"""Import de la table ISSN-L de l'ISSN International Centre (`import_issnl_table`)."""

import logging
from contextlib import contextmanager

from sqlalchemy import text

from pipeline.http.dump_download import DumpUnavailableError
from pipeline.transformation.publishing.serials.import_issnl_table import run_import_issnl_table
from tests.integration.helpers.serials import insert_serial_issn

_LOG = logging.getLogger("test_import_issnl_table")


def _table(pairs):
    @contextmanager
    def download():
        yield iter(pairs)

    return download


def _unavailable():
    raise DumpUnavailableError("réseau")


def _issnls(conn) -> dict[str, tuple[str | None, bool]]:
    return {
        r.issn: (r.issnl, r.checked)
        for r in conn.execute(
            text("SELECT issn, issnl, issnl_checked_at IS NOT NULL AS checked FROM serial_issns")
        )
    }


def _run(conn, download, *, refresh_after_days=30):
    return run_import_issnl_table(
        conn, _LOG, refresh_after_days=refresh_after_days, download_table=download
    )


def test_chaque_issn_recoit_l_issnl_de_la_table(sa_sync_conn):
    insert_serial_issn(sa_sync_conn, None, issn="0735-7036", issnl="0093-4127")
    insert_serial_issn(sa_sync_conn, None, issn="1939-2087")
    insert_serial_issn(sa_sync_conn, None, issn="0028-0836", issnl="0028-0836")

    metrics = _run(
        sa_sync_conn,
        _table([("ISSN", "ISSN-L"), ("0735-7036", "1939-2087"), ("1939-2087", "1939-2087")]),
    )

    assert _issnls(sa_sync_conn) == {
        "0735-7036": ("1939-2087", True),
        "1939-2087": ("1939-2087", True),
        "0028-0836": (None, True),
    }
    assert (metrics.extras["matched"], metrics.extras["changed"]) == (2, 3)


def test_un_import_recent_saute_le_telechargement(sa_sync_conn):
    insert_serial_issn(sa_sync_conn, None, issn="0028-0836")
    _run(sa_sync_conn, _table([("0028-0836", "0028-0836")]))

    metrics = _run(sa_sync_conn, _unavailable)

    assert metrics.extras["skipped"] == 1


def test_une_table_inaccessible_laisse_les_issnl(sa_sync_conn):
    insert_serial_issn(sa_sync_conn, None, issn="0028-0836", issnl="0028-0836")

    metrics = _run(sa_sync_conn, _unavailable)

    assert _issnls(sa_sync_conn) == {"0028-0836": ("0028-0836", False)}
    assert metrics.signals


def test_une_table_sans_aucun_de_nos_issn_laisse_les_issnl(sa_sync_conn):
    insert_serial_issn(sa_sync_conn, None, issn="0028-0836", issnl="0028-0836")

    metrics = _run(sa_sync_conn, _table([("1234-5679", "1234-5679")]))

    assert _issnls(sa_sync_conn) == {"0028-0836": ("0028-0836", False)}
    assert metrics.signals[0]["code"] == "dump_unrecognized"
