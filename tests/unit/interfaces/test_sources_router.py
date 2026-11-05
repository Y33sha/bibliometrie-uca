"""Routeur des sources (`/api/sources`) : sources et libellés dans l'ordre d'affichage, sources des identifiants de structure."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.sources.registry import STRUCTURE_API_SOURCES, Source
from interfaces.api.routers import sources


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(sources.router)
    return TestClient(app)


def test_les_sources_et_leur_libelle_dans_l_ordre_d_affichage():
    reponse = _client().get("/api/sources")

    assert reponse.status_code == 200
    assert [o["value"] for o in reponse.json()] == list(Source)
    assert {"value": "theses", "label_fr": "theses.fr"} in reponse.json()


def test_les_sources_des_identifiants_de_structure_et_leur_libelle():
    reponse = _client().get("/api/sources/structure-ids")

    assert reponse.status_code == 200
    assert [o["value"] for o in reponse.json()] == list(STRUCTURE_API_SOURCES)
    assert {
        "value": "scanr_patents",
        "label_fr": "ScanR brevets (Paysage des déposants)",
    } in reponse.json()
