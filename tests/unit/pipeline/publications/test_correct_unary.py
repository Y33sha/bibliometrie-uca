"""Tests purs de `compute_update` : correction unaire idempotente."""

import logging
from unittest.mock import MagicMock

from domain.source_records.corrections import stash_entry
from domain.source_records.metadata_correction.rules import MetadataForCorrection
from domain.source_records.metadata_correction.source_record import CorrectedSourceRecord
from pipeline.transformation.publications.correction.correct_unary import (
    compute_update,
    compute_updates,
    hal_origin_ids,
    run,
    tally_corrections,
)
from pipeline.transformation.publications.correction.correction_store import (
    CorrectionUpdate,
    UnaryCorrectionRow,
)


def _update(source_record: UnaryCorrectionRow) -> CorrectionUpdate | None:
    return compute_update(source_record)


def test_tally_corrections_compte_les_regles():
    updates = [
        CorrectionUpdate(
            2,
            CorrectedSourceRecord(
                "thesis",
                None,
                {},
                {"doc_type": stash_entry("article", "THESIS_WITH_SERIAL_TO_ARTICLE")},
            ),
        ),
        # deux champs corrigés sur un même enregistrement source → 1 enregistrement source, 2 déclenchements
        CorrectionUpdate(
            3,
            CorrectedSourceRecord(
                "media",
                "green",
                {},
                {
                    "doc_type": stash_entry("article", "SERIAL_TYPE_MEDIA_TO_MEDIA"),
                    "oa_status": stash_entry("closed", "EMBARGO_EXPIRED_TO_GREEN"),
                },
            ),
        ),
        # correction défaite : mise à jour sans règle
        CorrectionUpdate(4, CorrectedSourceRecord("article", None, {}, {})),
    ]
    corrected, rule_counts = tally_corrections(updates)
    assert corrected == 2
    assert rule_counts == {
        "THESIS_WITH_SERIAL_TO_ARTICLE": 1,
        "SERIAL_TYPE_MEDIA_TO_MEDIA": 1,
        "EMBARGO_EXPIRED_TO_GREEN": 1,
    }


_ROW_FIELDS = ("id", "source_id", "external_ids", "corrections")


def _source_record(**overrides: object) -> UnaryCorrectionRow:
    """Ligne de correction unaire ; une clé hors des champs de la ligne est un fait des règles."""
    row: dict[str, object] = {"id": 1, "source_id": "W1", "external_ids": {}, "corrections": {}}
    facts: dict[str, object] = {
        "source": "openalex",
        "title": "Un titre quelconque",
        "doc_type": "article",
        "doi": None,
        "serial_id": None,
        "embargo_expired": False,
        "self_declared_preprint": False,
        "declares_conference": False,
        "in_proceedings_volume": False,
        "journal_diamond": False,
        "author_count": 1,
    }
    for key, value in overrides.items():
        (row if key in _ROW_FIELDS else facts)[key] = value
    return UnaryCorrectionRow(**row, facts=MetadataForCorrection(**facts))  # type: ignore[arg-type]


def test_no_rule_returns_none():
    assert _update(_source_record(doc_type="article")) is None


def test_thesis_with_serial_id_and_publisher_doi_is_mistyped_article():
    # Mistype OpenAlex/ScanR : un article typé thèse, rattaché à un journal, avec un DOI d'éditeur
    # (préfixe ≠ registre de thèses) → article.
    upd = _update(_source_record(doc_type="thesis", serial_id=42, doi="10.1016/j.ex.2020.01.001"))
    assert upd is not None
    assert upd.corrected.doc_type == "article"
    assert upd.corrected.corrections == {
        "doc_type": {"raw": "thesis", "corrected_by": "THESIS_WITH_SERIAL_TO_ARTICLE"}
    }


def test_thesis_with_serial_id_but_thesis_registry_doi_stays_thesis():
    # DOI ABES (registre des thèses FR) : c'est le DOI propre de la thèse, le serial_id est parasite
    # (conflation thèse↔version publiée) → le type reste thèse, pas de correction.
    assert _update(_source_record(doc_type="thesis", serial_id=42, doi="10.70675/abc123")) is None


