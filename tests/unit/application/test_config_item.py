"""Masquage des clés secrètes par `ConfigItem.from_stored`.

Une clé de `SECRET_CONFIG_KEYS` s'écrit mais ne se relit pas : la lecture rend `value=None` et un indicateur `is_set`, jamais le secret en clair.
"""

from application.ports.read_models.config_queries import ConfigItem


class TestConfigItemFromStored:
    def test_secret_key_hides_value_but_reports_it_set(self):
        item = ConfigItem.from_stored(key="wos_api_key", value="super-secret", description=None)
        assert item.value is None
        assert item.is_set is True

    def test_secret_key_reports_not_set_when_empty(self):
        for empty in (None, ""):
            item = ConfigItem.from_stored(key="scanr_password", value=empty, description=None)
            assert item.value is None
            assert item.is_set is False

    def test_non_secret_key_keeps_value(self):
        item = ConfigItem.from_stored(key="pipeline_start_year_full", value=2018, description="d")
        assert item.value == 2018
        assert item.is_set is True
        assert item.description == "d"
