"""Tests de la lecture des numéros de brevet d'un texte libre, sur des valeurs de `number_s` des dépôts HAL."""

import pytest

from domain.documents.patent_numbers import PatentNumberKind, ReadPatentNumber, read_patent_numbers

PUB = PatentNumberKind.PUBLICATION
APP = PatentNumberKind.APPLICATION


@pytest.mark.parametrize(
    ("text", "year", "expected"),
    [
        # Publications, codes de type et séparateurs.
        ("FR3055549 (A1)", 2018, [(PUB, "FR3055549")]),
        ("FR.3.067.121", 2018, [(PUB, "FR3067121")]),
        ("3 109 054", 2021, [(PUB, "FR3109054")]),
        ("WO/2019/229378", 2019, [(PUB, "WO2019229378")]),
        ("WO2018215476A1", 2018, [(PUB, "WO2018215476")]),
        ("EP 4 235 469 A1", 2023, [(PUB, "EP4235469")]),
        ("ES2880413 (T3)", 2021, [(PUB, "ES2880413")]),
        # Publications américaines : demande publiée, brevet délivré.
        ("US20240211607A1", 2024, [(PUB, "US2024211607")]),
        ("US2024127465 (A1)", 2024, [(PUB, "US2024127465")]),
        ("US Patent : US9856383B2", 2018, [(PUB, "US9856383")]),
        ("11,198,814", 2021, [(PUB, "US11198814")]),
        # Demandes françaises.
        ("FR19/04067", 2019, [(APP, "FR1904067")]),
        ("FR-1860557", 2018, [(APP, "FR1860557")]),
        ("21 13249", 2021, [(APP, "FR2113249")]),
        ("1760978", 2017, [(APP, "FR1760978")]),
        ("FR2024/04.864", 2024, [(APP, "FR2404864")]),
        ("FR2100307", 2025, [(APP, "FR2100307")]),
        # Demandes européennes, avec ou sans office.
        ("EP21306403.3", 2021, [(APP, "EP21306403")]),
        ("EP22306008", 2022, [(APP, "EP22306008")]),
        ("20350072.9", 2020, [(APP, "EP20350072")]),
        ("FEP23290029.0", 2023, [(APP, "EP23290029")]),
        # Demandes internationales.
        ("PCT/FR2025/050875", 2025, [(APP, "WO2025050875")]),
        ("WO2022FR50459 20220315", 2021, [(APP, "WO2022050459")]),
        ("WO2019EP84487 20191210", 2019, [(APP, "WO2019084487")]),
        # Plusieurs numéros.
        ("N°WO2018002556 A1 N°FR3053353", 2018, [(PUB, "WO2018002556"), (PUB, "FR3053353")]),
        (
            "Brevet national N° FR2017050584. Brevet international N° WO2017158284 (2019-09-21)",
            2017,
            [(APP, "WO2017050584"), (PUB, "WO2017158284")],
        ),
        (
            "WO 2021/064186 A1 / EP 4037770 A1 (US 12351556 B2 ; JP 7646643 B2)",
            2021,
            [(PUB, "WO2021064186"), (PUB, "EP4037770"), (PUB, "US12351556"), (PUB, "JP7646643")],
        ),
        ("B-025149FR01_2021-12-24 FR3131453 (A1) 2023-06-30", 2023, [(PUB, "FR3131453")]),
        ("Application No. EP16162941.5, Patent No. 1360", 2017, [(APP, "EP16162941")]),
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
    assert read_patent_numbers("FR2957077", 2011) == [ReadPatentNumber(PUB, "FR2957077")]


def test_doublons_retires():
    assert read_patent_numbers("FR1908401 FR 1908401", 2019) == [ReadPatentNumber(APP, "FR1908401")]
