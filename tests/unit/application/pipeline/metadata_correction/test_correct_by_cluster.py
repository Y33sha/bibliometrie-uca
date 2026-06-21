"""Tests purs : corrections de DOI par cluster (convergence même-œuvre, ouvrage/chapitre,
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
    id,
    doc_type,
    doi,
    title="t",
    raw_metadata=None,
    raw_doi="10.1/x",
    canonical_doi=None,
    same_work_case=None,
) -> DoiClusterRow:
    return DoiClusterRow(
        id, doc_type, doi, title, raw_metadata or {}, raw_doi, canonical_doi, same_work_case
    )


def _m(id, doc_type, title="t", canonical_doi=None, same_work_case=None) -> DoiClusterMember:
    return DoiClusterMember(id, doc_type, title, canonical_doi, same_work_case)


# ── domaine pur : convergence même-œuvre ─────────────────────────────────


def test_same_work_all_converge_on_canonical():
    # Un membre (datacite) porte le DOI canonique + son cas ; tous convergent dessus.
    group = [
        _m(
            1,
            "dataset",
            canonical_doi="10.5281/zenodo.1",
            same_work_case="DATACITE_VERSION_TO_CONCEPT",
        ),
        _m(2, "dataset"),
    ]
    assert resolve_cluster_doi_corrections(group) == [
        DoiClusterDecision(1, "10.5281/zenodo.1", DoiClusterCase.DATACITE_VERSION_TO_CONCEPT),
        DoiClusterDecision(2, "10.5281/zenodo.1", DoiClusterCase.DATACITE_VERSION_TO_CONCEPT),
    ]


def test_same_work_carries_its_case():
    # Le cas porté par le membre est restitué (variante, pièce de package…).
    for case in ("DATACITE_VARIANT_TO_PRIMARY", "DATACITE_PACKAGE_PIECE"):
        group = [_m(1, "dataset", canonical_doi="10.9/canon", same_work_case=case)]
        assert resolve_cluster_doi_corrections(group) == [
            DoiClusterDecision(1, "10.9/canon", DoiClusterCase(case))
        ]


def test_same_work_takes_precedence_over_book_chapter():
    group = [
        _m(
            1,
            "book",
            canonical_doi="10.5281/zenodo.1",
            same_work_case="DATACITE_VERSION_TO_CONCEPT",
        ),
        _m(2, "book_chapter"),
    ]
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
    # raw_doi = la version ; canonique porté par le membre datacite → substitution + stash.
    datacite = _row(
        1,
        "dataset",
        "10.5281/zenodo.10",
        raw_doi="10.5281/zenodo.10",
        canonical_doi="10.5281/zenodo.1",
        same_work_case="DATACITE_VERSION_TO_CONCEPT",
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


def test_variant_substituted_to_primary():
    # Copie repository → version publiée, provenance DATACITE_VARIANT_TO_PRIMARY.
    row = _row(
        1,
        "article",
        "10.18154/rwth-1",
        raw_doi="10.18154/rwth-1",
        canonical_doi="10.1103/published",
        same_work_case="DATACITE_VARIANT_TO_PRIMARY",
    )
    assert compute_updates([row]) == [
        DoiCorrectionUpdate(
            1,
            "10.1103/published",
            {"doi": {"raw": "10.18154/rwth-1", "corrected_by": "DATACITE_VARIANT_TO_PRIMARY"}},
        )
    ]


def test_package_piece_substituted_to_parent():
    row = _row(
        1,
        "dataset",
        "10.15454/abc/file1",
        raw_doi="10.15454/abc/file1",
        canonical_doi="10.15454/abc",
        same_work_case="DATACITE_PACKAGE_PIECE",
    )
    assert compute_updates([row]) == [
        DoiCorrectionUpdate(
            1,
            "10.15454/abc",
            {"doi": {"raw": "10.15454/abc/file1", "corrected_by": "DATACITE_PACKAGE_PIECE"}},
        )
    ]


def test_concept_equal_to_canonical_is_noop():
    # Dépôt non versionné (canonique == DOI brut) : pas de substitution.
    row = _row(
        1,
        "dataset",
        "10.5281/zenodo.5",
        raw_doi="10.5281/zenodo.5",
        canonical_doi="10.5281/zenodo.5",
        same_work_case="DATACITE_VERSION_TO_CONCEPT",
    )
    assert compute_updates([row]) == []


def test_self_heals_when_canonical_gone():
    # Déjà substituée mais le canonique n'est plus dérivable → restaure le DOI brut.
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
