"""Avancement d'une boucle : barre en terminal, jalons au journal sinon."""

import io
import logging
import time

import pytest

from application.pipeline import progression as module


@pytest.fixture
def sans_terminal(monkeypatch):
    monkeypatch.setattr(module.sys.stdout, "isatty", lambda: False, raising=False)


@pytest.fixture
def avec_terminal(monkeypatch):
    monkeypatch.setattr(module.sys.stdout, "isatty", lambda: True, raising=False)


class TestSansTerminal:
    """Sortie capturée : le journal reçoit des jalons, jamais de retour chariot."""

    def test_aucune_barre_n_est_ouverte(self, sans_terminal, caplog):
        with module.progression(10, "hal", logging.getLogger(__name__)) as p:
            assert p._barre is None

    def test_le_premier_jalon_attend_l_intervalle(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.progression(100, "hal", logging.getLogger(__name__), intervalle_s=3600) as p,
        ):
            p.avance(50)
        assert caplog.records == []

    def test_un_jalon_porte_l_avancement_et_le_debit(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.progression(100, "hal", logging.getLogger(__name__), intervalle_s=0) as p,
        ):
            p.avance(25)
        assert "hal : 25/100 (25 %)" in caplog.text
        assert "/s" in caplog.text

    def test_les_jalons_prennent_le_libelle_du_perimetre_en_cours(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.progression(100, "hal 2023", logging.getLogger(__name__), intervalle_s=0) as p,
        ):
            p.renomme("hal 2024")
            p.avance(25)
        assert "hal 2024 : 25/100" in caplog.text

    def test_un_total_nul_n_affiche_pas_de_part(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.progression(0, "hal", logging.getLogger(__name__), intervalle_s=0) as p,
        ):
            p.avance(3)
        assert "%" not in caplog.text


class TestAvecTerminal:
    """Terminal : la barre porte l'avancement, le journal reste muet."""

    def test_la_barre_est_ouverte(self, avec_terminal):
        with module.progression(10, "hal", logging.getLogger(__name__)) as p:
            assert p._barre is not None

    def test_le_journal_ne_recoit_aucun_jalon(self, avec_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.progression(10, "hal", logging.getLogger(__name__), intervalle_s=0) as p,
        ):
            p.avance(5)
        assert caplog.records == []

    def test_la_barre_prend_le_libelle_du_perimetre_en_cours(self, avec_terminal):
        with module.progression(10, "hal 2023", None) as p:
            p.renomme("hal 2024")
            assert p._barre.desc == "hal 2024"

    def test_la_barre_est_refermee_a_la_sortie(self, avec_terminal):
        with module.progression(10, "hal", logging.getLogger(__name__)) as p:
            barre = p._barre
        assert p._barre is None
        assert barre.disable or barre.n is not None


class TestSansLaBibliotheque:
    """L'absence de `tqdm` conduit au même repli que l'absence de terminal."""

    def test_les_jalons_prennent_le_relais(self, avec_terminal, caplog, monkeypatch):
        monkeypatch.setattr(module, "tqdm", None)
        with (
            caplog.at_level(logging.INFO),
            module.progression(100, "hal", logging.getLogger(__name__), intervalle_s=0) as p,
        ):
            assert p._barre is None
            p.avance(10)
        assert "hal : 10/100" in caplog.text


def test_une_exception_referme_la_barre(avec_terminal):
    """Le bloc rend la main proprement, même interrompu."""
    with (
        pytest.raises(RuntimeError),
        module.progression(10, "hal", logging.getLogger(__name__)) as p,
    ):
        raise RuntimeError("interruption")
    assert p._barre is None


class TestBarresConcurrentes:
    """`tqdm` empile les barres simultanées, chacune sur sa ligne."""

    def test_chaque_barre_prend_une_position_distincte(self, avec_terminal):
        with (
            module.progression(10, "hal", None) as premiere,
            module.progression(10, "openalex", None) as seconde,
        ):
            assert premiere._barre.pos != seconde._barre.pos

    def test_une_position_liberee_se_reprend(self, avec_terminal):
        with module.progression(10, "hal", None) as premiere:
            prise = premiere._barre.pos
        with module.progression(10, "openalex", None) as seconde:
            assert seconde._barre.pos == prise


