"""ROR attribués aux signatures par chaque normaliseur."""

import logging

from application.pipeline.normalize.normalize_crossref import build_crossref_author_records
from application.pipeline.normalize.normalize_datacite import build_datacite_author_records
from application.pipeline.normalize.normalize_openalex import build_openalex_author_records
from application.pipeline.normalize.normalize_scanr import build_scanr_author_records
from application.pipeline.normalize.normalize_wos import build_wos_author_records
from domain.structures.identifiers import RorId

UNIV, LABO = RorId("01a8ajp46"), RorId("03vgfxd91")


def test_openalex_ror_des_institutions():
    work = {
        "authorships": [
            {
                "raw_author_name": "Jane Doe",
                "institutions": [
                    {"display_name": "UCA", "ror": "https://ror.org/01a8ajp46"},
                    {"display_name": "Sans ROR", "ror": None},
                ],
            }
        ]
    }
    assert build_openalex_author_records(work)[0].ror_ids == {UNIV}


def test_wos_ror_des_organisations_des_adresses():
    rec = {
        "ut": "WOS:1",
        "authors": [
            {
                "position": 0,
                "full_name": "Jane Doe",
                "addresses": ["Univ Clermont Auvergne, Inst Pascal"],
                "organizations": [
                    {"name": "Univ Clermont Auvergne", "ror_id": "https://ror.org/01a8ajp46"},
                    {"name": "Inst Pascal", "ror_id": None},
                ],
            }
        ],
    }
    assert build_wos_author_records(rec, logging.getLogger(__name__))[0].ror_ids == {UNIV}


def test_crossref_identifiants_ror_des_affiliations():
    msg = {
        "author": [
            {
                "family": "Doe",
                "given": "Jane",
                "affiliation": [
                    {
                        "name": "UCA",
                        "id": [
                            {"id": "https://ror.org/01a8ajp46", "id-type": "ROR"},
                            {"id": "grid.494717.8", "id-type": "GRID"},
                        ],
                    },
                    {"name": "Sans identifiant"},
                ],
            }
        ]
    }
    assert build_crossref_author_records(msg)[0].ror_ids == {UNIV}


def test_scanr_ror_de_toutes_les_affiliations():
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
    record = build_scanr_author_records(doc)[0]
    assert [a.text for a in record.addresses] == ["Institut Pascal"]
    assert record.ror_ids == {UNIV, LABO}


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
                    "Affiliation en chaîne",
                ],
            }
        ]
    }
    assert build_datacite_author_records(attributes)[0].ror_ids == {UNIV}
