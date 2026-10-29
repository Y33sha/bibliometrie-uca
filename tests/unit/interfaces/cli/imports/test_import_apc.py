"""Import des frais de publication : lecture des fichiers Open APC, des frais hors OA et des réponses à l'enquête APC.

Ces tests vérifient ce que la lecture extrait de chaque format (montants, années, payeur, type de frais) et ce qu'elle refuse comme DOI. L'écriture en base a son test d'intégration.
"""

import pytest

from domain.structures.structure import StructureType
from interfaces.cli.imports.import_apc import (
    LAB_TYPES,
    PAYER_TYPES,
    FileFormat,
    StructureResolver,
    detect_format,
    institution_filter,
    institution_survey_payment,
    institution_survey_payments,
    non_oa_fee_payment,
    open_apc_payment,
    parse_amount,
    parse_year,
    read_payments,
)
from pipeline.transformation.structures.name_recognition import MatchableNameForm


class TestInstitutionFilter:
    """L'établissement se désigne par son nom (Open APC), son coman_id (frais hors OA) ou son ROR (réponse à l'enquête)."""

    def test_nom_open_apc_sans_casse_ni_accents(self):
        ours = institution_filter(FileFormat.OPEN_APC, "Université Clermont Auvergne")
        assert ours({"institution": "Universite clermont auvergne"})
        assert not ours({"institution": "CNRS"})
        assert not ours({"institution": None})

    def test_coman_id_des_frais_hors_oa(self):
        ours = institution_filter(FileFormat.NON_OA_FEES, "200")
        assert ours({"coman_id": 200})
        assert not ours({"coman_id": 271})

    def test_ror_de_la_reponse_a_l_enquete(self):
        ours = institution_filter(FileFormat.INSTITUTION_SURVEY, "https://ror.org/01a8ajp46")
        assert ours({"payer_ror": "01a8ajp46"})
        assert not ours({"payer_ror": "02feahw73"})

    @pytest.mark.parametrize(
        ("file_format", "value"),
        [(FileFormat.NON_OA_FEES, "Université"), (FileFormat.INSTITUTION_SURVEY, "pas un ROR")],
    )
    def test_valeur_illisible_refusee(self, file_format, value):
        with pytest.raises(ValueError):
            institution_filter(file_format, value)


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
        assert (payment["billing_year"], payment["publication_year"]) == (2023, 2023)
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
        MatchableNameForm(
            1, _UCA, "universite clermont auvergne", False, None, False, StructureType.UNIVERSITE
        ),
        MatchableNameForm(2, _LMV, "lmv", True, [_UCA], False, StructureType.LABO),
        MatchableNameForm(
            3, _LMV, "laboratoire magmas et volcans", False, None, False, StructureType.LABO
        ),
        MatchableNameForm(4, _CNRS, "cnrs", True, None, False, StructureType.ONR),
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


class TestInstitutionSurvey:
    _HEADER = "laboratoire_sigle,doi,montant_euros_ht,ror,budget,année_facturation,commentaire,Réponse Couperin"

    @staticmethod
    def _row(lab: str, doi: str, amount: str, comment: str = "", couperin: str = "") -> dict:
        return {
            "laboratoire_sigle": lab,
            "doi": doi,
            "montant_euros_ht": amount,
            "ror": "https://ror.org/01a8ajp46",
            "budget": "",
            "année_facturation": "2025",
            "commentaire": comment,
            "Réponse Couperin": couperin,
        }

    def test_detect_format(self):
        assert detect_format(self._HEADER.split(",")) is FileFormat.INSTITUTION_SURVEY

    def test_paiement_complet(self):
        payment = institution_survey_payment(
            self._row("NEURO-DOL ", " 10.3390/BIOM15050740.", "2 883,13", "Co-écrit", "Retenu"),
            open_access_fee=True,
        )
        assert payment["doi"] == "10.3390/biom15050740"
        assert payment["amount_eur_ht"] == 2883.13
        assert payment["billing_year"] == 2025
        assert payment["publication_year"] is None
        assert payment["payer_ror"] == "01a8ajp46"
        assert payment["lab_name"] == "NEURO-DOL"
        assert payment["remarks"] == "Co-écrit — Couperin : Retenu"

    def test_sections(self):
        rows = [
            self._row("LMGE", "10.1/a", "100"),
            self._row("", "", "100"),
            self._row("Pas d'APC mais des frais de publication", "", ""),
            self._row("ICCF", "10.1/b", "200"),
            self._row("Retour Couperin", "", ""),
            self._row("MEDIS", "10.1/c", "300"),
        ]
        payments = institution_survey_payments(rows)
        assert [(p["doi"], p["open_access_fee"]) for p in payments] == [
            ("10.1/a", True),
            ("10.1/b", False),
        ]

    def test_un_montant_negatif_annule_un_paiement_de_meme_valeur(self):
        rows = [
            self._row("IMoST", "10.1/a", "-2390"),
            self._row("IMoST", "10.1/a", "2390"),
            self._row("IMoST", "10.1/a", "2390"),
            self._row("IMoST", "10.1/a", "-55"),
            self._row("IMoST", "10.1/a", "55"),
            self._row("IMoST", "10.1/a", "55"),
            self._row("M2iSH", "10.1/b", "-2481,64"),
            self._row("M2iSH", "10.1/b", "2436"),
            self._row("M2iSH", "10.1/b", "2481,64"),
        ]
        payments = institution_survey_payments(rows)
        assert [(p["doi"], p["amount_eur_ht"]) for p in payments] == [
            ("10.1/a", 2390.0),
            ("10.1/a", 55.0),
            ("10.1/b", 2436.0),
        ]

    def test_paiements_scindes_conserves(self):
        rows = [self._row("LPC", "10.1/a", "3000"), self._row("LPC", "10.1/a", "565,62")]
        assert [p["amount_eur_ht"] for p in institution_survey_payments(rows)] == [3000.0, 565.62]

    def test_preambule_avant_l_en_tete(self, tmp_path):
        path = tmp_path / "apc_2025.csv"
        path.write_text(
            ",,,,,,,\nEnquête APC 2025,,,,,,,\n"
            + self._HEADER
            + "\nLMGE,10.1/a,100,https://ror.org/01a8ajp46,,2025,,\n",
            encoding="utf-8",
        )
        file_format, payments = read_payments(path)
        assert file_format is FileFormat.INSTITUTION_SURVEY
        assert [p["doi"] for p in payments] == ["10.1/a"]


def test_read_payments_reconnait_le_format(tmp_path):
    path = tmp_path / "apc_de.csv"
    path.write_text(
        "institution,period,euro,doi,is_hybrid\nUniversité Clermont Auvergne,2023,100,10.1/a,FALSE\n",
        encoding="utf-8",
    )
    file_format, payments = read_payments(path)
    assert file_format is FileFormat.OPEN_APC
    assert [p["doi"] for p in payments] == ["10.1/a"]
