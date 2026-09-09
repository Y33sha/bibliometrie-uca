"""Avancement d'une boucle : barre en terminal, jalons au journal sinon."""

import io
import logging

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