def test_thesis_with_serial_id_no_doi_stays_thesis():
    # Sans DOI, rien ne distingue le mistype de la conflation : on ne bascule pas, le type reste thèse.
    assert _update(_source_record(doc_type="thesis", serial_id=42, doi=None)) is None


def test_real_thesis_without_serial_id_untouched():
    assert _update(_source_record(doc_type="thesis", serial_id=None)) is None


def test_retrait_par_cluster_reapplique():
    """L'étape unaire garde le retrait d'identifiants noté par l'étape cluster : aucune mise à jour."""
    removal = {
        "removed_external_ids": {
            "before": {"hal_id": ["hal-1", "hal-2"]},
            "removed": {"hal_id": ["hal-1"]},
            "corrected_by": "ACTES_VS_COMMUNICATION",
        }
    }
    assert _update(_source_record(external_ids={"hal_id": ["hal-2"]}, corrections=removal)) is None


def test_retrait_par_cluster_compose_avec_la_conflation_these():
    removal = {
        "removed_external_ids": {
            "before": {"hal_id": ["tel-01", "hal-99", "hal-5"]},
            "removed": {"hal_id": ["hal-5"]},
            "corrected_by": "ACTES_VS_COMMUNICATION",
        }
    }
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            external_ids={"hal_id": ["tel-01", "hal-99", "hal-5"]},
            corrections=removal,
        )
    )
    assert upd is not None
    assert upd.corrected.external_ids == {"hal_id": ["hal-99"]}
    assert upd.corrected.corrections["removed_external_ids"] == removal["removed_external_ids"]


def test_thesis_to_article_strips_dissertation_keys():
    # Conflation : l'enregistrement source corrigé thèse→article perd le NNT et les hal_id tel-/dumas-,
    # garde les autres hal_id (article) et les autres clés. Brut stashé pour réversibilité.
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            external_ids={"nnt": "2020X", "hal_id": ["tel-01", "hal-99"], "pmid": "123"},
        )
    )
    assert upd is not None
    assert upd.corrected.doc_type == "article"
    assert upd.corrected.external_ids == {"hal_id": ["hal-99"], "pmid": "123"}
    assert upd.corrected.corrections["external_ids"] == {
        "raw": {"nnt": "2020X", "hal_id": ["tel-01", "hal-99"], "pmid": "123"},
        "corrected_by": "THESIS_WITH_SERIAL_TO_ARTICLE",
    }


def test_thesis_to_article_without_dissertation_keys_leaves_external_ids():
    # Mistype pur (pas de clé-thèse) : external_ids inchangé, pas de stash.
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            external_ids={"pmid": "123"},
        )
    )
    assert upd is not None
    assert upd.corrected.doc_type == "article"
    assert upd.corrected.external_ids == {"pmid": "123"}
    assert "external_ids" not in upd.corrected.corrections


def test_serial_id_wins_over_theses_fr_url_conflation():
    # Conflation thèse↔article : un enregistrement source theses.fr AVEC un serial_id ET un DOI d'éditeur → article
    # (`serial_id_present: False` garde la règle URL ; `doi_prefix_not_in` distingue l'article
    # publié — DOI éditeur — d'une vraie thèse à DOI ABES).
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            urls=["https://theses.fr/2020X"],
        )
    )
    assert upd is not None
    assert upd.corrected.doc_type == "article"
    assert upd.corrected.corrections["doc_type"]["corrected_by"] == "THESIS_WITH_SERIAL_TO_ARTICLE"


def test_serial_media_corrects_and_stashes_the_value_before_correction():
    upd = _update(_source_record(source="hal", doc_type="article", serial_type="media"))
    assert upd is not None
    assert upd.corrected.doc_type == "media"
    assert upd.corrected.corrections == {
        "doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
    }


def test_theses_fr_url_corrects_doc_type_and_stashes_raw():
    upd = _update(_source_record(doc_type="article", urls=["https://theses.fr/2020ABCD"]))
    assert upd is not None
    assert upd.corrected.doc_type == "thesis"
    assert upd.corrected.corrections == {
        "doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}
    }


