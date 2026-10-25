"""Router des sources (`/api/sources`) : libellés dans l'ordre d'affichage."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.sources.registry import ALL_SOURCES
from interfaces.api.routers import sources


def test_les_sources_et_leur_libelle_dans_l_ordre_d_affichage():
    app = FastAPI()
    app.include_router(sources.router)

    reponse = TestClient(app).get("/api/sources")

    assert reponse.status_code == 200
    assert [o["value"] for o in reponse.json()] == list(ALL_SOURCES)
    assert {"value": "theses", "label_fr": "theses.fr"} in reponse.json()
