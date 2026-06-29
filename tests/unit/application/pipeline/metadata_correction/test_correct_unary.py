"""Tests purs de `compute_update` : mapping source→canonique puis correction unaire idempotente."""

from application.pipeline.metadata_correction.correct_unary import (
    DOC_TYPE_MAP_MARKER,
    compute_update,
    tally_corrections,
)
from application.ports.pipeline.metadata_correction import CorrectionUpdate
from domain.source_publications.correction import SourcePublicationForCorrection
from domain.source_publications.raw_metadata import stash_entry


def test_tally_corrections_exclut_le_mapping_doc_type():
    updates = [
        # mapping de vocabulaire seul → pas une correction
        CorrectionUpdate(
            1, "article", None, {}, {"doc_type": stash_entry("ART", DOC_TYPE_MAP_MARKER)}
        ),
        # règle réelle sur doc_type
        CorrectionUpdate(
            2,
            "thesis",
            None,
            {},
            {"doc_type": stash_entry("article", "THESIS_WITH_JOURNAL_TO_ARTICLE")},
        ),
        # deux champs corrigés sur une même SP → 1 SP, 2 déclenchements
        CorrectionUpdate(
            3,
            "media",
            "green",
            {},
            {
                "doc_type": stash_entry("article", "JOURNAL_TYPE_MEDIA_TO_MEDIA"),
                "oa_status": stash_entry("closed", "EMBARGO_EXPIRED_TO_GREEN"),
            },
        ),
    ]
    corrected, rule_counts = tally_corrections(updates)
    assert corrected == 2  # SP 1 = mapping seul (exclue) ; SP 2 et 3 corrigées
    assert rule_counts == {
        "THESIS_WITH_JOURNAL_TO_ARTICLE": 1,
        "JOURNAL_TYPE_MEDIA_TO_MEDIA": 1,
        "EMBARGO_EXPIRED_TO_GREEN": 1,
    }


def _sp(**overrides: object) -> SourcePublicationForCorrection:
    base: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W1",
        "title": "Un titre quelconque",
        "pub_year": 2020,
        "doc_type": "article",
        "doi": None,
        "journal_id": None,
        "oa_status": None,
        "container_title": None,
        "language": None,
        "urls": None,
        "external_ids": {},
        "journal_type": None,
        "oa_model": None,
        "apc_amount": None,
        "raw_metadata": {},
        "embargo_expired": False,
        "declares_preprint": False,
    }
    base.update(overrides)
    return SourcePublicationForCorrection(**base)  # type: ignore[arg-type]


def test_no_rule_no_mapping_change_returns_none():
    # OpenAlex 'article' → map = 'article' (inchangé), aucune règle → no-op.
    assert compute_update(_sp(doc_type="article")) is None


def test_hal_code_mapped_to_canonical_with_marker():
    # ART (HAL) → 'article' par mapping seul, sans règle : marqueur DOC_TYPE_MAP.
    upd = compute_update(_sp(source="hal", doc_type="ART"))
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata == {"doc_type": {"raw": "ART", "corrected_by": "DOC_TYPE_MAP"}}


def test_thesis_with_journal_id_and_publisher_doi_is_mistyped_article():
    # Mistype OpenAlex/ScanR : un article typé thèse, rattaché à un journal, avec un DOI d'éditeur
    # (préfixe ≠ registre de thèses) → article.
    upd = compute_update(_sp(doc_type="thesis", journal_id=42, doi="10.1016/j.ex.2020.01.001"))
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata == {
        "doc_type": {"raw": "thesis", "corrected_by": "THESIS_WITH_JOURNAL_TO_ARTICLE"}
    }


def test_thesis_with_journal_id_but_thesis_registry_doi_stays_thesis():
    # DOI ABES (registre des thèses FR) : c'est le DOI propre de la thèse, le journal_id est parasite
    # (conflation thèse↔version publiée) → le type reste thèse, pas de correction.
    assert compute_update(_sp(doc_type="thesis", journal_id=42, doi="10.70675/abc123")) is None


def test_thesis_with_journal_id_no_doi_stays_thesis():
    # Sans DOI, rien ne distingue le mistype de la conflation : on ne bascule pas, le type reste thèse.
    assert compute_update(_sp(doc_type="thesis", journal_id=42, doi=None)) is None


def test_real_thesis_without_journal_id_untouched():
    assert compute_update(_sp(doc_type="thesis", journal_id=None)) is None


