"""Phase 5 (chantier background-jobs) — hygiène des tâches de fond.

Invariant : une `BackgroundTasks` ne doit jamais laisser une transaction ouverte
(idle in transaction) si son travail plante. Les BG tasks (`interfaces/api/deps.py`)
ouvrent leur propre connexion via `with engine.begin()` (rollback + close en
sortie, même sur exception) et enveloppent le tout dans un `try/except` qui logue.

On vérifie le contrat de bout en bout : quand la propagation interne lève, la BG
task n'escalade pas l'erreur **et** rend sa connexion au pool (aucune fuite).
"""

import application.services.addresses.countries as countries_service
import application.services.authorships.core as authorships_core
from infrastructure.db.engine import get_sync_engine
from interfaces.api.deps import bg_propagate_countries, bg_propagate_in_perimeter


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


def test_bg_propagate_in_perimeter_swallows_errors_and_releases_connection(monkeypatch):
    monkeypatch.setattr(authorships_core, "propagate_in_perimeter_for_addresses", _boom)
    pool = get_sync_engine().pool
    before = pool.checkedout()
    bg_propagate_in_perimeter([1])  # ne doit pas lever (erreur loggée)
    assert pool.checkedout() == before  # connexion rendue → pas d'idle in transaction


def test_bg_propagate_countries_swallows_errors_and_releases_connection(monkeypatch):
    monkeypatch.setattr(countries_service, "propagate_countries_to_publications", _boom)
    pool = get_sync_engine().pool
    before = pool.checkedout()
    bg_propagate_countries([1])  # ne doit pas lever (erreur loggée)
    assert pool.checkedout() == before