def test_already_corrected_is_idempotent_noop():
    source_record = _source_record(
        doc_type="thesis",
        urls=["https://theses.fr/2020ABCD"],
        corrections={"doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}},
    )
    assert _update(source_record) is None


def test_self_heals_when_rule_no_longer_applies():
    # doc_type figé à 'media' par une règle journal, mais le journal n'est plus 'media' :
    # la correction doit être défaite, le brut canonique 'article' restauré.
    source_record = _source_record(
        doc_type="media",
        serial_type=None,
        corrections={"doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}},
    )
    upd = _update(source_record)
    assert upd is not None
    assert upd.corrected.doc_type == "article"
    assert upd.corrected.corrections == {}


def test_expired_embargo_promotes_oa_status_to_green():
    # oa_status `embargoed` + embargo expiré (calculé au fetch) → `green`, brut stashé.
    upd = _update(_source_record(oa_status="embargoed", embargo_expired=True))
    assert upd is not None
    assert upd.corrected.oa_status == "green"
    assert upd.corrected.corrections["oa_status"] == {
        "raw": "embargoed",
        "corrected_by": "EMBARGO_EXPIRED_TO_GREEN",
    }


def test_active_embargo_oa_status_untouched():
    # Embargo non expiré → pas de promotion, no-op.
    assert _update(_source_record(oa_status="embargoed", embargo_expired=False)) is None


def test_null_doc_type_left_null_when_no_rule():
    assert _update(_source_record(doc_type=None)) is None


def test_preserves_unmanaged_corrections_keys():
    # La clé `doi` (gérée par la sous-étape relationnelle) doit survivre à la passe unaire.
    source_record = _source_record(
        doc_type="article",
        urls=["https://theses.fr/2020ABCD"],
        corrections={"doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    upd = _update(source_record)
    assert upd is not None
    assert upd.corrected.corrections == {
        "doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"},
        "doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"},
    }


def test_le_journal_compte_seulement_les_documents_corriges_par_une_regle(caplog):
    """Une correction défaite donne une mise à jour, sans compter comme une correction."""
    queries = MagicMock()
    queries.fetch_for_unary_correction.return_value = [
        _source_record(
            id=1,
            doc_type="media",
            corrections={
                "doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
            },
        ),
        _source_record(id=2, doc_type="article", urls=["https://theses.fr/2020ABCD"]),
    ]
    with caplog.at_level(logging.INFO, logger="test"):
        run(MagicMock(), queries, logging.getLogger("test"))
    assert "  ├─ 1 document à corriger" in caplog.messages


# ── Enregistrements sources ScanR issues d'un dépôt HAL ─────────────────────────────


def test_scanr_from_hal_takes_corrected_hal_type():
    """Un enregistrement source ScanR issue de HAL prend le type corrigé de son dépôt, calculé depuis l'enregistrement source HAL."""
    hal = _source_record(id=1, source="hal", source_id="hal-04565713", doc_type="poster")
    scanr = _source_record(id=2, source="scanr", source_id="halhal-04565713", doc_type="other")

    updates = compute_updates([hal, scanr], {"hal-04565713": hal})

    (scanr_update,) = [u for u in updates if u.id == 2]
    assert scanr_update.corrected.doc_type == "poster"
    assert (
        scanr_update.corrected.corrections["doc_type"]["corrected_by"]
        == "SCANR_FROM_HAL_TO_HAL_TYPE"
    )


def test_scanr_without_hal_deposit_keeps_its_type():
    scanr = _source_record(id=2, source="scanr", source_id="halhal-04565713", doc_type="other")
    assert compute_updates([scanr], {}) == []


def test_scanr_from_another_origin_keeps_its_type():
    scanr = _source_record(id=2, source="scanr", source_id="doi10.1/x", doc_type="other")
    hal = _source_record(id=1, source="hal", source_id="hal-04565713", doc_type="poster")
    assert [u.id for u in compute_updates([scanr], {"hal-04565713": hal})] == []


def test_hal_origin_ids():
    rows = [
        _source_record(source="scanr", source_id="halhal-04565713"),
        _source_record(source="scanr", source_id="doi10.1/x"),
        _source_record(source="hal", source_id="hal-04501427"),
    ]
    assert hal_origin_ids(rows) == ["hal-04565713"]
