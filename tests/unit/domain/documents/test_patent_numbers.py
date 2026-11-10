"""Tests de la lecture des numéros de brevet d'un texte libre, sur des valeurs de `number_s` des dépôts HAL."""

import pytest

from domain.documents.patent_numbers import (
    PatentNumberKind,
    ReadPatentNumber,
    is_disclosure,
    read_patent_numbers,
)

PUBLICATION = PatentNumberKind.PUBLICATION
APPLICATION = PatentNumberKind.APPLICATION


@pytest.mark.parametrize(
    ("text", "year", "expected"),
    [
        # Publications, codes de type et séparateurs.
        ("FR3055549 (A1)", 2018, [(PUBLICATION, "FR3055549")]),
        ("FR.3.067.121", 2018, [(PUBLICATION, "FR3067121")]),
        ("3 109 054", 2021, [(PUBLICATION, "FR3109054")]),
        ("WO/2019/229378", 2019, [(PUBLICATION, "WO2019229378")]),
        ("WO2018215476A1", 2018, [(PUBLICATION, "WO2018215476")]),
        ("EP 4 235 469 A1", 2023, [(PUBLICATION, "EP4235469")]),
        ("ES2880413 (T3)", 2021, [(PUBLICATION, "ES2880413")]),
        # Publications américaines : demande publiée, brevet délivré.
        ("US20240211607A1", 2024, [(PUBLICATION, "US2024211607")]),
        ("US2024127465 (A1)", 2024, [(PUBLICATION, "US2024127465")]),
        ("US Patent : US9856383B2", 2018, [(PUBLICATION, "US9856383")]),
        ("11,198,814", 2021, [(PUBLICATION, "US11198814")]),
        # Demandes françaises.
        ("FR19/04067", 2019, [(APPLICATION, "FR1904067")]),
        ("FR-1860557", 2018, [(APPLICATION, "FR1860557")]),
        ("21 13249", 2021, [(APPLICATION, "FR2113249")]),
        ("1760978", 2017, [(APPLICATION, "FR1760978")]),
        ("FR2024/04.864", 2024, [(APPLICATION, "FR2404864")]),
        ("FR2100307", 2025, [(APPLICATION, "FR2100307")]),
        # Demandes européennes, avec ou sans office.
        ("EP21306403.3", 2021, [(APPLICATION, "EP21306403")]),
        ("EP22306008", 2022, [(APPLICATION, "EP22306008")]),
        ("20350072.9", 2020, [(APPLICATION, "EP20350072")]),
        ("FEP23290029.0", 2023, [(APPLICATION, "EP23290029")]),
        # Demandes internationales.
        ("PCT/FR2025/050875", 2025, [(APPLICATION, "WO2025050875")]),
        ("WO2022FR50459 20220315", 2021, [(APPLICATION, "WO2022050459")]),
        ("WO2019EP84487 20191210", 2019, [(APPLICATION, "WO2019084487")]),
        # Plusieurs numéros.
        (
            "N°WO2018002556 A1 N°FR3053353",
            2018,
            [(PUBLICATION, "WO2018002556"), (PUBLICATION, "FR3053353")],
        ),
        (
            "Brevet national N° FR2017050584. Brevet international N° WO2017158284 (2019-09-21)",
            2017,
            [(APPLICATION, "WO2017050584"), (PUBLICATION, "WO2017158284")],
        ),
        (
            "WO 2021/064186 A1 / EP 4037770 A1 (US 12351556 B2 ; JP 7646643 B2)",
            2021,
            [
                (PUBLICATION, "WO2021064186"),
                (PUBLICATION, "EP4037770"),
                (PUBLICATION, "US12351556"),
                (PUBLICATION, "JP7646643"),
            ],
        ),
        ("B-025149FR01_2021-12-24 FR3131453 (A1) 2023-06-30", 2023, [(PUBLICATION, "FR3131453")]),
        ("Application No. EP16162941.5, Patent No. 1360", 2017, [(APPLICATION, "EP16162941")]),
        # Références internes et numéros illisibles.
        ("DI-RV-22-0027", 2022, []),
        ("P-19-25", 2021, []),
        ("21060884", 2020, []),
        ("EP20200315228", 2021, []),
        (None, None, []),
    ],
)
def test_read_patent_numbers(text, year, expected):
    assert read_patent_numbers(text, year) == [ReadPatentNumber(k, v) for k, v in expected]


def test_publication_francaise_ancienne():
    """Un numéro français de forme demande, d'une année postérieure au document, est une publication."""
    assert read_patent_numbers("FR2957077", 2011) == [ReadPatentNumber(PUBLICATION, "FR2957077")]


def test_doublons_retires():
    assert read_patent_numbers("FR1908401 FR 1908401", 2019) == [
        ReadPatentNumber(APPLICATION, "FR1908401")
    ]


@pytest.mark.parametrize(
    ("number", "title", "expected"),
    [
        ("DI-RV-22-0027", "Composition probiotique", True),
        (None, "Déclaration d’Invention et de Résultats Valorisables DI-RV-20-0104 (2020)", True),
        (
            "DSO2021006565",
            "Dépôt en ligne auprès de l'INPI d’une enveloppe Soleau électronique",
            True,
        ),
        ("21 08274", "Certificat d’utilité n° 21 08274 (2021) : Support de flacon", False),
        ("FR3055549 (A1)", "Méthode de détection", False),
    ],
)
def test_declaration_d_invention_ou_enveloppe_soleau(number, title, expected):
    assert is_disclosure(number, title) is expected
