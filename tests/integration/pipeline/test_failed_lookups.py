"""Journal des recherches infructueuses : inscription, délai de reprise, effacement."""

import pytest
from sqlalchemy import text

from domain.sources.registry import DOI_ORG
from pipeline.ingestion.common.failed_lookups import (
    forget_failed_doi_lookups,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.common.staging import StagingStore


def _count(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM failed_lookups")).scalar_one()


def _pending(conn, source, id_type, id_value, retry_after_days) -> bool:
    condition = pending_failed_lookup_sql(source_sql=":source", id_type=id_type, value_sql=":value")
    return conn.execute(
        text(f"SELECT {condition}"),
        {"source": source, "value": id_value, "retry_after_days": retry_after_days},
    ).scalar_one()


class TestRecordFailedLookup:
    def test_un_echec_recent_attend_le_delai(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x")
        assert _pending(sa_sync_conn, "hal", "doi", "10.1234/x", 30) is True

    def test_un_doi_absent_de_crossref_est_repris_apres_le_delai(self, sa_sync_conn):
        """Régression : un échec chez l'agence d'enregistrement du DOI restait définitif, alors que Crossref peut renvoyer le DOI plus tard."""
        record_failed_lookup(sa_sync_conn, "crossref", "doi", "10.1234/x")
        sa_sync_conn.execute(
            text("UPDATE failed_lookups SET not_found_at = now() - interval '31 days'")
        )
        assert _pending(sa_sync_conn, "crossref", "doi", "10.1234/x", 30) is False

    def test_doi_org_est_une_source_d_echec(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, DOI_ORG, "doi", "10.1364/ao.xx.xxxxxx")
        assert _pending(sa_sync_conn, DOI_ORG, "doi", "10.1364/ao.xx.xxxxxx", 30) is True

    @pytest.mark.parametrize(
        ("source", "id_type", "id_value"),
        [
            ("hal", "hal_id", "hal-01234567"),
            ("theses", "nnt", "2020UCFA0001"),
            (DOI_ORG, "doi", "10.1364/ao.xx.xxxxxx"),
        ],
    )
    def test_un_identifiant_absent_de_son_registre_n_est_plus_cherche(
        self, sa_sync_conn, source, id_type, id_value
    ):
        """Régression : un hal-id introuvable dans HAL était cherché de nouveau après le délai."""
        record_failed_lookup(sa_sync_conn, source, id_type, id_value)
        sa_sync_conn.execute(
            text("UPDATE failed_lookups SET not_found_at = now() - interval '365 days'")
        )
        assert _pending(sa_sync_conn, source, id_type, id_value, 30) is True

    def test_un_nnt_absent_de_hal_est_repris_apres_le_delai(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "nnt", "2020UCFA0001")
        sa_sync_conn.execute(
            text("UPDATE failed_lookups SET not_found_at = now() - interval '31 days'")
        )
        assert _pending(sa_sync_conn, "hal", "nnt", "2020UCFA0001", 30) is False

    def test_un_second_echec_redate_la_ligne_sans_doublon(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x")
        sa_sync_conn.execute(
            text("UPDATE failed_lookups SET not_found_at = now() - interval '60 days'")
        )
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x")
        assert _count(sa_sync_conn) == 1
        assert _pending(sa_sync_conn, "hal", "doi", "10.1234/x", 30) is True


class TestForgetFailedDoiLookups:
    def test_un_doi_livre_par_la_source_quitte_la_table(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "scanr", "doi", "10.1234/x")
        forget_failed_doi_lookups(sa_sync_conn, "scanr", ["10.1234/x"])
        assert _count(sa_sync_conn) == 0

    def test_les_autres_sources_gardent_la_leur(self, sa_sync_conn):
        """Une source qui livre le document ne dit rien de ce que les autres connaissent."""
        record_failed_lookup(sa_sync_conn, "hal", "doi", "10.1234/x")
        forget_failed_doi_lookups(sa_sync_conn, "scanr", ["10.1234/x"])
        restant = sa_sync_conn.execute(text("SELECT source::text FROM failed_lookups")).scalar_one()
        assert restant == "hal"

    def test_normalise_les_doi_avant_de_les_chercher(self, sa_sync_conn):
        """La table contient des DOI normalisés ; le document reçu les expose sous n'importe quelle forme."""
        record_failed_lookup(sa_sync_conn, "scanr", "doi", "10.1234/casse")
        forget_failed_doi_lookups(sa_sync_conn, "scanr", ["HTTPS://DOI.ORG/10.1234/Casse"])
        assert _count(sa_sync_conn) == 0

    def test_un_document_sans_doi_laisse_la_table_intacte(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "scanr", "doi", "10.1234/x")
        forget_failed_doi_lookups(sa_sync_conn, "scanr", [None, ""])
        assert _count(sa_sync_conn) == 1

    def test_un_depot_rendu_par_hal_quitte_la_table(self, sa_sync_conn):
        record_failed_lookup(sa_sync_conn, "hal", "hal_id", "hal-03178520")
        record_failed_lookup(sa_sync_conn, "hal", "hal_id", "hal-05524892")
        StagingStore(sa_sync_conn).stage("hal", {"halId_s": "hal-03178520", "title_s": ["T"]})
        assert sa_sync_conn.execute(
            text("SELECT id_value FROM failed_lookups")
        ).scalars().all() == ["hal-05524892"]
