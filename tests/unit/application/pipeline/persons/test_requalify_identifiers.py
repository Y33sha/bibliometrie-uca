"""Tests du consensus des porteurs d'identifiant et de la requalification des identifiants mal placés."""

from unittest.mock import ANY, MagicMock

from application.pipeline.persons.requalify_identifiers import (
    compute_identifier_consensus,
    requalify_misplaced_identifiers,
)
from application.ports.pipeline.persons.matching import (
    IdentityIdentifier,
    MisplacedNeutralizations,
)


def test_consensus_retient_la_majorite_stricte():
    votes = {"orcid": {"X": {"s dahbi": 3, "t dado": 1}, "Y": {"a b": 1, "c d": 1}}}
    queries = MagicMock()
    queries.fetch_identifier_votes.side_effect = lambda conn, id_type: votes.get(id_type, {})
    assert compute_identifier_consensus(MagicMock(), queries) == {("orcid", "X"): "s dahbi"}


def test_identite_contredisant_le_consensus_neutralisee_et_detachee():
    identities = {
        "orcid": [IdentityIdentifier(1, "dahbi s", "X"), IdentityIdentifier(2, "t dado", "X")]
    }
    queries = MagicMock()
    queries.fetch_identity_identifiers.side_effect = lambda conn, id_type: identities.get(
        id_type, []
    )
    queries.write_misplaced_neutralizations.return_value = MisplacedNeutralizations(
        neutralized=3, to_detach=[10]
    )
    queries.detach_authorships.return_value = 1

    result = requalify_misplaced_identifiers(MagicMock(), {("orcid", "X"): "s dahbi"}, queries)

    queries.write_misplaced_neutralizations.assert_called_once_with(ANY, {2: ["orcid"]})
    queries.detach_authorships.assert_called_once_with(ANY, [10])
    assert result == {"neutralized": 3, "detached": 1}
