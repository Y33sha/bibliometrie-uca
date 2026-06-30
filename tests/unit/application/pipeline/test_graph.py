"""L'ordre des phases est cohérent : noms uniques."""

from application.pipeline.graph import PHASE_ORDER


def test_phases_uniques():
    assert len(PHASE_ORDER) == len(set(PHASE_ORDER))


def test_ordre_colonne_vertebrale():
    # L'extraction ouvre le pipeline, la normalisation précède les phases aval.
    assert PHASE_ORDER[0] == "extract"
    assert PHASE_ORDER.index("normalize") < PHASE_ORDER.index("publications")
