"""Import des paiements de frais de publication : lecture des deux fichiers d'enquête.

Deux fichiers de formats distincts alimentent la même table : l'enquête principale et le relevé des frais hors accès ouvert, dont les intitulés de colonnes diffèrent. Les tests portent sur ce que la lecture en tire — montants au format français, années bornées, identifiant de comptabilité numérique — et sur ce qu'elle refuse de prendre pour un DOI.

Les requêtes couplées au schéma ont leur propre épreuve, sur base ; ici, la connexion est doublée.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from interfaces.cli.imports import import_apc
from interfaces.cli.imports.import_apc import (
    import_fp_hors_oa,
    import_main_file,
    main,
    parse_amount,
    parse_year,
)


class _FakeConnection:
    """Retient les lots passés à l'insertion."""

    def __init__(self) -> None:
        self.lots: list[list[dict]] = []

    def execute(self, statement, rows=None):
        self.lots.append(rows)


class TestParseAmount:
    @pytest.mark.parametrize(
        ("cellule", "attendu"),
        [
            ("1234.56", 1234.56),
            ("1 234,56", 1234.56),  # espace insécable des tableurs français
            ("1234,56", 1234.56),
            ("1 234,56", 1234.56),
        ],
    )
    def test_montants_au_format_francais(self, cellule, attendu):
        assert parse_amount(cellule) == attendu

    @pytest.mark.parametrize("cellule", ["", "  ", "NA", "na", "Non identifié", "abc"])
    def test_absence_de_montant(self, cellule):
        assert parse_amount(cellule) is None


class TestParseYear:
    def test_annee_plausible(self):
        assert parse_year("2024") == 2024
        assert parse_year(" 2024 ") == 2024

    @pytest.mark.parametrize("cellule", ["", "1989", "2101", "vingt", "20a4"])
    def test_annee_refusee(self, cellule):
        """Hors de l'intervalle plausible ou non numérique : la donnée est tenue pour absente."""
        assert parse_year(cellule) is None


_ENTETE_PRINCIPAL = (
    "Laboratoire,Editeur,TypeEditeur,Revue,Issn_l,TypeRevue,DOI,TitreArticle,"
    "MontantEURHT,AnneeFacturation,AnneePublication,Budget,Etablissement,"
    "TypeEtablissement,CoManId,EtablissementsRepondantsAToutesLesEnquetes,"
    "PaiementPartage,Remarques"
)


