"""L'ordre des phases est cohérent : noms uniques."""

from application.pipeline.phase_order import EXTRA_PHASES, PHASE_ORDER


def test_phases_uniques():
    assert len(PHASE_ORDER) == len(set(PHASE_ORDER))


def test_ordre_colonne_vertebrale():
    # L'extraction ouvre le pipeline, la normalisation précède les phases aval.
    assert PHASE_ORDER[0] == "extract"
    assert PHASE_ORDER.index("normalize") < PHASE_ORDER.index("publications")


def test_les_enrichissements_ferment_la_sequence():
    """Les omettre ne coupe pas la séquence en deux : ils sont les derniers."""
    rangs = sorted(PHASE_ORDER.index(p) for p in EXTRA_PHASES)

    assert rangs == list(range(len(PHASE_ORDER) - len(EXTRA_PHASES), len(PHASE_ORDER)))
