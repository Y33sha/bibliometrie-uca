"""L'ordre des phases est cohérent : noms uniques."""

from pipeline.phases import PHASES
from pipeline.public import PHASE_ORDER


def test_l_ordre_public_suit_les_phases():
    assert tuple(phase.name for phase in PHASES) == PHASE_ORDER


def test_phases_uniques():
    assert len(PHASE_ORDER) == len(set(PHASE_ORDER))


def test_ordre_colonne_vertebrale():
    # Le moissonnage ouvre le pipeline, la normalisation précède les phases aval.
    assert PHASE_ORDER[0] == "harvest"
    assert PHASE_ORDER.index("normalize") < PHASE_ORDER.index("publications")


def test_les_enrichissements_ferment_la_sequence():
    """Les enrichissements sont les dernières phases : les omettre laisse une séquence continue."""
    extras = [phase.extra for phase in PHASES]

    assert extras == sorted(extras)