def _fichier_principal(tmp_path, lignes: list[str], monkeypatch) -> None:
    (tmp_path / "APC_2026.csv").write_text(
        "\n".join([_ENTETE_PRINCIPAL, *lignes]) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(import_apc, "DATA_DIR", tmp_path)


class TestImportMainFile:
    def test_ligne_lue_et_versee(self, tmp_path, monkeypatch):
        _fichier_principal(
            tmp_path,
            [
                (
                    "LMBP,Elsevier,Commercial,J. Things,1234-5678,Hybride,10.1/a,Un titre,"
                    '"1 234,56",2024,2023,Budget A,CNRS,EPST,4321,oui,non,RAS'
                )
            ],
            monkeypatch,
        )
        conn = _FakeConnection()

        assert import_main_file(conn) == 1
        (ligne,) = conn.lots[0]
        assert ligne["lab_name"] == "LMBP"
        assert ligne["doi"] == "10.1/a"
        assert ligne["amount_eur_ht"] == 1234.56
        assert ligne["billing_year"] == 2024
        assert ligne["pub_year"] == 2023
        assert ligne["coman_id"] == 4321
        assert ligne["source_file"] == "enquete_apc"

    @pytest.mark.parametrize("mention", ["non identifié", "NA"])
    def test_mention_d_absence_ne_vaut_pas_un_doi(self, mention, tmp_path, monkeypatch):
        """Le fichier note l'absence de DOI en toutes lettres : la colonne reste vide."""
        _fichier_principal(tmp_path, [f"LMBP,,,,,,{mention},,,,,,,,,,,"], monkeypatch)
        conn = _FakeConnection()

        import_main_file(conn)

        assert conn.lots[0][0]["doi"] is None

    def test_identifiant_de_comptabilite_non_numerique(self, tmp_path, monkeypatch):
        _fichier_principal(tmp_path, ["LMBP,,,,,,,,,,,,,,inconnu,,,"], monkeypatch)
        conn = _FakeConnection()

        import_main_file(conn)

        assert conn.lots[0][0]["coman_id"] is None

    def test_sans_fichier_rien_n_est_importe(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(import_apc, "DATA_DIR", tmp_path)
        conn = _FakeConnection()

        assert import_main_file(conn) == 0
        assert conn.lots == []
        assert "introuvable" in capsys.readouterr().out


class TestImportFpHorsOa:
    def test_sans_fichier_rien_n_est_importe(self, tmp_path, monkeypatch):
        monkeypatch.setattr(import_apc, "DATA_DIR", tmp_path)
        conn = _FakeConnection()

        assert import_fp_hors_oa(conn) == 0
        assert conn.lots == []

    def test_mention_d_absence_ne_vaut_pas_un_doi(self, tmp_path, monkeypatch):
        entete = "DOI,Montant payé en EURHT"
        (tmp_path / "FP hors OA.csv").write_text(entete + "\nnon identifié,800\n", encoding="utf-8")
        monkeypatch.setattr(import_apc, "DATA_DIR", tmp_path)
        conn = _FakeConnection()

        import_fp_hors_oa(conn)

        assert conn.lots[0][0]["doi"] is None

    def test_intitules_propres_a_ce_fichier(self, tmp_path, monkeypatch):
        """Les colonnes portent d'autres noms que l'enquête principale, et l'établissement y manque."""
        entete = (
            "Laboratoire,Editeur,Type d'éditeur*,Revue,ISSN,Type de revue*,DOI,"
            "Montant payé en EURHT,Année de facturation,Année de publication,Budget,"
            "Type d'établissement,CoMan Id.,Nature de la dépense*,Remarques"
        )
        (tmp_path / "FP hors OA.csv").write_text(
            entete + "\nLMBP,Wiley,Commercial,J. Things,1234-5678,Hybride,10.1/b,"
            "800,2024,2024,Budget B,EPST,99,Frais de publication,RAS\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(import_apc, "DATA_DIR", tmp_path)
        conn = _FakeConnection()

        assert import_fp_hors_oa(conn) == 1
        (ligne,) = conn.lots[0]
        assert ligne["publisher_type"] == "Commercial"
        assert ligne["expense_type"] == "Frais de publication"
        assert ligne["amount_eur_ht"] == 800
        assert ligne["coman_id"] == 99
        assert ligne["institution"] is None  # ce fichier ne porte pas la colonne
        assert ligne["source_file"] == "fp_hors_oa"


class _FakeResult:
    """Résultat d'une requête d'écriture ou de dénombrement."""

    rowcount = 3

    def one(self):
        return SimpleNamespace(total=10, with_pub=7, with_journal=6, with_publisher=5)


class _FakeMainConnection:
    """Connexion du script : retient les ordres SQL émis, sans rien exécuter."""

    def __init__(self) -> None:
        self.ordres: list[str] = []

    def execute(self, statement, rows=None):
        self.ordres.append(str(statement).strip().split()[0].upper())
        return _FakeResult()

    @contextmanager
    def begin(self):
        yield self


class _FakeEngine:
    def __init__(self, conn) -> None:
        self._conn = conn

    @contextmanager
    def connect(self):
        yield self._conn


def test_main_enchaine_vidage_imports_et_rapprochements(tmp_path, monkeypatch, capsys):
    """Le script vide la table avant d'importer : il se rejoue sans empiler les doublons."""
    monkeypatch.setattr(import_apc, "DATA_DIR", tmp_path)  # aucun fichier : les imports rendent 0
    conn = _FakeMainConnection()
    monkeypatch.setattr(import_apc, "get_sync_engine", lambda: _FakeEngine(conn))

    main()

    assert conn.ordres[0] == "TRUNCATE"
    assert conn.ordres.count("UPDATE") == 3  # DOI, ISSN, éditeurs
    sortie = capsys.readouterr().out
    assert "Total: 10 lignes" in sortie
