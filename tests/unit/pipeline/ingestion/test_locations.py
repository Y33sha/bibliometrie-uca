"""Fusion des localisations d'un enregistrement source (`pipeline.ingestion.common.locations`)."""

from pipeline.ingestion.common.locations import LocationFacts, merge_locations


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


def test_un_depot_dumas_ou_tel_garde_son_portail():
    merged = merge_locations(
        [
            LocationFacts("https://dumas.ccsd.cnrs.fr/dumas-01234567v1"),
            LocationFacts("https://tel.archives-ouvertes.fr/tel-01234567"),
        ]
    )
    assert [loc.url for loc in merged] == [
        "https://dumas.ccsd.cnrs.fr/dumas-01234567",
        "https://theses.hal.science/tel-01234567",
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
