"""ROR attribués par chaque normaliseur : sur l'adresse de leur affiliation, ou sur la seule signature pour une affiliation sans adresse."""

import logging

from domain.structures.identifiers import RorId
from pipeline.ingestion.common.signatures import AuthorRecord
from pipeline.ingestion.crossref.normalize import build_crossref_author_records
from pipeline.ingestion.datacite.normalize import build_datacite_author_records
from pipeline.ingestion.hal.normalize import build_hal_author_records
from pipeline.ingestion.openalex.normalize import build_openalex_author_records
from pipeline.ingestion.scanr.normalize import build_scanr_author_records
from pipeline.ingestion.wos.normalize import build_wos_author_records

UNIV, LABO = RorId("01a8ajp46"), RorId("03vgfxd91")


def _placement(record: AuthorRecord) -> dict[str | None, set[RorId]]:
    """ROR par texte d'adresse ; la clé `None` porte ceux de la seule signature."""
    placement: dict[str | None, set[RorId]] = {a.text: set(a.ror_ids) for a in record.addresses}
    placement[None] = set(record.ror_ids)
    return placement


def test_openalex_ror_des_institutions_de_chaque_affiliation():
    work = {
        "authorships": [
            {
                "raw_author_name": "Jane Doe",
                "raw_affiliation_strings": ["Institut Pascal"],
                "affiliations": [
                    {
                        "raw_affiliation_string": "Institut Pascal",
                        "institution_ids": ["https://openalex.org/I1"],
                    }
                ],
                "institutions": [
                    {"id": "https://openalex.org/I1", "ror": "https://ror.org/03vgfxd91"},
                    {"id": "https://openalex.org/I2", "ror": "https://ror.org/01a8ajp46"},
                    {"id": "https://openalex.org/I3", "ror": None},
                ],
            }
        ]
    }
    assert _placement(build_openalex_author_records(work)[0]) == {
        "Institut Pascal": {LABO},
        None: {UNIV},
    }


def test_wos_ror_des_organisations_de_chaque_adresse():
    rec = {
        "ut": "WOS:1",
        "authors": [
            {
                "position": 0,
                "full_name": "Jane Doe",
                "addresses": [
                    {"text": "Univ Clermont Auvergne", "ror_ids": ["https://ror.org/01a8ajp46"]},
                    {"text": "Inst Pascal", "ror_ids": []},
                ],
            }
        ],
    }
    assert _placement(build_wos_author_records(rec, logging.getLogger(__name__))[0]) == {
        "Univ Clermont Auvergne": {UNIV},
        "Inst Pascal": set(),
        None: set(),
    }


def test_crossref_identifiants_ror_de_chaque_affiliation():
    ror = {"id": "https://ror.org/01a8ajp46", "id-type": "ROR"}
    msg = {
        "author": [
            {
                "family": "Doe",
                "given": "Jane",
                "affiliation": [
                    {"name": "UCA", "id": [ror, {"id": "grid.494717.8", "id-type": "GRID"}]},
                    {"name": "Sans identifiant"},
                    {"id": [{"id": "https://ror.org/03vgfxd91", "id-type": "ROR"}]},
                ],
            }
        ]
    }
    assert _placement(build_crossref_author_records(msg)[0]) == {
        "UCA": {UNIV},
        "Sans identifiant": set(),
        None: {LABO},
    }


def test_scanr_ror_de_chaque_affiliation_et_des_tutelles_ecartees():
    doc = {
        "authors": [
            {
                "fullName": "Jane Doe",
                "affiliations": [
                    {
                        "name": "Institut Pascal",
                        "id_name_author_labo": "x###Jane Doe###y###Institut Pascal",
                        "ror": "https://ror.org/03vgfxd91",
                    },
                    {"name": "Université Clermont Auvergne", "ror": "https://ror.org/01a8ajp46"},
                ],
            }
        ]
    }
    assert _placement(build_scanr_author_records(doc)[0]) == {
        "Institut Pascal": {LABO},
        None: {UNIV},
    }


def test_scanr_structures_hal_des_affiliations_feuilles():
    doc = {
        "authors": [
            {
                "fullName": "Jane Doe",
                "affiliations": [
                    {"name": "LMV", "id_name_author_labo": "x", "structId": "483019"},
                    {"name": "Université Clermont Auvergne", "structId": "422708"},
                ],
            }
        ]
    }
    assert build_scanr_author_records(doc)[0].hal_structure_ids == {483019}


def test_hal_ror_de_la_structure_de_chaque_adresse():
    block = {
        "authFullNameFormIDPersonIDIDHal_fs": ["Jane Doe_FacetSep_1-0_FacetSep_"],
        "authIdHasStructure_fs": ["1-0_FacetSep_Jane Doe_JoinSep_472222_FacetSep_Institut Pascal"],
        "tei_author_rors": [
            [["472222", "https://ror.org/03vgfxd91"], ["81173", "https://ror.org/01a8ajp46"]]
        ],
    }
    assert _placement(build_hal_author_records(block)[0]) == {
        "Institut Pascal": {LABO},
        None: {UNIV},
    }


def test_datacite_affiliation_identifier_de_schema_ror():
    attributes = {
        "creators": [
            {
                "name": "Jane Doe",
                "affiliation": [
                    {
                        "name": "UCA",
                        "affiliationIdentifier": "https://ror.org/01a8ajp46",
                        "affiliationIdentifierScheme": "ROR",
                    },
                    {
                        "name": "Autre",
                        "affiliationIdentifier": "0000 0001 2345 6789",
                        "affiliationIdentifierScheme": "ISNI",
                    },
                    {
                        "affiliationIdentifier": "https://ror.org/03vgfxd91",
                        "affiliationIdentifierScheme": "ROR",
                    },
                    "Affiliation en chaîne",
                ],
            }
        ]
    }
    assert _placement(build_datacite_author_records(attributes)[0]) == {
        "UCA": {UNIV},
        "Autre": set(),
        "Affiliation en chaîne": set(),
        None: {LABO},
    }