class TestRedessinDeLaBarre:
    """La ligne réécrite en place emporte de quoi effacer le redessin précédent."""

    @staticmethod
    def _barre(flux: io.StringIO, largeur: int) -> "module._Barre":
        barre = module._Barre(
            total=100, desc="hal", bar_format=module.FORMAT_BARRE, file=flux, dynamic_ncols=True
        )
        barre.dynamic_ncols = lambda _: (largeur, 20)
        return barre

    @staticmethod
    def _redessine(barre: "module._Barre", flux: io.StringIO) -> str:
        """Vide le flux, redessine la barre, rend ce que le redessin a écrit."""
        flux.seek(0)
        flux.truncate(0)
        barre.refresh()
        return flux.getvalue()

    def test_le_redessin_tient_dans_la_largeur_du_terminal(self):
        """Des espaces jusqu'à la longueur du redessin précédent déborderaient d'un terminal rétréci."""
        flux = io.StringIO()
        with self._barre(flux, 80) as barre:
            self._redessine(barre, flux)
            barre.dynamic_ncols = lambda _: (40, 20)
            ecrit = self._redessine(barre, flux)
        assert module.disp_len(ecrit.strip("\r")) <= 40

    def test_le_curseur_revient_en_debut_de_ligne(self):
        """Un terminal replie la barre trop longue en gardant le curseur à sa place dans le texte : ramené au début, il reste sur la première ligne du repli, que le redessin suivant remplace."""
        flux = io.StringIO()
        with self._barre(flux, 80) as barre:
            ecrit = self._redessine(barre, flux)
        assert ecrit.startswith("\r")
        assert ecrit.endswith("\r")

    def test_une_largeur_stable_efface_la_fin_de_la_ligne(self):
        flux = io.StringIO()
        with self._barre(flux, 80) as barre:
            self._redessine(barre, flux)
            ecrit = self._redessine(barre, flux)
        assert module.EFFACE_FIN_DE_LIGNE in ecrit
        assert module.EFFACE_BAS_DE_L_ECRAN not in ecrit

    def test_la_barre_tient_dans_la_fenetre(self):
        """Une ligne plus longue que la fenêtre s'y replierait, décalant les barres voisines."""
        flux = io.StringIO()
        with self._barre(flux, 70) as barre:
            assert module.disp_len(str(barre)) <= 70

    def test_la_barre_ne_s_etire_pas_indefiniment(self):
        flux = io.StringIO()
        with self._barre(flux, 300) as barre:
            assert module.disp_len(str(barre)) == module.LARGEUR_LIGNE

    def test_deux_volumes_differents_donnent_la_meme_longueur(self):
        """Le compteur occupe une colonne fixe : ce qui reste au remplissage l'est aussi."""
        flux = io.StringIO()
        with self._barre(flux, 80) as petite, self._barre(flux, 80) as grande:
            petite.total = 19
            grande.total = 435758
            assert module.disp_len(str(petite)) == module.disp_len(str(grande))

    def test_un_terminal_retreci_efface_jusqu_au_bas_de_l_ecran(self):
        """La barre trop longue s'y replie sur plusieurs lignes, toutes à effacer."""
        flux = io.StringIO()
        with self._barre(flux, 80) as barre:
            self._redessine(barre, flux)
            barre.dynamic_ncols = lambda _: (40, 20)
            ecrit = self._redessine(barre, flux)
        assert module.EFFACE_BAS_DE_L_ECRAN in ecrit


class TestEcritureHorsBarre:
    """Une ligne écrite pendant qu'une barre tourne passe au-dessus d'elle."""

    def test_la_ligne_part_sur_le_flux_donne(self):
        flux = io.StringIO()
        module.ecrire_hors_barre("erreur sur hal-05614798", flux)
        assert "erreur sur hal-05614798" in flux.getvalue()

    def test_sans_la_bibliotheque_la_ligne_part_quand_meme(self, monkeypatch):
        monkeypatch.setattr(module, "tqdm", None)
        flux = io.StringIO()
        module.ecrire_hors_barre("erreur sur hal-05614798", flux)
        assert "erreur sur hal-05614798" in flux.getvalue()

    def test_le_terminal_recoit_de_quoi_effacer_la_fin_de_ligne(self, avec_terminal):
        """La ligne emporte de quoi effacer la fin de la barre dont elle prend la place."""
        flux = io.StringIO()
        module.ecrire_hors_barre("[HAL · 2018] 13 nouveaux", flux)
        assert module.EFFACE_FIN_DE_LIGNE in flux.getvalue()

    def test_une_sortie_capturee_reste_sans_sequence_d_effacement(self, sans_terminal):
        """Un fichier de journal porterait la séquence telle quelle."""
        flux = io.StringIO()
        module.ecrire_hors_barre("[HAL · 2018] 13 nouveaux", flux)
        assert module.EFFACE_FIN_DE_LIGNE not in flux.getvalue()


