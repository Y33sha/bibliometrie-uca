"""Tests purs : cible du DOI d'une forme secondaire (`doi_target`, `compute_doi_targets`)."""

from domain.source_records.metadata_correction.shared_doi import (
    DoiTarget,
    DoiTargetRule,
    SecondaryFormDeclaration,
    doi_target,
)
from pipeline.transformation.publications.correction.correction_store import SecondaryFormRow
from pipeline.transformation.publications.correction.doi_targets import compute_doi_targets

_VERSION = DoiTargetRule.DATACITE_VERSION_TO_CONCEPT
_VARIANT = DoiTargetRule.DATACITE_VARIANT_TO_PRIMARY
_PIECE = DoiTargetRule.DATACITE_PACKAGE_PIECE


def _cible(doi, target_doi, rule, doc_type="dataset"):
    return doi_target([SecondaryFormDeclaration(1, doc_type, target_doi, rule)], doi=doi)


def test_version_du_meme_registrant_a_pour_cible_son_concept():
    assert _cible("10.5281/zenodo.10", "10.5281/zenodo.1", _VERSION) == DoiTarget(
        "10.5281/zenodo.10", "10.5281/zenodo.1", _VERSION
    )


def test_forme_secondaire_d_elle_meme_sans_cible():
    """Un dépôt non versionné déclare son propre DOI comme concept."""
    assert _cible("10.5281/zenodo.5", "10.5281/zenodo.5", _VERSION) is None


def test_version_d_un_autre_prefixe_reste_distincte():
    """Un preprint arXiv déclare `IsVersionOf` vers l'article publié : deux œuvres, pas une."""
    assert (
        _cible("10.48550/arxiv.2210.12000", "10.1007/jhep07(2023)066", _VERSION, "article") is None
    )


def test_copie_de_l_article_d_un_autre_prefixe_a_pour_cible_l_article():
    """Une copie déposée à RWTH déclare `IsVariantFormOf` vers l'article publié : une seule œuvre."""
    target = _cible("10.18154/rwth-2022-02923", "10.1103/physrevd.105.012010", _VARIANT, "article")
    assert target is not None and target.target_doi == "10.1103/physrevd.105.012010"


def test_copie_de_preprint_d_un_autre_prefixe_reste_distincte():
    """Un working paper déposé au DESY déclare `IsVariantFormOf` vers l'article publié : deux œuvres."""
    assert (
        _cible("10.3204/pubdb-2017-13318", "10.1140/epjc/s10052-017-5315-6", _VARIANT, "preprint")
        is None
    )


def test_copie_de_preprint_du_meme_prefixe_a_une_cible():
    assert _cible("10.5281/zenodo.2", "10.5281/zenodo.1", _VARIANT, "preprint") is not None


def test_piece_de_dataset_a_pour_cible_son_parent_quel_que_soit_le_prefixe():
    """Une pièce a pour cible son dataset parent, dont le DOI prend souvent une autre forme."""
    target = _cible("10.15454/fichier", "10.1594/pangaea.1", _PIECE)
    assert target == DoiTarget("10.15454/fichier", "10.1594/pangaea.1", _PIECE)


def test_la_premiere_declaration_de_meme_oeuvre_donne_la_cible():
    declarations = [
        SecondaryFormDeclaration(1, "article", "10.1007/autre", _VERSION),
        SecondaryFormDeclaration(2, "dataset", "10.5281/zenodo.1", _VERSION),
    ]
    target = doi_target(declarations, doi="10.5281/zenodo.10")
    assert target is not None and target.target_doi == "10.5281/zenodo.1"


def test_compute_doi_targets_regroupe_les_declarations_par_doi():
    rows = [
        SecondaryFormRow(
            "10.5281/zenodo.10",
            SecondaryFormDeclaration(1, "dataset", "10.5281/zenodo.1", _VERSION),
        ),
        SecondaryFormRow(
            "10.48550/arxiv.1", SecondaryFormDeclaration(2, "article", "10.1007/x", _VERSION)
        ),
    ]
    assert compute_doi_targets(rows) == [
        DoiTarget("10.5281/zenodo.10", "10.5281/zenodo.1", _VERSION)
    ]
