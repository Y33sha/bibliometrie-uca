"""`correct_source_record` : valeurs corrigées d'un enregistrement source, statuts de ses identifiants et trace complète de ses corrections."""

from domain.source_records.corrections import CorrectionKey, stash_entry
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.metadata_correction.rules import MetadataForCorrection
from domain.source_records.metadata_correction.source_record import correct_source_record

_HAL_1 = SourceIdentifier(SourceIdentifierType.HAL_ID, "hal-1", SourceIdentifierRole.SECONDARY)
_HAL_2 = SourceIdentifier(SourceIdentifierType.HAL_ID, "hal-2", SourceIdentifierRole.SECONDARY)


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
    assert correct_source_record(_facts(), (), {}) is None


def test_entrees_des_autres_sous_etapes_gardees():
    others = {
        CorrectionKey.DOI: stash_entry("10.1/x", "OUVRAGE_VS_CHAPITRE"),
        CorrectionKey.SERIAL_ID: stash_entry(None, "SERIAL_BY_DOI_NAMESPACE"),
    }
    corrected = correct_source_record(_facts(serial_type="media"), (), others)
    assert corrected is not None
    assert corrected.columns.corrections == {
        **others,
        CorrectionKey.DOC_TYPE: stash_entry("article", "SERIAL_TYPE_MEDIA_TO_MEDIA"),
    }


def test_retrait_par_une_autre_sous_etape_garde():
    removed = SourceIdentifier(
        SourceIdentifierType.HAL_ID,
        "hal-1",
        SourceIdentifierRole.SECONDARY,
        "ACTES_VS_COMMUNICATION",
    )
    assert correct_source_record(_facts(), (removed, _HAL_2), {}) is None


def test_depot_hal_introuvable_retire():
    corrected = correct_source_record(_facts(), (_HAL_1, _HAL_2), {}, missing_hal_ids={"hal-1"})
    assert corrected is not None
    assert [i.removed_by for i in corrected.identifiers] == ["HAL_DEPOSIT_MISSING_TO_REMOVED", None]


def test_retrait_defait_quand_la_regle_ne_s_applique_plus():
    removed = SourceIdentifier(
        SourceIdentifierType.HAL_ID,
        "hal-1",
        SourceIdentifierRole.SECONDARY,
        "HAL_DEPOSIT_MISSING_TO_REMOVED",
    )
    corrected = correct_source_record(_facts(), (removed,), {})
    assert corrected is not None
    assert corrected.identifiers == (_HAL_1,)


def test_correction_defaite_quand_la_regle_ne_s_applique_plus():
    corrected = correct_source_record(
        _facts(doc_type="media"),
        (),
        {CorrectionKey.DOC_TYPE: stash_entry("article", "SERIAL_TYPE_MEDIA_TO_MEDIA")},
    )
    assert corrected is not None
    assert (corrected.columns.doc_type, corrected.columns.corrections) == ("article", {})
