"""Journal des recherches infructueuses : inscription, délai de reprise, effacement."""

from datetime import timedelta

from sqlalchemy import text

from infrastructure.pipeline.fetch_missing.failed_lookups import (
    forget_failed_doi_lookups,
    record_failed_lookup,
)


def _next_retry(conn, source, id_type, id_value):
    return conn.execute(
        text(
            "SELECT next_retry FROM failed_lookups "
            "WHERE source = CAST(:s AS source_type) AND id_type = :t AND id_value = :v"
        ),
        {"s": source, "t": id_type, "v": id_value},
    ).scalar_one()


def _count(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM failed_lookups")).scalar_one()


class TestRecordFailedLookup:
    def test_un_doi_absent_d_une_source_non_native_est_repris_plus_tard(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x", retry_after_days=30)
        pending = sa_sync_conn.execute(
            text("SELECT next_retry > now() FROM failed_lookups WHERE id_value = '10.1234/x'")
        ).scalar_one()
        assert pending is True

    def test_un_doi_absent_de_crossref_est_definitif(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "crossref", "doi", "10.1234/x", retry_after_days=30)
        assert _next_retry(sa_sync_conn, "crossref", "doi", "10.1234/x") is None

    def test_un_hal_id_absent_de_hal_est_definitif(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "hal_id", "hal-01234567", retry_after_days=30)
        assert _next_retry(sa_sync_conn, "hal", "hal_id", "hal-01234567") is None

    def test_un_nnt_absent_de_hal_est_repris_plus_tard(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "nnt", "2024UCA0001", retry_after_days=30)
        assert _next_retry(sa_sync_conn, "hal", "nnt", "2024UCA0001") is not None

    def test_un_second_echec_rearme_la_ligne_sans_doublon(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x", retry_after_days=30)
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x", retry_after_days=30)
        assert _count(sa_sync_conn) == 1

    def test_la_reprise_suit_le_delai_transmis(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x", retry_after_days=7)
        delai = sa_sync_conn.execute(
            text("SELECT next_retry - not_found_at FROM failed_lookups")
        ).scalar_one()
        assert delai == timedelta(days=7)


class TestForgetFailedDoiLookups:
    def test_un_doi_livre_par_la_source_quitte_la_table(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "scanr", "doi", "10.1234/x", retry_after_days=30)
        forget_failed_doi_lookups(sa_sync_conn, "scanr", ["10.1234/x"])
        assert _count(sa_sync_conn) == 0

    def test_les_autres_sources_gardent_la_leur(self, sa_sync_conn):
        """Une source qui livre le document ne dit rien de ce que les autres connaissent."""
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x", retry_after_days=30)
        forget_failed_doi_lookups(sa_sync_conn, "scanr", ["10.1234/x"])
        restant = sa_sync_conn.execute(text("SELECT source FROM failed_lookups")).scalar_one()
        assert restant == "hal"

    def test_normalise_les_doi_avant_de_les_chercher(self, sa_sync_conn):
        """La table porte des DOI normalisés ; le document reçu les expose sous n'importe quelle forme."""
        record_failed_lookup(sa_sync_conn, "scanr", "doi", "10.1234/casse", retry_after_days=30)
        forget_failed_doi_lookups(sa_sync_conn, "scanr", ["HTTPS://DOI.ORG/10.1234/Casse"])
        assert _count(sa_sync_conn) == 0

    def test_un_document_sans_doi_laisse_la_table_intacte(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "scanr", "doi", "10.1234/x", retry_after_days=30)
        forget_failed_doi_lookups(sa_sync_conn, "scanr", [None])
        assert _count(sa_sync_conn) == 1
