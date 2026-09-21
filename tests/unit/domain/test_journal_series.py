"""Tests du niveau d'un titre de conteneur (`domain.journals.series`)."""

import pytest

from domain.journals.series import (
    ContainerLevel,
    SeriesGroup,
    VolumeTitle,
    container_level,
    group_series,
    reference_series_title,
    series_key,
    series_title,
    split_collection_and_volume,
)


@pytest.mark.parametrize(
    "title",
    [
        "NuFACT 2022",
        "2024 IEEE SENSORS",
        "8th International Conference on Control, Decision and Information Technologies (CoDIT)",
        "Actes des 34es Journées Francophones sur les Systèmes Multi-Agents",
        "Actes du 1er colloque",
        "Book of Abstracts of the 74. Annual Meeting of the European Federation of Animal Science",
        "LIPIcs, Volume 364, STACS 2026",
    ],
)
def test_titre_de_volume(title):
    assert container_level(title) is ContainerLevel.VOLUME


@pytest.mark.parametrize(
    "title",
    [
        "Lecture notes in computer science",
        "Proceedings of the AAAI Conference on Artificial Intelligence",
        "IOP Conference Series Earth and Environmental Science",
        "Studies in 19th-century literature",
        "Le XVIe siècle",
        "Poetry, 1960–2015",
        "Journal of high energy physics 2018(7)",
    ],
)
def test_titre_de_serie(title):
    assert container_level(title) is ContainerLevel.SERIES


def test_volumes_d_une_meme_serie_partagent_la_cle():
    assert series_key("NuFACT 2022") == series_key("NuFACT 2023") == "nufact"
    assert series_key("LIPIcs, Volume 364, STACS 2026") == series_key(
        "LIPIcs, Volume 367, STACS 2027"
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            (
                "Proceedings of the 12th International Conference on Operations Research"
                " and Enterprise Systems (ICORES 2023)"
            ),
            (
                "Proceedings of the International Conference on Operations Research"
                " and Enterprise Systems (ICORES)"
            ),
        ),
        (
            (
                "World Congress on Medical Physics and Biomedical Engineering,"
                " September 7 - 12, 2009, Munich, Germany"
            ),
            "World Congress on Medical Physics and Biomedical Engineering, Munich, Germany",
        ),
        ("LIPIcs, Volume 364, STACS 2026", "LIPIcs, STACS"),
        (
            "2022 IEEE 95th Vehicular Technology Conference: (VTC2022-Spring)",
            "IEEE Vehicular Technology Conference: (VTC-Spring)",
        ),
        ("Goldschmidt2023 abstracts", "Goldschmidt abstracts"),
        (
            "Dossier : Justice pour l'eau, Actes du colloque de Clermont-Ferrand du 6 juin 2019",
            "Dossier : Justice pour l'eau, Actes du colloque de Clermont-Ferrand",
        ),
    ],
)
def test_titre_de_serie_d_un_volume(title, expected):
    assert series_title(title) == expected


class TestReferenceSeriesTitle:
    def test_titre_de_serie_garde(self):
        assert reference_series_title("Lecture notes in computer science", None) is None

    def test_titre_sudoc_fait_reference(self):
        assert (
            reference_series_title("ICORES 2023", "Operations research and enterprise systems")
            == "Operations research and enterprise systems"
        )

    def test_sans_notice_titre_sans_marques(self):
        assert reference_series_title("8th CoDIT", None) == "CoDIT"

    def test_titre_sudoc_de_volume_ignore(self):
        assert reference_series_title("NuFACT 2022", "NuFACT 2021") == "NuFACT"


class TestGroupSeries:
    def test_volumes_d_une_meme_serie(self):
        volumes = [
            VolumeTitle(2, "2023 Winter Simulation Conference (WSC)", 5),
            VolumeTitle(1, "2022 Winter Simulation Conference (WSC)", 5),
        ]
        assert group_series(volumes) == [
            SeriesGroup("Winter Simulation Conference (WSC)", 5, (1, 2))
        ]

    def test_editeurs_differents_pas_de_serie(self):
        volumes = [VolumeTitle(1, "NuFACT 2022", 5), VolumeTitle(2, "NuFACT 2023", 6)]
        assert group_series(volumes) == []

    def test_ouvrage_en_plusieurs_volumes_pas_de_serie(self):
        """Cas réel : « Current Developments in Biotechnology and Bioengineering », quatre volumes sans marque d'édition."""
        title = "Current Developments in Biotechnology and Bioengineering"
        assert group_series([VolumeTitle(1, title, 5), VolumeTitle(2, title, 5)]) == []

    def test_volume_seul_pas_de_serie(self):
        assert group_series([VolumeTitle(1, "NuFACT 2022", 5)]) == []


def test_deux_titres_le_volume_a_la_forme_d_un_volume():
    assert split_collection_and_volume(
        "ICORES 2023", "Lecture Notes in Business Information Processing"
    ) == (
        "Lecture Notes in Business Information Processing",
        "ICORES 2023",
    )


def test_deux_titres_sans_forme_distinctive_l_ordre_tranche():
    """Cas réel : UNCECOMP, deux titres de volume ; Operator Theory, aucun."""
    assert split_collection_and_volume(
        "Proceedings of the 5th International Conference UNCECOMP 2019",
        "5th International Conference on Uncertainty Quantification",
    ) == (
        "Proceedings of the 5th International Conference UNCECOMP 2019",
        "5th International Conference on Uncertainty Quantification",
    )
    assert split_collection_and_volume(
        "Operator Theory: Advances and Applications", "Ritt Operators and Their Functional Calculus"
    ) == (
        "Operator Theory: Advances and Applications",
        "Ritt Operators and Their Functional Calculus",
    )
