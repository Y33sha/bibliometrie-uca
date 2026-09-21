"""Tests purs de `compute_update` : mapping source→canonique puis correction unaire idempotente."""

import logging
from unittest.mock import MagicMock

from application.pipeline.metadata_correction.correct_unary import (
    DOC_TYPE_MAP_MARKER,
    LANGUAGE_MAP_MARKER,
    compute_update,
    run,
    tally_corrections,
)
from application.ports.pipeline.metadata_correction import CorrectionUpdate, UnaryCorrectionRow
from domain.source_publications.raw_metadata import stash_entry

# Formes du référentiel des langues, chacune associée au code de sa langue.
_FORMS = {"en": "en", "eng": "en", "english": "en", "fr": "fr", "fra": "fr"}


def _update(sp: UnaryCorrectionRow) -> CorrectionUpdate | None:
    return compute_update(sp, _FORMS)


def test_tally_corrections_exclut_les_traductions_de_vocabulaire():
    updates = [
        # mapping de vocabulaire seul → pas une correction
        CorrectionUpdate(
            1, "article", None, None, {}, {"doc_type": stash_entry("ART", DOC_TYPE_MAP_MARKER)}
        ),
        # langue ramenée au référentiel → pas une correction
        CorrectionUpdate(
            4,
            "article",
            None,
            "en",
            {},
            {"language": stash_entry("English", LANGUAGE_MAP_MARKER)},
        ),
        # règle réelle sur doc_type
        CorrectionUpdate(
            2,
            "thesis",
            None,
            None,
            {},
            {"doc_type": stash_entry("article", "THESIS_WITH_JOURNAL_TO_ARTICLE")},
        ),
        # deux champs corrigés sur une même SP → 1 SP, 2 déclenchements
        CorrectionUpdate(
            3,
            "media",
            "green",
            None,
            {},
            {
                "doc_type": stash_entry("article", "JOURNAL_TYPE_MEDIA_TO_MEDIA"),
                "oa_status": stash_entry("closed", "EMBARGO_EXPIRED_TO_GREEN"),
            },
        ),
    ]
    corrected, rule_counts = tally_corrections(updates)
    assert corrected == 2  # SP 1 et 4 = traductions seules (exclues) ; SP 2 et 3 corrigées
    assert rule_counts == {
        "THESIS_WITH_JOURNAL_TO_ARTICLE": 1,
        "JOURNAL_TYPE_MEDIA_TO_MEDIA": 1,
        "EMBARGO_EXPIRED_TO_GREEN": 1,
    }


def _sp(**overrides: object) -> UnaryCorrectionRow:
    base: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "title": "Un titre quelconque",
        "doc_type": "article",
        "doi": None,
        "journal_id": None,
        "oa_status": None,
        "language": None,
        "urls": None,
        "external_ids": {},
        "journal_type": None,
        "oa_model": None,
        "raw_metadata": {},
        "embargo_expired": False,
        "self_declared_preprint": False,
        "declares_conference": False,
        "registrant_publisher_type": None,
        "in_proceedings_volume": False,
    }
    base.update(overrides)
    return UnaryCorrectionRow(**base)  # type: ignore[arg-type]


def test_no_rule_no_mapping_change_returns_none():
    # OpenAlex 'article' → map = 'article' (inchangé), aucune règle → no-op.
    assert _update(_sp(doc_type="article")) is None


def test_hal_code_mapped_to_canonical_with_marker():
    # ART (HAL) → 'article' par mapping seul, sans règle : marqueur DOC_TYPE_MAP.
    upd = _update(_sp(source="hal", doc_type="ART"))
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata == {"doc_type": {"raw": "ART", "corrected_by": "DOC_TYPE_MAP"}}


def test_thesis_with_journal_id_and_publisher_doi_is_mistyped_article():
    # Mistype OpenAlex/ScanR : un article typé thèse, rattaché à un journal, avec un DOI d'éditeur
    # (préfixe ≠ registre de thèses) → article.
    upd = _update(_sp(doc_type="thesis", journal_id=42, doi="10.1016/j.ex.2020.01.001"))
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata == {
        "doc_type": {"raw": "thesis", "corrected_by": "THESIS_WITH_JOURNAL_TO_ARTICLE"}
    }


