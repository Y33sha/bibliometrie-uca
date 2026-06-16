"""Tests purs de la substitution Zenodo concept→colonne (`compute_updates`).

Garde le contrat : concept normalisé en colonne, version source stashée sous `ZENODO_CONCEPT_DOI`, idempotence (repart du brut reconstruit), auto-cicatrisation (concept == version → restaure le brut).
"""

from application.pipeline.metadata_correction.correct_zenodo_concept import (
    ZENODO_CONCEPT_DOI,
    compute_updates,
)
from application.ports.pipeline.metadata_correction import DoiCorrectionUpdate, ZenodoConceptRow


def _row(id, doi, concept, raw_metadata=None) -> ZenodoConceptRow:
    return ZenodoConceptRow(id, doi, concept, raw_metadata or {})


def test_first_run_substitutes_concept_and_stashes_version():
    """Colonne = version, pas de sidecar : concept écrit en colonne, version stashée."""
    rows = [_row(1, "10.5281/zenodo.11", "10.5281/zenodo.10")]
    assert compute_updates(rows) == [
        DoiCorrectionUpdate(
            1,
            "10.5281/zenodo.10",
            {"doi": {"raw": "10.5281/zenodo.11", "corrected_by": ZENODO_CONCEPT_DOI}},
        )
    ]


def test_idempotent_when_already_substituted():
    """Colonne = concept, version déjà stashée : aucun changement."""
    rows = [
        _row(
            1,
            "10.5281/zenodo.10",
            "10.5281/zenodo.10",
            {"doi": {"raw": "10.5281/zenodo.11", "corrected_by": ZENODO_CONCEPT_DOI}},
        )
    ]
    assert compute_updates(rows) == []


def test_concept_normalized():
    """Le concept caché est normalisé (casse) avant écriture en colonne."""
    rows = [_row(1, "10.5281/zenodo.11", "10.5281/ZENODO.10")]
    assert compute_updates(rows)[0].doi == "10.5281/zenodo.10"


def test_non_versioned_concept_equals_version_no_correction():
    """Dépôt non versionné (concept == version) : pas de correction, colonne inchangée."""
    rows = [_row(1, "10.5281/zenodo.5", "10.5281/zenodo.5")]
    assert compute_updates(rows) == []


def test_self_heal_restores_raw_when_concept_now_equals_version():
    """Concept devenu == version : le DOI brut est restauré, le sidecar `doi` retiré."""
    rows = [
        _row(
            1,
            "10.5281/zenodo.10",
            "10.5281/zenodo.11",
            {"doi": {"raw": "10.5281/zenodo.11", "corrected_by": ZENODO_CONCEPT_DOI}},
        )
    ]
    assert compute_updates(rows) == [DoiCorrectionUpdate(1, "10.5281/zenodo.11", {})]


def test_invalid_concept_restores_raw():
    """Concept malformé : on ne substitue pas, le brut est restauré."""
    rows = [_row(1, "10.5281/zenodo.11", "   ")]
    assert compute_updates(rows) == []
