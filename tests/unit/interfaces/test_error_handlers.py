"""Les gestionnaires d'erreur de l'API rendent le code attendu, et rien d'autre.

Ils décident de ce qu'un appelant apprend d'un échec : un refus d'autorisation doit se lire 401 et non 500, et une erreur imprévue ne doit rendre qu'un message générique — la trace part au journal, jamais dans la réponse.

Les gestionnaires sont éprouvés directement plutôt qu'à travers un point d'entrée : ils reçoivent une exception et une requête, et rien de ce qu'ils font ne dépend du chemin par lequel l'exception est arrivée.
"""

import json

import pytest
from starlette.requests import Request

from domain.errors import (
    BlockingJournal,
    ConflictError,
    DomainError,
    PublisherMergeBlockedError,
    UnauthorizedError,
)
from interfaces.api.app import (
    conflict_handler,
    domain_error_handler,
    publisher_merge_blocked_handler,
    unauthorized_handler,
    unhandled_exception_handler,
)


def _requete() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/x", "headers": []})


def _corps(reponse) -> dict:
    return json.loads(reponse.body)


@pytest.mark.asyncio
async def test_acces_refuse_donne_401():
    reponse = await unauthorized_handler(_requete(), UnauthorizedError("session invalide"))
    assert reponse.status_code == 401
    assert _corps(reponse) == {"detail": "session invalide"}


@pytest.mark.asyncio
async def test_conflit_donne_409():
    reponse = await conflict_handler(_requete(), ConflictError("déjà rattaché"))
    assert reponse.status_code == 409
    assert _corps(reponse) == {"detail": "déjà rattaché"}


@pytest.mark.asyncio
async def test_erreur_de_domaine_non_specialisee_donne_400():
    reponse = await domain_error_handler(_requete(), DomainError("règle métier"))
    assert reponse.status_code == 400
    assert _corps(reponse) == {"detail": "règle métier"}


@pytest.mark.asyncio
async def test_fusion_editeurs_bloquee_enumere_les_paires():
    bloquante = BlockingJournal(
        target_journal_id=1,
        target_title="Nature",
        source_journal_id=2,
        source_title="Nature",
        reason="ISSN différents",
    )
    reponse = await publisher_merge_blocked_handler(
        _requete(), PublisherMergeBlockedError([bloquante])
    )
    assert reponse.status_code == 409
    corps = _corps(reponse)
    assert len(corps["blocking_journals"]) == 1
    assert corps["blocking_journals"][0]["reason"] == "ISSN différents"


@pytest.mark.asyncio
async def test_erreur_imprevue_ne_rend_pas_la_trace(caplog):
    """Le 500 porte un message fixe ; le détail de l'échec reste au journal."""
    reponse = await unhandled_exception_handler(_requete(), RuntimeError("mot de passe = hunter2"))
    assert reponse.status_code == 500
    assert _corps(reponse) == {"detail": "Erreur interne du serveur"}
    assert "hunter2" not in reponse.body.decode()
