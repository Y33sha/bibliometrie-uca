"""Lecture d'un document de `ref/structure` en `HalStructure`."""

import datetime

from domain.structures.hal_structures import HalStructureStatus, parse_hal_structure

_LMV = {
    "docid": "483019",
    "name_s": "Laboratoire Magmas et Volcans",
    "acronym_s": "LMV",
    "type_s": "laboratory",
    "country_s": "fr",
    "valid_s": "OLD",
    "ror_s": ["https://ror.org/02vnq7240"],
    "startDate_s": "2017-01-01",
    "endDate_s": "2020-12-31",
    "parentDocid_i": ["67872", "300045", "483019"],
    "aliasDocid_i": [1069029, 136807],
}


def test_lit_une_structure_complete():
    structure = parse_hal_structure(_LMV)

    assert structure is not None
    assert structure.hal_structure_id == 483019
    assert structure.status is HalStructureStatus.OLD
    assert structure.ror_id is not None and structure.ror_id.value == "02vnq7240"
    assert structure.country_code == "fr"
    assert (structure.start_date, structure.end_date) == (
        datetime.date(2017, 1, 1),
        datetime.date(2020, 12, 31),
    )
    # Une structure n'est ni son propre parent ni son propre alias.
    assert structure.parent_ids == (67872, 300045)
    assert structure.alias_ids == (136807, 1069029)


def test_ecarte_un_document_sans_statut_reconnu():
    assert parse_hal_structure({**_LMV, "valid_s": "PENDING"}) is None


def test_champs_facultatifs_absents():
    structure = parse_hal_structure(
        {"docid": "1", "name_s": "Équipe", "type_s": "researchteam", "valid_s": "VALID"}
    )

    assert structure is not None
    assert (structure.acronym, structure.ror_id, structure.country_code) == (None, None, None)
    assert structure.parent_ids == ()
