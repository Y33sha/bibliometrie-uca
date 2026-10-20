"""Lecture de la configuration du pipeline depuis la table `config`.

Les clés dont la forme est imposée — plafonds d'interrogation, délais de réinterrogation, année de départ — sont contrôlées à l'écriture, et la table refuse ce qui s'en écarte. Pour les autres, une valeur illisible ne fait pas échouer le pipeline : elle est signalée et le réglage retombe sur son défaut.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from domain.dates import today
from pipeline.runtime.config import (
    FETCH_STALE_AFTER_DAYS_DEFAULT,
    UNPAYWALL_MAX_PER_RUN_DEFAULT,
    get_doaj_refresh_after_days,
    get_fetch_missing_max_per_source,
    get_fetch_missing_retry_after_days,
    get_fetch_stale_after_days,
    get_unpaywall_max_per_run,
    get_unpaywall_recheck_after_days,
    get_years,
)
from tests.integration.helpers.config import set_config


class TestGetYears:
    def test_uses_config_anchor_when_no_argument(self, sa_sync_conn):
        set_config(sa_sync_conn, "pipeline_start_year_full", 2017)
        current = today().year
        assert get_years(sa_sync_conn) == list(range(2017, current + 1))

    def test_explicit_start_year_overrides_config(self, sa_sync_conn):
        set_config(sa_sync_conn, "pipeline_start_year_full", 2017)
        current = today().year
        assert get_years(sa_sync_conn, start_year=2020) == list(range(2020, current + 1))

    def test_falls_back_to_current_year_when_unset(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'pipeline_start_year_full'"))
        current = today().year
        assert get_years(sa_sync_conn) == [current]

    def test_falls_back_when_start_year_in_future(self, sa_sync_conn):
        current = today().year
        assert get_years(sa_sync_conn, start_year=current + 5) == [current]


class TestFormeImposeeEnBase:
    """La table refuse une valeur hors de la forme que sa clé impose, quelle que soit la voie d'écriture.

    Le domaine porte la même règle et la fait valoir à l'écriture (`normalize_config_value`). Ces contraintes tiennent les voies qui la contournent : psql, migration, script.
    """

    @pytest.mark.parametrize("valeur", ["pas une année", True, "2017", 1969, 3.5])
    def test_une_annee_hors_forme_est_refusee(self, sa_sync_conn, valeur):
        with pytest.raises(IntegrityError, match="config_year_is_in_range"):
            set_config(sa_sync_conn, "pipeline_start_year_full", valeur)

    @pytest.mark.parametrize("valeur", ["beaucoup", -1, True, 2.5])
    def test_un_plafond_hors_forme_est_refuse(self, sa_sync_conn, valeur):
        with pytest.raises(IntegrityError, match="config_cap_is_non_negative_integer"):
            set_config(sa_sync_conn, "unpaywall_max_per_run", valeur)

    @pytest.mark.parametrize("valeur", ["longtemps", 0, -3, True, 1.5])
    def test_un_delai_hors_forme_est_refuse(self, sa_sync_conn, valeur):
        with pytest.raises(IntegrityError, match="config_delay_is_positive_integer"):
            set_config(sa_sync_conn, "fetch_stale_after_days", valeur)


class TestPlafondsParRun:
    """Plafonds d'interrogation lus en configuration, zéro valant illimité."""

    def test_le_plafond_unpaywall_configure_est_lu(self, sa_sync_conn):
        set_config(sa_sync_conn, "unpaywall_max_per_run", 250)
        assert get_unpaywall_max_per_run(sa_sync_conn) == 250

    def test_zero_vaut_illimite_pour_unpaywall(self, sa_sync_conn):
        set_config(sa_sync_conn, "unpaywall_max_per_run", 0)
        assert get_unpaywall_max_per_run(sa_sync_conn) is None

    def test_la_cle_absente_laisse_le_plafond_par_defaut(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'unpaywall_max_per_run'"))
        assert get_unpaywall_max_per_run(sa_sync_conn) == UNPAYWALL_MAX_PER_RUN_DEFAULT

    def test_le_plafond_de_fetch_missing_configure_est_lu(self, sa_sync_conn):
        set_config(sa_sync_conn, "fetch_missing_max_per_source", 5000)
        assert get_fetch_missing_max_per_source(sa_sync_conn) == 5000

    def test_zero_vaut_illimite_pour_fetch_missing(self, sa_sync_conn):
        set_config(sa_sync_conn, "fetch_missing_max_per_source", 0)
        assert get_fetch_missing_max_per_source(sa_sync_conn) is None

    def test_fetch_missing_sans_cle_est_illimite(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'fetch_missing_max_per_source'"))
        assert get_fetch_missing_max_per_source(sa_sync_conn) is None


class TestDelais:
    """Délais de réinterrogation lus en configuration, en jours."""

    @pytest.mark.parametrize(
        ("key", "lire"),
        [
            ("fetch_stale_after_days", get_fetch_stale_after_days),
            ("fetch_missing_retry_after_days", get_fetch_missing_retry_after_days),
            ("unpaywall_recheck_after_days", get_unpaywall_recheck_after_days),
            ("doaj_refresh_after_days", get_doaj_refresh_after_days),
        ],
    )
    def test_le_delai_configure_est_lu(self, sa_sync_conn, key, lire):
        set_config(sa_sync_conn, key, 7)
        assert lire(sa_sync_conn) == 7

    def test_la_cle_absente_laisse_le_delai_par_defaut(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'fetch_stale_after_days'"))
        assert get_fetch_stale_after_days(sa_sync_conn) == FETCH_STALE_AFTER_DAYS_DEFAULT
