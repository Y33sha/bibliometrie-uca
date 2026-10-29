"""Les gestionnaires d'erreur de l'API renvoient le code attendu, et rien d'autre.

Ils décident de ce qu'un appelant apprend d'un échec : un conflit donne 409, et une erreur imprévue donne seulement un message générique ; la trace part au journal.

Les gestionnaires sont testés directement : ils reçoivent une exception et une requête, et leur comportement est indépendant de la route qui a levé l'exception.
"""

import json

import pytest
from starlette.requests import Request

from domain.errors import (
    BlockingSerial,
    ConflictError,
    DomainError,
    PublisherMergeBlockedError,
)
from interfaces.api.app import (
    conflict_handler,
    domain_error_handler,
    publisher_merge_blocked_handler,
    unhandled_exception_handler,
)


def _requete() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/x", "headers": []})


def _corps(reponse) -> dict:
    return json.loads(reponse.body)


@pytest.mark.asyncio
async def test_conflit_donne_409():
    reponse = await conflict_handler(_requete(), ConflictError("déjà rattaché"))
    assert reponse.status_code == 409
    assert _corps(reponse) == {"detail": "déjà rattaché"}


@pytest.mark.asyncio
async def test_erreur_de_domaine_non_specialisee_donne_422():
    reponse = await domain_error_handler(_requete(), DomainError("règle métier"))
    assert reponse.status_code == 422
    assert _corps(reponse) == {"detail": "règle métier"}


@pytest.mark.asyncio
async def test_fusion_editeurs_bloquee_enumere_les_paires():
    bloquante = BlockingSerial(
        target_serial_id=1,
        target_title="Nature",
        source_serial_id=2,
        source_title="Nature",
        reason="ISSN différents",
    )
    reponse = await publisher_merge_blocked_handler(
        _requete(), PublisherMergeBlockedError([bloquante])
    )
    assert reponse.status_code == 409
    corps = _corps(reponse)
    assert len(corps["blocking_serials"]) == 1
    assert corps["blocking_serials"][0]["reason"] == "ISSN différents"


@pytest.mark.asyncio
async def test_erreur_imprevue_ne_rend_pas_la_trace(caplog):
    """Le 500 contient un message fixe, sans le détail de l'échec."""
    reponse = await unhandled_exception_handler(_requete(), RuntimeError("mot de passe = hunter2"))
    assert reponse.status_code == 500
    assert _corps(reponse) == {"detail": "Erreur interne du serveur"}
    assert "hunter2" not in reponse.body.decode()
