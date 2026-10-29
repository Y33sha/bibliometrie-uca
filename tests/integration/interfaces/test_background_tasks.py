"""Hygiène des tâches de fond.

Une tâche de fond ouvre sa propre transaction par `engine.begin()` (rollback et fermeture en sortie, même sur exception). Quand la propagation lève une exception, la tâche la journalise sans la relancer et rend sa connexion au pool : aucune transaction ne reste ouverte.
"""

from application.services.addresses import AddressService
from infrastructure.db.engine import get_sync_engine
from interfaces.api.deps import bg_propagate_countries, bg_propagate_in_perimeter


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


def test_bg_propagate_in_perimeter_swallows_errors_and_releases_connection(monkeypatch):
    monkeypatch.setattr(AddressService, "propagate_in_perimeter_for_addresses", _boom)
    pool = get_sync_engine().pool
    before = pool.checkedout()
    bg_propagate_in_perimeter([1])  # erreur journalisée, sans exception
    assert pool.checkedout() == before  # connexion rendue au pool


def test_bg_propagate_countries_swallows_errors_and_releases_connection(monkeypatch):
    monkeypatch.setattr(AddressService, "propagate_countries_to_publications", _boom)
    pool = get_sync_engine().pool
    before = pool.checkedout()
    bg_propagate_countries([1])  # erreur journalisée, sans exception
    assert pool.checkedout() == before