def test_thesis_with_journal_id_but_thesis_registry_doi_stays_thesis():
    # DOI ABES (registre des thèses FR) : c'est le DOI propre de la thèse, le journal_id est parasite
    # (conflation thèse↔version publiée) → le type reste thèse, pas de correction.
    assert _update(_sp(doc_type="thesis", journal_id=42, doi="10.70675/abc123")) is None


def test_thesis_with_journal_id_no_doi_stays_thesis():
    # Sans DOI, rien ne distingue le mistype de la conflation : on ne bascule pas, le type reste thèse.
    assert _update(_sp(doc_type="thesis", journal_id=42, doi=None)) is None


def test_real_thesis_without_journal_id_untouched():
    assert _update(_sp(doc_type="thesis", journal_id=None)) is None


def test_thesis_to_article_strips_dissertation_keys():
    # Conflation : la SP corrigée thèse→article perd le NNT et les hal_id tel-/dumas-,
    # garde les autres hal_id (article) et les autres clés. Brut stashé pour réversibilité.
    upd = _update(
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
    upd = _update(
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
    upd = _update(
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
    upd = _update(_sp(source="hal", doc_type="ART", journal_type="media"))
    assert upd is not None
    assert upd.doc_type == "media"
    assert upd.raw_metadata == {
        "doc_type": {"raw": "ART", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
    }


def test_theses_fr_url_corrects_doc_type_and_stashes_raw():
    upd = _update(_sp(doc_type="article", urls=["https://theses.fr/2020ABCD"]))
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
    assert _update(sp) is None


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
    upd = _update(sp)
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata == {}


def test_expired_embargo_promotes_oa_status_to_green():
    # oa_status `embargoed` + embargo expiré (calculé au fetch) → `green`, brut stashé.
    upd = _update(_sp(oa_status="embargoed", embargo_expired=True))
    assert upd is not None
    assert upd.oa_status == "green"
    assert upd.raw_metadata["oa_status"] == {
        "raw": "embargoed",
        "corrected_by": "EMBARGO_EXPIRED_TO_GREEN",
    }


def test_active_embargo_oa_status_untouched():
    # Embargo non expiré → pas de promotion, no-op.
    assert _update(_sp(oa_status="embargoed", embargo_expired=False)) is None


def test_null_doc_type_left_null_when_no_rule():
    # Pas de mapping forcé pour None (pas de représentation à traduire) ; aucune règle → no-op.
    assert _update(_sp(doc_type=None)) is None


def test_preserves_unmanaged_raw_metadata_keys():
    # La clé `doi` (gérée par la sous-étape relationnelle) doit survivre à la passe unaire.
    sp = _sp(
        doc_type="article",
        urls=["https://theses.fr/2020ABCD"],
        raw_metadata={"doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    upd = _update(sp)
    assert upd is not None
    assert upd.raw_metadata == {
        "doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"},
        "doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"},
    }


def test_language_code_of_referential_untouched():
    assert _update(_sp(language="en")) is None


def test_language_name_mapped_to_code_with_marker():
    # WoS donne le nom anglais : la forme `english` le ramène à `en`, valeur source stashée.
    upd = _update(_sp(source="wos", language="English"))
    assert upd is not None
    assert upd.language == "en"
    assert upd.raw_metadata == {"language": {"raw": "English", "corrected_by": "LANGUAGE_MAP"}}


def test_unknown_language_gives_none_with_source_value_kept():
    upd = _update(_sp(source="hal", language="und"))
    assert upd is not None
    assert upd.language is None
    assert upd.raw_metadata == {"language": {"raw": "und", "corrected_by": "LANGUAGE_MAP"}}


def test_le_journal_compte_seulement_les_documents_corriges_par_une_regle(caplog):
    """Un type de document seulement traduit (`ART` → `article`) est mis à jour sans être corrigé."""
    queries = MagicMock()
    queries.fetch_for_unary_correction.return_value = [
        _sp(id=1, source="hal", doc_type="ART"),
        _sp(id=2, doc_type="article", urls=["https://theses.fr/2020ABCD"]),
    ]
    queries.fetch_language_forms.return_value = _FORMS
    with caplog.at_level(logging.INFO, logger="test"):
        run(MagicMock(), queries, logging.getLogger("test"))
    assert "  ├─ 1 document corrigé" in caplog.messages


def test_language_already_mapped_is_idempotent_noop():
    sp = _sp(
        source="wos",
        language="en",
        raw_metadata={"language": {"raw": "English", "corrected_by": "LANGUAGE_MAP"}},
    )
    assert _update(sp) is None
