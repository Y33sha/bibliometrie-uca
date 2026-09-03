"""Amorçage du préfixe DOI des revues, déduit des DOI de leurs publications.

Un éditeur attribue à chaque revue un fragment de DOI qui lui est propre : `10.1080/10408398` chez Taylor & Francis, par exemple. Ce fragment se retrouve en confrontant les DOI d'une même revue et en gardant leur début commun. Trois écueils le brouillent, et le script les traite : les dépôts de préprints, dont les DOI n'appartiennent pas à la revue ; les numéros d'article en fin de préfixe commun, variables d'un article à l'autre ; et les DOI de chapitres d'ouvrage, qui encodent un numéro international normalisé du livre.

Le préfixe qui ne distingue rien après la barre oblique désigne l'éditeur, non la revue : il est déclaré ambigu et reporté dans un fichier, pour arbitrage humain.
"""

import csv
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from interfaces.cli.maintenance import seed_journals_doi_prefix as module
from interfaces.cli.maintenance.seed_journals_doi_prefix import (
    is_ambiguous,
    is_outlier,
    lcp,
    main,
    trim_trailing_variable,
)


class TestIsOutlier:
    @pytest.mark.parametrize(
        "doi",
        [
            "10.1101/2024.01.01.573000",  # bioRxiv
            "10.48550/arxiv.2401.00001",
            "10.2139/ssrn.1234567",
            "10.5194/egusphere-2024-1",
        ],
    )
    def test_depots_de_preprints_ecartes(self, doi):
        assert is_outlier(doi) is True

    def test_revue_copernicus_conservee(self):
        """Seuls les préprints de cet éditeur sont écartés, pas ses revues."""
        assert is_outlier("10.5194/acp-24-1-2024") is False


class TestLcp:
    def test_debut_commun(self):
        assert lcp(["10.1080/10408398.2024.1", "10.1080/10408398.2023.7"]) == "10.1080/10408398.202"

    def test_aucun_debut_commun(self):
        assert lcp(["10.1080/a", "10.1234/b"]) == "10.1"

    def test_liste_vide(self):
        assert lcp([]) == ""

    def test_chaine_entierement_contenue_dans_l_autre(self):
        assert lcp(["10.1080/ab", "10.1080/abcd"]) == "10.1080/ab"


class TestTrimTrailingVariable:
    def test_numero_d_article_retire(self):
        assert trim_trailing_variable("10.1080/10408398.20") == "10.1080/10408398"

    def test_separateur_de_bord_retire(self):
        assert trim_trailing_variable("10.1007/s41597-") == "10.1007/s41597"

    def test_code_de_revue_numerique_preserve(self):
        """Le code d'une revue peut être un nombre : le retrait s'arrête au séparateur qui le suit.

        Le retrait porte sur ce que la comparaison des DOI a laissé de variable — ici l'année. Sans l'arrêt au séparateur, le code de la revue serait emporté avec.
        """
        commun = lcp(["10.1080/10408398.2024.1", "10.1080/10408398.2023.7"])

        assert trim_trailing_variable(commun) == "10.1080/10408398"


class TestIsAmbiguous:
    def test_prefixe_specifique_a_la_revue(self):
        assert is_ambiguous("10.1080/10408398") is False

    def test_sans_barre_oblique(self):
        """Le préfixe s'est effondré sur celui de l'éditeur, voire moins."""
        assert is_ambiguous("10.10") is True

    def test_rien_apres_la_barre_oblique(self):
        assert is_ambiguous("10.1080/") is True

    def test_numero_international_de_l_ouvrage(self):
        """Un DOI de chapitre encode le numéro du livre : ce n'est pas un identifiant de série."""
        assert is_ambiguous("10.1007/978-3-030") is True


class _FakeConnection:
    def __init__(self, journaux) -> None:
        self._journaux = journaux
        self.mises_a_jour: list[dict] = []
        self._premiere = True

    def execute(self, statement, params=None):
        if self._premiere:
            self._premiere = False
            return SimpleNamespace(all=lambda: self._journaux)
        self.mises_a_jour.append(params)
        return None

    @contextmanager
    def begin(self):
        yield self


def _journal(id_: int, titre: str, dois: list[str]):
    return SimpleNamespace(id=id_, title=titre, dois=dois)


class TestMain:
    @pytest.fixture
    def lancer(self, tmp_path, monkeypatch):
        """Lance le script sur un jeu de revues donné, et rend la connexion et le fichier produit."""

        @contextmanager
        def _contexte(conn):
            yield conn

        def _lancer(journaux, *arguments):
            conn = _FakeConnection(journaux)
            monkeypatch.setattr(
                module,
                "get_sync_engine",
                lambda: SimpleNamespace(connect=lambda: _contexte(conn)),
            )
            csv_out = tmp_path / "ambigus.csv"
            monkeypatch.setattr(
                sys,
                "argv",
                ["seed_journals_doi_prefix", "--csv-out", str(csv_out), *arguments],
            )
            main()
            return conn, csv_out

        return _lancer

    def test_prefixe_amorce(self, lancer):
        conn, _ = lancer(
            [_journal(1, "J. Things", ["10.1080/10408398.2024.1", "10.1080/10408398.2023.7"])]
        )

        assert conn.mises_a_jour == [{"p": "10.1080/10408398", "id": 1}]

    def test_revue_ambigue_reportee_sans_ecriture(self, lancer):
        conn, csv_out = lancer(
            [_journal(2, "Chapitres", ["10.1007/978-3-030-1", "10.1007/978-3-030-2"])]
        )

        assert conn.mises_a_jour == []
        (ligne,) = list(csv.DictReader(csv_out.open(encoding="utf-8")))
        assert ligne["journal_id"] == "2"
        assert ligne["title"] == "Chapitres"

    def test_revue_faite_de_preprints_reportee(self, lancer):
        """Tous ses DOI viennent d'un dépôt de préprints : rien à déduire, mais on en garde trace."""
        conn, csv_out = lancer(
            [_journal(3, "bioRxiv", ["10.1101/2024.01.01.1", "10.1101/2024.02.02.2"])]
        )

        assert conn.mises_a_jour == []
        (ligne,) = list(csv.DictReader(csv_out.open(encoding="utf-8")))
        assert ligne["n_filtered"] == "0"

    def test_simulation_n_ecrit_pas_en_base(self, lancer):
        conn, _ = lancer(
            [_journal(1, "J. Things", ["10.1080/10408398.2024.1", "10.1080/10408398.2023.7"])],
            "--dry-run",
        )

        assert conn.mises_a_jour == []

    def test_aucune_revue_a_analyser(self, lancer):
        conn, csv_out = lancer([])

        assert conn.mises_a_jour == []
        assert not csv_out.exists()  # aucun cas à arbitrer, aucun fichier produit
