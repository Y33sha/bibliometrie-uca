"""La transaction de la requête : `db_conn` committe une écriture qui aboutit avec ses événements d'audit, et une seule connexion sert toute la requête."""

from collections.abc import Iterable, Iterator
from types import SimpleNamespace

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from interfaces.api import deps
from interfaces.api.app import app


class _Connection:
    """Connexion factice qui consigne les gestes de fin de transaction."""

    def __init__(self) -> None:
        self.gestes: list[str] = []

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.gestes.append("close")

    def commit(self) -> None:
        self.gestes.append("commit")

    def rollback(self) -> None:
        self.gestes.append("rollback")


@pytest.fixture
def connexion(monkeypatch) -> _Connection:
    conn = _Connection()
    monkeypatch.setattr(deps, "_open_connection", lambda request: conn)
    monkeypatch.setattr(deps, "audit_repository", lambda c: c)
    monkeypatch.setattr(deps, "record_pending_events", lambda c: c.gestes.append("audit"))
    return conn


def _requete(methode: str) -> Iterator:
    return deps.db_conn(SimpleNamespace(method=methode))


def test_une_ecriture_qui_aboutit_est_committee_avec_son_audit(connexion):
    gen = _requete("POST")
    next(gen)
    with pytest.raises(StopIteration):
        next(gen)
    assert connexion.gestes == ["audit", "commit", "close"]


def test_une_exception_annule_l_ecriture(connexion):
    gen = _requete("POST")
    next(gen)
    with pytest.raises(ValueError):
        gen.throw(ValueError("refus"))
    assert connexion.gestes == ["rollback", "close"]


def test_une_lecture_ne_committe_rien(connexion):
    gen = _requete("GET")
    next(gen)
    with pytest.raises(StopIteration):
        next(gen)
    assert connexion.gestes == ["close"]


def _routes(routes: Iterable[BaseRoute]) -> Iterator[APIRoute]:
    """Routes de l'application, y compris celles des routeurs inclus."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif (routeur := getattr(route, "original_router", None)) is not None:
            yield from _routes(routeur.routes)


def _dependances(dependant: Dependant) -> Iterator[Dependant]:
    for sous_dependance in dependant.dependencies:
        yield sous_dependance
        yield from _dependances(sous_dependance)


def test_la_connexion_de_la_requete_est_declaree_avec_un_seul_scope() -> None:
    """Une déclaration d'un autre scope ouvrirait une seconde connexion dans la même requête, avec sa propre transaction."""
    scopes = [
        (route.path, dependance.scope)
        for route in _routes(app.routes)
        for dependance in _dependances(route.dependant)
        if dependance.call is deps.db_conn
    ]
    assert scopes, "Aucune route ne déclare la connexion de la requête : le parcours est vide."
    ecarts = sorted(chemin for chemin, scope in scopes if scope != "function")
    assert not ecarts, f"`db_conn` déclaré hors de `DbConn` : {ecarts}"
