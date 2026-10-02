"""Import des frais de publication : lecture des fichiers Open APC et des frais hors OA.

Les tests portent sur ce que la lecture tire de chaque format — montants, années, payeur, type de frais — et sur ce qu'elle refuse de prendre pour un DOI. L'écriture en base a son épreuve d'intégration.
"""

import pytest

from application.ports.pipeline.affiliations.address_resolution import StructureNameForm
from domain.structures.structure import StructureType
from interfaces.cli.imports.import_apc import (
    LAB_TYPES,
    PAYER_TYPES,
    FileFormat,
    StructureResolver,
    detect_format,
    non_oa_fee_payment,
    open_apc_payment,
    parse_amount,
    parse_year,
    read_payments,
)


class TestParseAmount:
    @pytest.mark.parametrize(
        ("cellule", "attendu"),
        [
            ("1234.56", 1234.56),
            ("1 234,56", 1234.56),
            ("1 234,56", 1234.56),
            ("1 100,00", 1100.0),
            ("437,76", 437.76),
        ],
    )
    def test_formats_francais_et_anglais(self, cellule, attendu):
        assert parse_amount(cellule) == attendu

    @pytest.mark.parametrize("cellule", [None, "", "na", "non identifié"])
    def test_absence_de_montant(self, cellule):
        assert parse_amount(cellule) is None


class TestParseYear:
    def test_annee_plausible(self):
        assert parse_year(" 2021 ") == 2021

    @pytest.mark.parametrize("cellule", [None, "", "1890", "2201", "2021-22"])
    def test_annee_refusee(self, cellule):
        assert parse_year(cellule) is None


class TestDetectFormat:
    def test_open_apc(self):
        assert detect_format(["institution", "period", "euro", "doi"]) is FileFormat.OPEN_APC

    def test_frais_hors_oa(self):
        assert (
            detect_format(["Laboratoire", "DOI", "Montant payé en EURHT"]) is FileFormat.NON_OA_FEES
        )

    def test_format_inconnu(self):
        with pytest.raises(ValueError, match="Format inconnu"):
            detect_format(["DOI", "MontantEURHT"])


class TestOpenApcPayment:
    _ROW = {
        "institution": "Université Clermont Auvergne",
        "period": "2023",
        "euro": "1850.5",
        "doi": "https://doi.org/10.1/ABC",
        "is_hybrid": "TRUE",
        "publisher": "Elsevier BV",
        "journal_full_title": "Journal X",
        "issn": "",
        "issn_l": "1234-5678",
    }

    def test_paiement_complet(self):
        payment = open_apc_payment(self._ROW)
        assert payment["doi"] == "10.1/abc"
        assert payment["amount_eur_ht"] == 1850.5
        assert (payment["billing_year"], payment["pub_year"]) == (2023, 2023)
        assert payment["institution"] == "Université Clermont Auvergne"
        assert payment["issn"] == "1234-5678"
        assert payment["remarks"] == "hybrid"
        assert payment["open_access_fee"] is True


class TestNonOaFeePayment:
    _ROW = {
        "Laboratoire": "Laboratoire de Météorologie Physique",
        "Editeur": "Wiley",
        "Revue": "JGR Atmospheres",
        "ISSN": "2169-897X",
        "DOI": "10.1029/2021JD035438",
        "Montant payé en EURHT": "997,65",
        "Année de facturation": "2022",
        "Année de publication": "2022",
        "Budget": "Université Clermont Auvergne",
        "CoMan Id.": "200",
        "Remarques": "",
    }

    def test_paiement_complet(self):
        payment = non_oa_fee_payment(self._ROW)
        assert payment["doi"] == "10.1029/2021jd035438"
        assert payment["amount_eur_ht"] == 997.65
        assert payment["institution"] == payment["budget"] == "Université Clermont Auvergne"
        assert payment["coman_id"] == 200
        assert payment["lab_name"] == "Laboratoire de Météorologie Physique"
        assert payment["open_access_fee"] is False

    @pytest.mark.parametrize("mention", ["inconnu", "pas de doi", "non publié"])
    def test_mention_d_absence_ne_vaut_pas_un_doi(self, mention):
        assert non_oa_fee_payment({**self._ROW, "DOI": mention})["doi"] is None


class TestStructureResolver:
    _UCA, _LMV, _CNRS = 1, 2, 3
    _FORMS = [
        StructureNameForm(
            1, _UCA, "universite clermont auvergne", False, None, False, StructureType.UNIVERSITE
        ),
        StructureNameForm(2, _LMV, "lmv", True, [_UCA], False, StructureType.LABO),
        StructureNameForm(
            3, _LMV, "laboratoire magmas et volcans", False, None, False, StructureType.LABO
        ),
        StructureNameForm(4, _CNRS, "cnrs", True, None, False, StructureType.ONR),
    ]

    def test_laboratoire_reconnu_par_son_nom(self):
        resolver = StructureResolver(self._FORMS)
        assert resolver.resolve("Laboratoire Magmas et Volcans / LMV", LAB_TYPES) == self._LMV

    def test_le_payeur_satisfait_le_contexte_d_une_forme(self):
        resolver = StructureResolver(self._FORMS)
        assert resolver.resolve("LMV", LAB_TYPES) is None
        assert resolver.resolve("LMV", LAB_TYPES, "Université Clermont Auvergne") == self._LMV

    def test_seuls_les_types_demandes_comptent(self):
        resolver = StructureResolver(self._FORMS)
        assert resolver.resolve("CNRS - Centre national", PAYER_TYPES) == self._CNRS
        assert resolver.resolve("CNRS - Centre national", LAB_TYPES) is None

    def test_plusieurs_structures_ne_designent_aucune(self):
        resolver = StructureResolver(self._FORMS)
        assert resolver.resolve("CNRS / Université Clermont Auvergne", PAYER_TYPES) is None


def test_read_payments_reconnait_le_format(tmp_path):
    path = tmp_path / "apc_de.csv"
    path.write_text(
        "institution,period,euro,doi,is_hybrid\nUniversité Clermont Auvergne,2023,100,10.1/a,FALSE\n",
        encoding="utf-8",
    )
    file_format, payments = read_payments(path)
    assert file_format is FileFormat.OPEN_APC
    assert [p["doi"] for p in payments] == ["10.1/a"]
