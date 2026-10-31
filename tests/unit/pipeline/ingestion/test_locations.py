"""Localisations d'un enregistrement source (`pipeline.ingestion.common.locations`)."""

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from pipeline.ingestion.common.locations import (
    LocationFacts,
    identifier_locations,
    merge_locations,
)


def _doi(value: str, role: SourceIdentifierRole = SourceIdentifierRole.PRIMARY) -> SourceIdentifier:
    return SourceIdentifier(SourceIdentifierType.DOI, value, role)


def test_doi_de_serveur_de_preprints_ouvert_donne_une_copie_ouverte():
    """bioRxiv et medRxiv partagent le préfixe 10.1101, et donnent tous deux librement accès à leur contenu."""
    assert identifier_locations([_doi("10.1101/2020.01.01.123456")]) == [
        LocationFacts("https://doi.org/10.1101/2020.01.01.123456", is_oa=True)
    ]


def test_doi_d_un_autre_serveur_donne_une_copie_sans_acces_libre_declare():
    assert identifier_locations([_doi("10.2139/ssrn.123")]) == [
        LocationFacts("https://doi.org/10.2139/ssrn.123", is_oa=False)
    ]


def test_doi_de_revue_ou_doi_lie_sans_copie():
    identifiers = [
        _doi("10.1101/gad.1"),
        _doi("10.1038/s41586-020-1"),
        _doi("10.1101/2020.01.01.123456", SourceIdentifierRole.RELATED),
    ]
    assert identifier_locations(identifiers) == []


def test_les_portails_hal_d_un_depot_forment_une_seule_copie():
    merged = merge_locations(
        [
            LocationFacts("https://shs.hal.science/halshs-01497672", is_oa=False),
            LocationFacts(
                "https://halshs.archives-ouvertes.fr/halshs-01497672v2/document", is_oa=True
            ),
            LocationFacts("https://hal.science/halshs-01497672"),
        ]
    )
    assert merged == [
        LocationFacts(
            "https://hal.science/halshs-01497672",
            pdf_url="https://halshs.archives-ouvertes.fr/halshs-01497672v2/document",
            is_oa=True,
        )
    ]


def test_un_depot_dumas_garde_son_portail_une_these_tel_va_sur_hal_science():
    merged = merge_locations(
        [
            LocationFacts("https://dumas.ccsd.cnrs.fr/dumas-01234567v1"),
            LocationFacts("https://tel.archives-ouvertes.fr/tel-01234567"),
        ]
    )
    assert [loc.url for loc in merged] == [
        "https://dumas.ccsd.cnrs.fr/dumas-01234567",
        "https://hal.science/tel-01234567",
    ]


def test_deux_depots_hal_restent_distincts():
    merged = merge_locations(
        [
            LocationFacts("https://hal.science/hal-01607327v1"),
            LocationFacts("https://hal.science/hal-01651302"),
        ]
    )
    assert [loc.url for loc in merged] == [
        "https://hal.science/hal-01607327",
        "https://hal.science/hal-01651302",
    ]


def test_les_pages_descriptives_et_les_autres_adresses():
    merged = merge_locations(
        [
            LocationFacts("https://doaj.org/article/abc"),
            LocationFacts("https://doi.org/10.1/x", is_oa=False),
            LocationFacts("https://doi.org/10.1/x", oai_id="doublon"),
        ]
    )
    assert merged == [LocationFacts("https://doi.org/10.1/x", is_oa=False)]
