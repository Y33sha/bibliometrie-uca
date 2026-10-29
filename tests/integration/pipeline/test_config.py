"""Lecture de la configuration du pipeline depuis la table `config`.

Les clés de forme imposée (plafonds d'interrogation, délais de réinterrogation, année de départ) sont contrôlées à l'écriture, et la table refuse une valeur hors de cette forme. Pour les autres clés, une valeur illisible est signalée et le réglage prend sa valeur par défaut ; le pipeline continue.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from domain.config import SETTINGS, ConfigKey
from domain.dates import today
from pipeline.runtime.config import cap, delay, get_years
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

    Le domaine applique la même règle à l'écriture (`normalize_config_value`). Ces contraintes couvrent les écritures qui contournent le domaine : psql, migration, script.
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
        assert cap(sa_sync_conn, ConfigKey.UNPAYWALL_MAX_PER_RUN) == 250

    def test_zero_vaut_illimite_pour_unpaywall(self, sa_sync_conn):
        set_config(sa_sync_conn, "unpaywall_max_per_run", 0)
        assert cap(sa_sync_conn, ConfigKey.UNPAYWALL_MAX_PER_RUN) is None

    def test_la_cle_absente_laisse_le_plafond_par_defaut(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'unpaywall_max_per_run'"))
        assert (
            cap(sa_sync_conn, ConfigKey.UNPAYWALL_MAX_PER_RUN)
            == SETTINGS[ConfigKey.UNPAYWALL_MAX_PER_RUN].default
        )

    def test_le_plafond_de_fetch_missing_configure_est_lu(self, sa_sync_conn):
        set_config(sa_sync_conn, "fetch_missing_max_per_source", 5000)
        assert cap(sa_sync_conn, ConfigKey.FETCH_MISSING_MAX_PER_SOURCE) == 5000

    def test_zero_vaut_illimite_pour_fetch_missing(self, sa_sync_conn):
        set_config(sa_sync_conn, "fetch_missing_max_per_source", 0)
        assert cap(sa_sync_conn, ConfigKey.FETCH_MISSING_MAX_PER_SOURCE) is None

    def test_fetch_missing_sans_cle_est_illimite(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'fetch_missing_max_per_source'"))
        assert cap(sa_sync_conn, ConfigKey.FETCH_MISSING_MAX_PER_SOURCE) is None


class TestDelais:
    """Délais de réinterrogation lus en configuration, en jours."""

    @pytest.mark.parametrize(
        "key",
        [
            ConfigKey.FETCH_STALE_AFTER_DAYS,
            ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS,
            ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS,
            ConfigKey.DOAJ_REFRESH_AFTER_DAYS,
        ],
    )
    def test_le_delai_configure_est_lu(self, sa_sync_conn, key):
        set_config(sa_sync_conn, key.value, 7)
        assert delay(sa_sync_conn, key) == 7

    def test_la_cle_absente_laisse_le_delai_par_defaut(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'fetch_stale_after_days'"))
        assert (
            delay(sa_sync_conn, ConfigKey.FETCH_STALE_AFTER_DAYS)
            == SETTINGS[ConfigKey.FETCH_STALE_AFTER_DAYS].default
        )