def test_thesis_to_article_strips_dissertation_keys():
    # Conflation : la SP corrigée thèse→article perd le NNT et les hal_id tel-/dumas-,
    # garde les autres hal_id (article) et les autres clés. Brut stashé pour réversibilité.
    upd = compute_update(
        _sp(
            doc_type="thesis",
            journal_id=42,
            doi="10.1016/j.ex.2020.01.001",
            external_ids={"nnt": "2020X", "hal_id": ["tel-01", "hal-99"], "pmid": "123"},
        )
    )
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.external_ids == {"hal_id": ["hal-99"], "pmid": "123"}
    assert upd.raw_metadata["external_ids"] == {
        "raw": {"nnt": "2020X", "hal_id": ["tel-01", "hal-99"], "pmid": "123"},
        "corrected_by": "THESIS_WITH_JOURNAL_TO_ARTICLE",
    }


def test_thesis_to_article_without_dissertation_keys_leaves_external_ids():
    # Mistype pur (pas de clé-thèse) : external_ids inchangé, pas de stash.
    upd = compute_update(
        _sp(
            doc_type="thesis",
            journal_id=42,
            doi="10.1016/j.ex.2020.01.001",
            external_ids={"pmid": "123"},
        )
    )
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.external_ids == {"pmid": "123"}
    assert "external_ids" not in upd.raw_metadata


def test_journal_id_wins_over_theses_fr_url_conflation():
    # Conflation thèse↔article : une SP theses.fr AVEC un journal_id ET un DOI d'éditeur → article
    # (`journal_id_present: False` garde la règle URL ; `doi_prefix_not_in` distingue l'article
    # publié — DOI éditeur — d'une vraie thèse à DOI ABES).
    upd = compute_update(
        _sp(
            doc_type="thesis",
            journal_id=42,
            doi="10.1016/j.ex.2020.01.001",
            urls=["https://theses.fr/2020X"],
        )
    )
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata["doc_type"]["corrected_by"] == "THESIS_WITH_JOURNAL_TO_ARTICLE"


def test_hal_code_mapped_then_rule_corrects():
    # ART → 'article' (map) → journal media → 'media' (règle). map-then-correct chaîné ;
    # corrected_by = la règle (pas le marqueur), raw = la valeur source ART.
    upd = compute_update(_sp(source="hal", doc_type="ART", journal_type="media"))
    assert upd is not None
    assert upd.doc_type == "media"
    assert upd.raw_metadata == {
        "doc_type": {"raw": "ART", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
    }


def test_theses_fr_url_corrects_doc_type_and_stashes_raw():
    upd = compute_update(_sp(doc_type="article", urls=["https://theses.fr/2020ABCD"]))
    assert upd is not None
    assert upd.doc_type == "thesis"
    assert upd.raw_metadata == {
        "doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}
    }


def test_already_corrected_is_idempotent_noop():
    sp = _sp(
        doc_type="thesis",
        urls=["https://theses.fr/2020ABCD"],
        raw_metadata={"doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}},
    )
    assert compute_update(sp) is None


def test_self_heals_when_rule_no_longer_applies():
    # doc_type figé à 'media' par une règle journal, mais le journal n'est plus 'media' :
    # la correction doit être défaite, le brut canonique 'article' restauré.
    sp = _sp(
        doc_type="media",
        journal_type=None,
        raw_metadata={
            "doc_type": {"raw": "article", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
        },
    )
    upd = compute_update(sp)
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata == {}


def test_expired_embargo_promotes_oa_status_to_green():
    # oa_status `embargoed` + embargo expiré (calculé au fetch) → `green`, brut stashé.
    upd = compute_update(_sp(oa_status="embargoed", embargo_expired=True))
    assert upd is not None
    assert upd.oa_status == "green"
    assert upd.raw_metadata["oa_status"] == {
        "raw": "embargoed",
        "corrected_by": "EMBARGO_EXPIRED_TO_GREEN",
    }


def test_active_embargo_oa_status_untouched():
    # Embargo non expiré → pas de promotion, no-op.
    assert compute_update(_sp(oa_status="embargoed", embargo_expired=False)) is None


def test_null_doc_type_left_null_when_no_rule():
    # Pas de mapping forcé pour None (pas de représentation à traduire) ; aucune règle → no-op.
    assert compute_update(_sp(doc_type=None)) is None


def test_preserves_unmanaged_raw_metadata_keys():
    # La clé `doi` (gérée par la sous-étape relationnelle) doit survivre à la passe unaire.
    sp = _sp(
        doc_type="article",
        urls=["https://theses.fr/2020ABCD"],
        raw_metadata={"doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    upd = compute_update(sp)
    assert upd is not None
    assert upd.raw_metadata == {
        "doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"},
        "doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"},
    }
