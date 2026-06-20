"""Tests purs : corrections de DOI par cluster (version→concept, ouvrage/chapitre,
chapitre/chapitre) + `compute_updates`."""

from application.pipeline.metadata_correction.correct_by_cluster import compute_updates
from application.ports.pipeline.metadata_correction import DoiClusterRow, DoiCorrectionUpdate
from domain.source_publications.correction import (
    DoiClusterCase,
    DoiClusterDecision,
    DoiClusterMember,
    resolve_cluster_doi_corrections,
)


def _row(
    id, doc_type, doi, title="t", raw_metadata=None, raw_doi="10.1/x", concept_doi=None
) -> DoiClusterRow:
    return DoiClusterRow(id, doc_type, doi, title, raw_metadata or {}, raw_doi, concept_doi)


def _m(id, doc_type, title="t", concept_doi=None) -> DoiClusterMember:
    return DoiClusterMember(id, doc_type, title, concept_doi)


# ── domaine pur : version → concept (convergence) ────────────────────────


def test_version_group_all_converge_on_concept():
    # Un membre (datacite) porte le concept ; tous les membres du groupe convergent dessus.
    group = [_m(1, "dataset", concept_doi="10.5281/zenodo.1"), _m(2, "dataset")]
    assert resolve_cluster_doi_corrections(group) == [
        DoiClusterDecision(1, "10.5281/zenodo.1", DoiClusterCase.DATACITE_VERSION_TO_CONCEPT),
        DoiClusterDecision(2, "10.5281/zenodo.1", DoiClusterCase.DATACITE_VERSION_TO_CONCEPT),
    ]


def test_version_takes_precedence_over_book_chapter():
    # Improbable en pratique (disjoint), mais la convergence prime si un concept est présent.
    group = [_m(1, "book", concept_doi="10.5281/zenodo.1"), _m(2, "book_chapter")]
    cases = {d.case for d in resolve_cluster_doi_corrections(group)}
    assert cases == {DoiClusterCase.DATACITE_VERSION_TO_CONCEPT}


# ── domaine pur : ouvrage/chapitre (divergence) ──────────────────────────


def test_book_and_chapter_chapter_loses_doi():
    group = [_m(1, "book"), _m(2, "book_chapter")]
    assert resolve_cluster_doi_corrections(group) == [
        DoiClusterDecision(2, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE)
    ]


def test_only_book_no_correction():
    assert resolve_cluster_doi_corrections([_m(1, "book")]) == []


def test_article_sharing_book_doi_is_ignored():
    # Un article partageant par accident le DOI d'un ouvrage n'est pas touché ; le chapitre l'est.
    group = [_m(1, "book"), _m(2, "book_chapter"), _m(3, "article")]
    assert resolve_cluster_doi_corrections(group) == [
        DoiClusterDecision(2, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE)
    ]


# ── domaine pur : chapitre/chapitre (nettoyage + containment + strict) ────


def test_chapters_distinct_titles_all_lose_doi():
    group = [
        _m(1, "book_chapter", "geographie de l environnement"),
        _m(2, "book_chapter", "le monde a la une"),
    ]
    decisions = resolve_cluster_doi_corrections(group)
    assert {d.case for d in decisions} == {DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS}
    assert {d.id for d in decisions} == {1, 2}
    assert all(d.target_doi is None for d in decisions)


def test_chapters_same_title_no_correction():
    assert (
        resolve_cluster_doi_corrections(
            [_m(1, "book_chapter", "introduction"), _m(2, "book_chapter", "introduction")]
        )
        == []
    )


def test_chapters_chapter_number_prefix_is_same():
    g = [
        _m(1, "book_chapter", "chapitre 14 les limnosystemes"),
        _m(2, "book_chapter", "les limnosystemes"),
    ]
    assert resolve_cluster_doi_corrections(g) == []


def test_chapters_subtitle_truncation_is_same():
    g = [
        _m(1, "book_chapter", "contested concepts"),
        _m(2, "book_chapter", "contested concepts plutarch on common notions"),
    ]
    assert resolve_cluster_doi_corrections(g) == []


def test_chapters_typo_is_false_positive_left_to_admin():
    g = [
        _m(1, "book_chapter", "les effets thermomecaniques"),
        _m(2, "book_chapter", "les effets thermomecanqiues"),
    ]
    assert resolve_cluster_doi_corrections(g) != []  # déterministe, pas de fuzzy


# ── compute_updates (orchestration mécanique) ────────────────────────────


def test_version_doi_substituted_to_concept():
    # raw_doi = la version ; concept porté par le membre datacite → substitution + stash.
    datacite = _row(
        1,
        "dataset",
        "10.5281/zenodo.10",
        raw_doi="10.5281/zenodo.10",
        concept_doi="10.5281/zenodo.1",
    )
    hal = _row(2, "dataset", "10.5281/zenodo.10", raw_doi="10.5281/zenodo.10")
    updates = compute_updates([datacite, hal])
    assert {u.id for u in updates} == {1, 2}
    assert all(u.doi == "10.5281/zenodo.1" for u in updates)
    assert all(
        u.raw_metadata["doi"]
        == {"raw": "10.5281/zenodo.10", "corrected_by": "DATACITE_VERSION_TO_CONCEPT"}
        for u in updates
    )


def test_concept_equal_to_version_is_noop():
    # Dépôt non versionné (concept == version) : pas de substitution.
    row = _row(
        1, "dataset", "10.5281/zenodo.5", raw_doi="10.5281/zenodo.5", concept_doi="10.5281/zenodo.5"
    )
    assert compute_updates([row]) == []


def test_self_heals_when_concept_gone():
    # Déjà substituée mais le concept n'est plus dérivable (pas de membre datacite) → restaure la version.
    row = _row(
        1,
        "dataset",
        "10.5281/zenodo.1",
        raw_metadata={
            "doi": {"raw": "10.5281/zenodo.10", "corrected_by": "DATACITE_VERSION_TO_CONCEPT"}
        },
        raw_doi="10.5281/zenodo.10",
    )
    assert compute_updates([row]) == [DoiCorrectionUpdate(1, "10.5281/zenodo.10", {})]


def test_chapter_doi_nulled_book_untouched():
    book = _row(1, "book", "10.1/x")
    chapter = _row(2, "book_chapter", "10.1/x")
    assert compute_updates([book, chapter]) == [
        DoiCorrectionUpdate(
            2, None, {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}}
        )
    ]


def test_chapter_chapter_both_nulled():
    a = _row(1, "book_chapter", "10.1/x", title="premier chapitre distinct")
    b = _row(2, "book_chapter", "10.1/x", title="second chapitre autre")
    updates = compute_updates([a, b])
    assert {u.id for u in updates} == {1, 2}
    assert all(u.doi is None for u in updates)
    assert all(
        u.raw_metadata["doi"]["corrected_by"] == "CHAPITRES_TITRES_DIFFERENTS" for u in updates
    )


def test_idempotent_when_already_nulled():
    book = _row(1, "book", "10.1/x")
    chapter = _row(
        2,
        "book_chapter",
        None,
        raw_metadata={"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([book, chapter]) == []


def test_self_heals_when_book_gone():
    chapter = _row(
        2,
        "book_chapter",
        None,
        raw_metadata={"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([chapter]) == [DoiCorrectionUpdate(2, "10.1/x", {})]