class TestCompteurDeRetenus:
    """Le compteur porte les éléments retenus ; le remplissage suit les éléments parcourus."""

    def test_le_compteur_part_de_zero(self, avec_terminal):
        with module.progression(25, "HAL", None, compte_retenus=True) as p:
            assert p._barre.retenus == 0

    def test_le_compteur_suit_les_retenus_et_la_barre_les_parcourus(self, avec_terminal):
        with module.progression(25, "HAL", None, compte_retenus=True) as p:
            for i in range(25):
                p.avance()
                if i < 14:
                    p.retient()
            assert p._barre.retenus == 14
            assert p._barre.n == 25

    def test_le_format_montre_les_retenus_sur_le_total(self, avec_terminal):
        with module.progression(25, "HAL", None, compte_retenus=True) as p:
            p.avance(25)
            p.retient(14)
            rendu = p._barre.format_meter(**p._barre.format_dict)
        assert "14/25" in rendu

    def test_sans_compteur_la_barre_montre_les_parcourus(self, avec_terminal):
        with module.progression(25, "HAL", None) as p:
            p.avance(25)
            rendu = p._barre.format_meter(**p._barre.format_dict)
        assert "25/25" in rendu

    def test_le_compteur_tient_sans_barre(self, sans_terminal):
        """Une sortie capturée compte les retenus sans rien afficher."""
        with module.progression(25, "HAL", None, compte_retenus=True) as p:
            p.retient(3)
            assert p._retenus == 3


class TestAttente:
    """Un travail dont l'avancement ne se mesure pas : maintenance des tables, VACUUM."""

    def test_le_terminal_recoit_le_libelle_sur_une_ligne_reecrite(self, avec_terminal, monkeypatch):
        flux = io.StringIO()
        monkeypatch.setattr(module, "_flux_barres", flux)
        with module.attente("maintenance des tables", None):
            pass
        ecrit = flux.getvalue()
        assert ecrit.startswith("\rmaintenance des tables")
        assert ecrit.endswith("\n")

    def test_les_points_courent_pendant_le_travail(self, avec_terminal, monkeypatch):
        flux = io.StringIO()
        monkeypatch.setattr(module, "_flux_barres", flux)
        monkeypatch.setattr(module, "RAFRAICHISSEMENT_ATTENTE_S", 0.01)
        with module.attente("maintenance des tables", None):
            time.sleep(0.08)
        assert "maintenance des tables..." in flux.getvalue()

    def test_la_conclusion_efface_la_fin_du_libelle(self, avec_terminal, monkeypatch):
        """Plus courte que le libellé dont elle prend la place, elle en laisserait la fin derrière elle."""
        flux = io.StringIO()
        monkeypatch.setattr(module, "_flux_barres", flux)
        with module.attente("mise à jour en cours", None) as ligne:
            ligne.conclut("Terminé en 12.3s")
        assert flux.getvalue().endswith(f"Terminé en 12.3s{module.EFFACE_FIN_DE_LIGNE}\n")

    def test_une_sortie_capturee_recoit_une_ligne_de_journal(self, sans_terminal, caplog):
        with caplog.at_level(logging.INFO), module.attente("maintenance des tables", _log()):
            pass
        assert "maintenance des tables…" in caplog.text

    def test_une_exception_arrete_les_points(self, avec_terminal, monkeypatch):
        flux = io.StringIO()
        monkeypatch.setattr(module, "_flux_barres", flux)
        with pytest.raises(RuntimeError), module.attente("maintenance des tables", None):
            raise RuntimeError("VACUUM en échec")
        assert flux.getvalue().endswith("\n")


def _log() -> logging.Logger:
    return logging.getLogger(__name__)
