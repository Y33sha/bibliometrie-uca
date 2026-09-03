"""Import Open APC : ne retenir que les paiements portant sur des publications connues.

Le jeu de données recense les frais de publication payés par des établissements du monde entier. L'import n'en garde que les lignes dont le DOI figure déjà dans le corpus, et il ne réécrit pas un paiement déjà enregistré — il se rejoue donc sans empiler les doublons.
"""

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from interfaces.cli.imports import import_openapc
from interfaces.cli.imports.import_openapc import build_payment, main

_ENTETE = "doi,euro,period,publisher,journal_full_title,issn,issn_l,institution,is_hybrid"


class TestBuildPayment:
    def _ligne(self, **surcharges) -> dict:
        base = {
            "doi": "10.1/a",
            "euro": "1234.56",
            "period": "2024",
            "publisher": "Elsevier",
            "journal_full_title": "J. Things",
            "issn": "1234-5678",
            "issn_l": "8765-4321",
            "institution": "Université de Nulle Part",
            "is_hybrid": "FALSE",
        }
        return {**base, **surcharges}

    def test_paiement_complet(self):
        paiement = build_payment(
            self._ligne(), doi="10.1/a", publication_id=7, source_file="apc_de.csv"
        )

        assert paiement["amount"] == 1234.56
        assert paiement["billing_year"] == 2024
        assert paiement["pub_year"] == 2024  # la période déclarée tient lieu des deux années
        assert paiement["issn"] == "1234-5678"
        assert paiement["pub_id"] == 7
        assert paiement["source_file"] == "apc_de.csv"
        assert paiement["remarks"] is None

    def test_montant_a_virgule_decimale(self):
        paiement = build_payment(
            self._ligne(euro="1234,56"), doi="10.1/a", publication_id=7, source_file="f"
        )

        assert paiement["amount"] == 1234.56

    @pytest.mark.parametrize("cellule", ["", "n/a"])
    def test_montant_illisible(self, cellule):
        paiement = build_payment(
            self._ligne(euro=cellule), doi="10.1/a", publication_id=7, source_file="f"
        )

        assert paiement["amount"] is None

    def test_periode_illisible(self):
        paiement = build_payment(
            self._ligne(period="inconnue"), doi="10.1/a", publication_id=7, source_file="f"
        )

        assert paiement["billing_year"] is None
        assert paiement["pub_year"] is None

    def test_issn_de_liaison_a_defaut_de_l_issn(self):
        paiement = build_payment(
            self._ligne(issn=""), doi="10.1/a", publication_id=7, source_file="f"
        )

        assert paiement["issn"] == "8765-4321"

    def test_revue_hybride_signalee(self):
        paiement = build_payment(
            self._ligne(is_hybrid="TRUE"), doi="10.1/a", publication_id=7, source_file="f"
        )

        assert paiement["remarks"] == "hybrid"


class _FakeConnection:
    """Rend le corpus et les paiements déjà connus, et retient les insertions."""

    def __init__(self, dois_connus: dict[str, int], deja_payes: list[str]) -> None:
        self._reponses = [
            [SimpleNamespace(doi=doi, id=pub_id) for doi, pub_id in dois_connus.items()],
            [(doi,) for doi in deja_payes],
        ]
        self.insertions: list[dict] = []

    def execute(self, statement, params=None):
        if self._reponses:
            return self._reponses.pop(0)
        self.insertions.append(params)
        return None

    @contextmanager
    def begin(self):
        yield self


class TestMain:
    @pytest.fixture
    def lancer(self, tmp_path, monkeypatch):
        """Écrit un fichier Open APC et lance le script dessus."""

        def _lancer(lignes: list[str], *, dois_connus=None, deja_payes=(), arguments=()):
            chemin = tmp_path / "apc_de.csv"
            chemin.write_text("\n".join([_ENTETE, *lignes]) + "\n", encoding="utf-8")
            conn = _FakeConnection(dois_connus or {}, list(deja_payes))
            monkeypatch.setattr(
                import_openapc,
                "get_sync_engine",
                lambda: SimpleNamespace(connect=lambda: _contexte(conn)),
            )
            monkeypatch.setattr(sys, "argv", ["import_openapc", str(chemin), *arguments])
            main()
            return conn

        @contextmanager
        def _contexte(conn):
            yield conn

        return _lancer

    def test_seuls_les_doi_du_corpus_sont_retenus(self, lancer):
        conn = lancer(
            ["10.1/connu,100,2024,Elsevier,J,1234-5678,,Univ,FALSE", "10.1/inconnu,200,2024,,,,,,"],
            dois_connus={"10.1/connu": 7},
        )

        assert [i["doi"] for i in conn.insertions] == ["10.1/connu"]
        assert conn.insertions[0]["pub_id"] == 7

    def test_paiement_deja_enregistre_non_reecrit(self, lancer):
        """Le script se rejoue sur un fichier déjà importé sans dupliquer ses lignes."""
        conn = lancer(
            ["10.1/connu,100,2024,,,,,,"],
            dois_connus={"10.1/connu": 7},
            deja_payes=["10.1/connu"],
        )

        assert conn.insertions == []

    def test_ligne_sans_doi_ignoree(self, lancer):
        conn = lancer([",100,2024,,,,,,"], dois_connus={"10.1/connu": 7})

        assert conn.insertions == []

    def test_simulation_n_insere_rien(self, lancer):
        conn = lancer(
            ["10.1/connu,100,2024,,,,,,"],
            dois_connus={"10.1/connu": 7},
            arguments=["--dry-run"],
        )

        assert conn.insertions == []
