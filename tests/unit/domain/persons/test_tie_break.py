"""Tests du départage des personnes candidates d'une forme de nom ambiguë."""

from domain.persons.contribution_matching import (
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    ContributionSkipReason,
)
from domain.persons.tie_break import ContributionContext, break_tie

_AMBIGUOUS = ContributionDecision(
    ContributionOutcome.SKIP,
    reason=ContributionSkipReason.AMBIGUOUS_NAME_FORM,
    candidates=frozenset({1, 2}),
)


def _context(publication_id=100, *, persons=(), laboratories=(), hal=(), serial=None, year=None):
    return ContributionContext(
        publication_id,
        frozenset(persons),
        frozenset(laboratories),
        frozenset(hal),
        serial,
        year,
    )


def _decided(context, profiles):
    decision = break_tie(_AMBIGUOUS, context, profiles)
    return decision.person_id, decision.reason


def test_un_coauteur_partage_designe_la_personne():
    profiles = {1: [_context(1, persons={7})], 2: [_context(2, persons={8})]}

    assert _decided(_context(persons={7}), profiles) == (1, ContributionMatchReason.COAUTHORS)


def test_quand_chaque_personne_partage_un_coauteur_deux_coauteurs_departagent():
    profiles = {1: [_context(1, persons={7, 9})], 2: [_context(2, persons={7})]}

    assert _decided(_context(persons={7, 9}), profiles) == (1, ContributionMatchReason.COAUTHORS)


def test_une_personne_candidate_presente_dans_la_publication_ne_compte_pas_comme_coauteur():
    """La personne 2, candidate et présente dans la publication, est coauteur habituel de la personne 1. Elle est écartée des coauteurs présents."""
    profiles = {1: [_context(1, persons={2})], 2: [_context(2, persons={1})]}

    assert _decided(_context(persons={2}), profiles) == (
        None,
        ContributionSkipReason.AMBIGUOUS_NAME_FORM,
    )


def test_l_ordre_des_indices_fait_passer_le_laboratoire_avant_la_revue():
    profiles = {
        1: [_context(1, laboratories={5})],
        2: [_context(2, serial=40)],
    }

    decided = _decided(_context(laboratories={5}, serial=40), profiles)

    assert decided == (1, ContributionMatchReason.LABORATORY)


def test_une_structure_hal_partagee_designe_la_personne():
    profiles = {1: [_context(1, hal={3})], 2: [_context(2, hal={4})]}

    assert _decided(_context(hal={3}), profiles) == (1, ContributionMatchReason.HAL_STRUCTURE)


def test_la_revue_partagee_designe_la_personne():
    profiles = {1: [_context(1, serial=40)], 2: [_context(2, serial=41)]}

    assert _decided(_context(serial=40), profiles) == (1, ContributionMatchReason.SERIAL)


def test_les_annees_d_activite_designent_la_personne():
    profiles = {1: [_context(1, year=2018)], 2: [_context(2, year=2005)]}

    assert _decided(_context(year=2020), profiles) == (1, ContributionMatchReason.ACTIVITY_YEARS)


def test_la_publication_decidee_est_exclue_des_profils():
    profiles = {1: [_context(100, laboratories={5})], 2: [_context(2)]}

    assert _decided(_context(laboratories={5}), profiles) == (
        None,
        ContributionSkipReason.AMBIGUOUS_NAME_FORM,
    )


def test_un_indice_partage_par_plusieurs_personnes_ne_decide_pas():
    profiles = {1: [_context(1, laboratories={5})], 2: [_context(2, laboratories={5})]}

    assert _decided(_context(laboratories={5}), profiles) == (
        None,
        ContributionSkipReason.AMBIGUOUS_NAME_FORM,
    )


def test_une_autre_decision_reste_inchangee():
    conflict = ContributionDecision(
        ContributionOutcome.SKIP,
        reason=ContributionSkipReason.NAME_CONFLICT,
        candidates=frozenset({1, 2}),
    )
    profiles = {1: [_context(1, laboratories={5})]}

    assert break_tie(conflict, _context(laboratories={5}), profiles) == conflict
