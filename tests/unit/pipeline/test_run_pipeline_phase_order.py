"""Ordre des phases : prérequis de chaque phase."""

from pipeline import run as run_pipeline


def test_le_referentiel_des_doi_suit_la_normalisation_et_precede_l_edition_et_la_correction():
    """L'agence et l'existence des DOI normalisés dans le run sont connues avant que `publishing` rattache les préfixes à leur éditeur, et que la correction retire les DOI inconnus de doi.org."""
    names = run_pipeline.PHASE_NAMES
    assert (
        names.index("normalize")
        < names.index("dois")
        < names.index("publishing")
        < names.index("metadata_correction")
    )
