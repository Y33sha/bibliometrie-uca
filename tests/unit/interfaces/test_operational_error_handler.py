"""Traduction en 503 d'une lecture interrompue par le plafond de durée des requêtes SQL."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from interfaces.api.app import operational_error_handler, unhandled_exception_handler


def _client_levant(sqlstate: str) -> TestClient:
    orig = Exception("requête interrompue")
    orig.sqlstate = sqlstate  # type: ignore[attr-defined]
    app = FastAPI()
    app.add_exception_handler(OperationalError, operational_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/boum")
    def boum() -> None:
        raise OperationalError("SELECT 1", {}, orig)

    return TestClient(app, raise_server_exceptions=False)


def test_une_requete_interrompue_donne_503():
    r = _client_levant("57014").get("/boum")
    assert r.status_code == 503
    assert r.json()["detail"] == "La requête a dépassé la durée maximale autorisée."


def test_une_autre_erreur_operationnelle_reste_en_500():
    assert _client_levant("08006").get("/boum").status_code == 500
