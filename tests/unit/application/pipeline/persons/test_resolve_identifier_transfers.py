"""Tests de l'arbitrage des conflits d'identifiant par consensus des porteurs."""

import logging
from unittest.mock import MagicMock

from application.pipeline.persons.resolve_identifier_transfers import (
    resolve_identifier_transfers,
)
from application.services.persons.core import IdentifierConflict
from domain.persons.matching import PersonNameForms

_ORCID = "0000-0001-2345-6789"
_OWNER, _CANDIDATE = 1, 2


def _transferred(votes: dict[str, int]) -> int:
    """Nombre de transferts pour un conflit : ORCID attribué en `pending` à Dupont, porté par une signature d'Aubert."""
    queries = MagicMock()
    queries.fetch_identifier_votes.return_value = {_ORCID: votes}
    queries.fetch_person_name_forms.return_value = {
        _OWNER: PersonNameForms("dupont", "jean", []),
        _CANDIDATE: PersonNameForms("aubert", "pierre", []),
    }
    queries.null_identifier_signatures.return_value = 0
    repo = MagicMock()
    repo.find_identifier.return_value.person_id = _OWNER
    result = resolve_identifier_transfers(
        MagicMock(),
        [IdentifierConflict("orcid", _ORCID, _CANDIDATE, _OWNER, "pending")],
        queries=queries,
        repo=repo,
        logger=logging.getLogger(__name__),
    )
    return result["transferred"]


def test_consensus_du_candidat_transfere():
    assert _transferred({"aubert p": 2, "dupont j": 1}) == 1


def test_une_voix_unanime_transfere():
    assert _transferred({"aubert p": 1}) == 1


def test_egalite_ne_transfere_pas():
    """Le nom du candidat précède celui du propriétaire dans l'ordre alphabétique : une égalité reste sans consensus."""
    assert _transferred({"aubert p": 1, "dupont j": 1}) == 0
