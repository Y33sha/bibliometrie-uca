"""Refus des caractères de contrôle dans les paramètres texte, et filet couvrant ce que le contrat ne borne pas."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError

from interfaces.api.app import data_error_handler, unhandled_exception_handler
from interfaces.api.params import reject_control_characters


def test_un_texte_ordinaire_passe():
    assert reject_control_characters("Dupont, Jean-René") == "Dupont, Jean-René"


@pytest.mark.parametrize("caractere", ["\x00", "\x07", "\x1b", "\x7f"])
def test_un_caractere_de_controle_est_refuse(caractere):
    with pytest.raises(ValueError, match="Caractères de contrôle interdits"):
        reject_control_characters(f"a{caractere}b")


def test_le_refus_nomme_les_caracteres_trouves():
    with pytest.raises(ValueError, match=r"U\+0000, U\+001B"):
        reject_control_characters("a\x00b\x1bc")


@pytest.mark.parametrize("caractere", ["\t", "\r", "\n"])
def test_les_separateurs_passent(caractere):
    assert reject_control_characters(f"a{caractere}b")


def _client_levant(exception: Exception) -> TestClient:
    """Application minimale dont la route lève l'exception donnée, munie des handlers de la surface HTTP."""
    app = FastAPI()
    app.add_exception_handler(DataError, data_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/boum")
    def boum() -> None:
        raise exception

    return TestClient(app, raise_server_exceptions=False)


def _data_error(sqlstate: str | None) -> DataError:
    orig = Exception("valeur refusée")
    orig.sqlstate = sqlstate  # type: ignore[attr-defined]
    return DataError("SELECT 1", {}, orig)


def test_une_valeur_refusee_par_le_driver_donne_422():
    assert _client_levant(_data_error(None)).get("/boum").status_code == 422


def test_une_erreur_venue_du_serveur_reste_en_500():
    assert _client_levant(_data_error("22003")).get("/boum").status_code == 500
