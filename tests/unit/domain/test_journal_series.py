"""Tests du niveau d'un titre de conteneur (`domain.journals.series`)."""

import pytest

from domain.journals.series import ContainerLevel, container_level, series_key


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
