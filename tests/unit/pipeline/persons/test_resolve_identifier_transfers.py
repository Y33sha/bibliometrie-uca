"""Tests de l'arbitrage des conflits d'identifiant par le vote des groupes."""

import logging
from unittest.mock import ANY, MagicMock

from pipeline.transformation.persons import identifier_arbitration
from pipeline.transformation.persons.identifier_arbitration import (
    IdentifierConflict,
    resolve_identifier_transfers,
)

_ORCID = "0000-0002-1825-0097"
_OWNER, _OTHER, _THIRD = 1, 2, 3


def _resolve(monkeypatch, votes: dict[int, int], status: str = "pending"):
    """Arbitre un conflit : ORCID attribué à `_OWNER` avec le statut `status`, voix des groupes `votes`. Rend les compteurs, le dépôt simulé et les accès SQL simulés."""
    queries = MagicMock()
    queries.mark_identifier_contributions.return_value = 0
    monkeypatch.setattr(
        identifier_arbitration,
        "mark_identifier_contributions",
        queries.mark_identifier_contributions,
    )
    repo = MagicMock()
    repo.find_identifier.return_value.person_id = _OWNER
    result = resolve_identifier_transfers(
        MagicMock(),
        [IdentifierConflict("orcid", _ORCID, _OWNER, status, votes)],
        repo=repo,
        logger=logging.getLogger(__name__),
    )
    return result, repo, queries


def test_la_majorite_d_une_autre_personne_transfere(monkeypatch):
    result, repo, queries = _resolve(monkeypatch, {_OWNER: 1, _OTHER: 2})
    assert result["transferred"] == 1
    repo.find_identifier.return_value.transfer_to.assert_called_once_with(_OTHER, source=ANY)
    queries.mark_identifier_contributions.assert_called_once_with(ANY, "orcid", _ORCID, _OWNER)


def test_la_majorite_du_titulaire_ne_transfere_pas(monkeypatch):
    result, repo, queries = _resolve(monkeypatch, {_OWNER: 2, _OTHER: 1})
    assert result["transferred"] == 0
    repo.update_identifier.assert_not_called()


def test_l_egalite_ne_transfere_pas(monkeypatch):
    result, repo, queries = _resolve(monkeypatch, {_OWNER: 1, _OTHER: 2, _THIRD: 2})
    assert result["transferred"] == 0
    repo.update_identifier.assert_not_called()


def test_sans_voix_rien_ne_transfere(monkeypatch):
    result, _, _ = _resolve(monkeypatch, {_OWNER: 0, _OTHER: 0})
    assert result["transferred"] == 0


def test_un_titulaire_confirme_n_est_jamais_transfere(monkeypatch):
    """Un conflit confirmé par l'admin est tranché : il ne compte pas parmi les conflits à arbitrer."""
    result, repo, queries = _resolve(monkeypatch, {_OWNER: 0, _OTHER: 5}, status="confirmed")
    assert result == {"conflicts": 1, "pending": 0, "transferred": 0}
    repo.find_identifier.assert_not_called()
