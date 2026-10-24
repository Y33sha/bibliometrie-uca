"""Tests du consensus des porteurs d'identifiant et de la requalification des identifiants mal placés."""

from unittest.mock import ANY, MagicMock

from pipeline.transformation.persons import identifier_arbitration
from pipeline.transformation.persons.identifier_arbitration import (
    ContributorInformationIdentifier,
    MisplacedNeutralizations,
    compute_identifier_consensus,
    requalify_misplaced_identifiers,
)


def _install(monkeypatch, queries: MagicMock) -> None:
    """Branche les accès SQL de `identifier_arbitration` sur les attributs de `queries`."""
    for name in (
        "fetch_identifier_votes",
        "fetch_contributor_information_identifiers",
        "write_misplaced_neutralizations",
        "release_misplaced_groups",
        "PersonsStore",
    ):
        monkeypatch.setattr(identifier_arbitration, name, getattr(queries, name))


def test_consensus_retient_la_majorite_stricte(monkeypatch):
    votes = {"orcid": {"X": {"s dahbi": 3, "t dado": 1}, "Y": {"a b": 1, "c d": 1}}}
    queries = MagicMock()
    _install(monkeypatch, queries)
    queries.fetch_identifier_votes.side_effect = lambda conn, id_type: votes.get(id_type, {})
    assert compute_identifier_consensus(MagicMock()) == {("orcid", "X"): "s dahbi"}


def test_identite_contredisant_le_consensus_neutralisee_groupes_liberes_et_detachee(monkeypatch):
    information = {
        "orcid": [
            ContributorInformationIdentifier(1, "dahbi s", "X"),
            ContributorInformationIdentifier(2, "t dado", "X"),
        ]
    }
    queries = MagicMock()
    _install(monkeypatch, queries)
    queries.fetch_contributor_information_identifiers.side_effect = lambda conn, id_type: (
        information.get(id_type, [])
    )
    gained = {10: ["orcid"], 11: ["orcid"], 12: ["orcid"]}
    queries.write_misplaced_neutralizations.return_value = MisplacedNeutralizations(
        gained=gained, to_detach=[10]
    )
    queries.release_misplaced_groups.return_value = 2
    queries.PersonsStore.return_value.detach_source_contributions.return_value = 1

    result = requalify_misplaced_identifiers(MagicMock(), {("orcid", "X"): "s dahbi"})

    queries.write_misplaced_neutralizations.assert_called_once_with(ANY, {2: ["orcid"]})
    queries.release_misplaced_groups.assert_called_once_with(ANY, gained)
    queries.PersonsStore.return_value.detach_source_contributions.assert_called_once_with([10])
    assert result == {"neutralized": 3, "released_groups": 2, "detached": 1}
