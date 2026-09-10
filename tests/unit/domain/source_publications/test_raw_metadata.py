"""Reconstruction de la vue aux valeurs source d'origine (`hydrate_raw_view`)."""

from dataclasses import dataclass

from domain.source_publications.raw_metadata import hydrate_raw_view, stash_entry


@dataclass(frozen=True)
class _Vue:
    doc_type: str | None
    doi: str | None


_VUE = _Vue(doc_type="article", doi="10.1/x")


def test_un_champ_corrige_reprend_sa_valeur_source():
    raw_metadata = {"doc_type": stash_entry("thesis", "THESIS_WITH_JOURNAL_TO_ARTICLE")}
    assert hydrate_raw_view(_VUE, raw_metadata) == _Vue(doc_type="thesis", doi="10.1/x")


def test_sans_raw_metadata_la_vue_est_rendue_telle_quelle():
    assert hydrate_raw_view(_VUE, None) is _VUE


def test_une_entree_qui_n_est_pas_un_stash_est_ignoree():
    assert hydrate_raw_view(_VUE, {"doc_type": "thesis"}) is _VUE


def test_une_entree_sans_valeur_source_est_ignoree():
    assert hydrate_raw_view(_VUE, {"doc_type": {"corrected_by": "regle"}}) is _VUE


def test_un_champ_absent_de_la_vue_est_ignore():
    assert hydrate_raw_view(_VUE, {"journal_id": stash_entry(42, "regle")}) is _VUE
