"""Hygiène des tâches de fond.

Une tâche de fond ouvre sa propre connexion (`interfaces/api/deps.py`, `with engine.begin()` : rollback et fermeture en sortie, même sur exception) et logue l'erreur de son travail. Quand la propagation lève, la tâche n'escalade pas l'erreur et rend sa connexion au pool : aucune transaction ne reste ouverte (idle in transaction).
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
    bg_propagate_in_perimeter([1])  # ne doit pas lever (erreur loggée)
    assert pool.checkedout() == before  # connexion rendue → pas d'idle in transaction


def test_bg_propagate_countries_swallows_errors_and_releases_connection(monkeypatch):
    monkeypatch.setattr(AddressService, "propagate_countries_to_publications", _boom)
    pool = get_sync_engine().pool
    before = pool.checkedout()
    bg_propagate_countries([1])  # ne doit pas lever (erreur loggée)
    assert pool.checkedout() == before
