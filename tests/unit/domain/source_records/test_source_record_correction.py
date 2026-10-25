"""`correct_source_record` : valeurs corrigées d'un enregistrement source et trace complète de ses corrections."""

from domain.source_records.corrections import CorrectionKey, removal_entry, stash_entry
from domain.source_records.metadata_correction.rules import MetadataForCorrection
from domain.source_records.metadata_correction.source_record import correct_source_record


def _facts(**overrides: object) -> MetadataForCorrection:
    defaults: dict[str, object] = {
        "title": "Un titre",
        "doc_type": "article",
        "doi": None,
        "serial_id": None,
    }
    defaults.update(overrides)
    return MetadataForCorrection(**defaults)  # type: ignore[arg-type]


def test_enregistrement_deja_corrige():
    assert correct_source_record(_facts(), {}, {}) is None


def test_entrees_des_autres_sous_etapes_gardees():
    others = {
        CorrectionKey.DOI: stash_entry("10.1/x", "OUVRAGE_VS_CHAPITRE"),
        CorrectionKey.SERIAL_ID: stash_entry(None, "SERIAL_BY_DOI_NAMESPACE"),
    }
    corrected = correct_source_record(_facts(serial_type="media"), {}, others)
    assert corrected is not None
    assert corrected.corrections == {
        **others,
        CorrectionKey.DOC_TYPE: stash_entry("article", "SERIAL_TYPE_MEDIA_TO_MEDIA"),
    }


def test_retrait_par_cluster_reapplique():
    removal = removal_entry(
        {"hal_id": ["hal-1", "hal-2"]}, {"hal_id": ["hal-1"]}, "ACTES_VS_COMMUNICATION"
    )
    corrected = correct_source_record(
        _facts(),
        {"hal_id": ["hal-1", "hal-2"]},
        {CorrectionKey.REMOVED_EXTERNAL_IDS: removal},
    )
    assert corrected is not None
    assert corrected.external_ids == {"hal_id": ["hal-2"]}


def test_correction_defaite_quand_la_regle_ne_s_applique_plus():
    corrected = correct_source_record(
        _facts(doc_type="media"),
        {},
        {CorrectionKey.DOC_TYPE: stash_entry("article", "SERIAL_TYPE_MEDIA_TO_MEDIA")},
    )
    assert corrected is not None
    assert (corrected.doc_type, corrected.corrections) == ("article", {})
