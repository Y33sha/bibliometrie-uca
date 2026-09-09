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
