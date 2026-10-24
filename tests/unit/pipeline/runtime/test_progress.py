"""Avancement d'une boucle : barre en terminal, jalons au journal sinon."""

import io
import logging
import time

import pytest

from pipeline.runtime.observability import progress as module


@pytest.fixture
def sans_terminal(monkeypatch):
    monkeypatch.setattr(module.sys.stdout, "isatty", lambda: False, raising=False)


@pytest.fixture
def avec_terminal(monkeypatch):
    monkeypatch.setattr(module.sys.stdout, "isatty", lambda: True, raising=False)


class TestSansTerminal:
    """Sortie capturée : le journal reçoit des jalons, jamais de retour chariot."""

    def test_aucune_barre_n_est_ouverte(self, sans_terminal, caplog):
        with module.track_progress(10, "hal", logging.getLogger(__name__)) as p:
            assert p._bar is None

    def test_le_premier_jalon_attend_l_intervalle(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.track_progress(100, "hal", logging.getLogger(__name__), interval_s=3600) as p,
        ):
            p.advance(50)
        assert caplog.records == []

    def test_un_jalon_porte_l_avancement_et_le_debit(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.track_progress(100, "hal", logging.getLogger(__name__), interval_s=0) as p,
        ):
            p.advance(25)
        assert "hal : 25/100 (25 %)" in caplog.text
        assert "/s" in caplog.text

    def test_les_jalons_prennent_le_libelle_du_perimetre_en_cours(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.track_progress(100, "hal 2023", logging.getLogger(__name__), interval_s=0) as p,
        ):
            p.relabel("hal 2024")
            p.advance(25)
        assert "hal 2024 : 25/100" in caplog.text

    def test_un_total_nul_n_affiche_pas_de_part(self, sans_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.track_progress(0, "hal", logging.getLogger(__name__), interval_s=0) as p,
        ):
            p.advance(3)
        assert "%" not in caplog.text


class TestAvecTerminal:
    """Terminal : la barre porte l'avancement, le journal reste muet."""

    def test_la_barre_est_ouverte(self, avec_terminal):
        with module.track_progress(10, "hal", logging.getLogger(__name__)) as p:
            assert p._bar is not None

    def test_le_journal_ne_recoit_aucun_jalon(self, avec_terminal, caplog):
        with (
            caplog.at_level(logging.INFO),
            module.track_progress(10, "hal", logging.getLogger(__name__), interval_s=0) as p,
        ):
            p.advance(5)
        assert caplog.records == []

    def test_la_barre_prend_le_libelle_du_perimetre_en_cours(self, avec_terminal):
        with module.track_progress(10, "hal 2023", None) as p:
            p.relabel("hal 2024")
            assert p._bar.desc == "hal 2024"

    def test_la_barre_est_refermee_a_la_sortie(self, avec_terminal):
        with module.track_progress(10, "hal", logging.getLogger(__name__)) as p:
            barre = p._bar
        assert p._bar is None
        assert barre.disable or barre.n is not None


class TestSansLaBibliotheque:
    """L'absence de `tqdm` conduit au même repli que l'absence de terminal."""

    def test_les_jalons_prennent_le_relais(self, avec_terminal, caplog, monkeypatch):
        for name in ("tqdm", "_Bar", "_KeptBar"):
            monkeypatch.setattr(module, name, None)
        with (
            caplog.at_level(logging.INFO),
            module.track_progress(100, "hal", logging.getLogger(__name__), interval_s=0) as p,
        ):
            assert p._bar is None
            p.advance(10)
        assert "hal : 10/100" in caplog.text


def test_une_exception_referme_la_barre(avec_terminal):
    """Le bloc rend la main proprement, même interrompu."""
    with (
        pytest.raises(RuntimeError),
        module.track_progress(10, "hal", logging.getLogger(__name__)) as p,
    ):
        raise RuntimeError("interruption")
    assert p._bar is None


class TestBarresConcurrentes:
    """`tqdm` empile les barres simultanées, chacune sur sa ligne."""

    def test_chaque_barre_prend_une_position_distincte(self, avec_terminal):
        with (
            module.track_progress(10, "hal", None) as premiere,
            module.track_progress(10, "openalex", None) as seconde,
        ):
            assert premiere._bar.pos != seconde._bar.pos

    def test_une_position_liberee_se_reprend(self, avec_terminal):
        with module.track_progress(10, "hal", None) as premiere:
            prise = premiere._bar.pos
        with module.track_progress(10, "openalex", None) as seconde:
            assert seconde._bar.pos == prise


class TestRedessinDeLaBarre:
    """La ligne réécrite en place emporte de quoi effacer le redessin précédent."""

    @staticmethod
    def _bar(stream: io.StringIO, largeur: int):
        assert module._Bar is not None
        barre = module._Bar(
            total=100, desc="hal", bar_format=module.BAR_FORMAT, file=stream, dynamic_ncols=True
        )
        barre.dynamic_ncols = lambda _: (largeur, 20)
        return barre

    @staticmethod
    def _redessine(barre: "module._Barre", stream: io.StringIO) -> str:
        """Vide le flux, redessine la barre, rend ce que le redessin a écrit."""
        stream.seek(0)
        stream.truncate(0)
        barre.refresh()
        return stream.getvalue()

    def test_le_redessin_tient_dans_la_largeur_du_terminal(self):
        """Des espaces jusqu'à la longueur du redessin précédent déborderaient d'un terminal rétréci."""
        stream = io.StringIO()
        with self._bar(stream, 80) as barre:
            self._redessine(barre, stream)
            barre.dynamic_ncols = lambda _: (40, 20)
            ecrit = self._redessine(barre, stream)
        assert module.disp_len(ecrit.strip("\r")) <= 40

    def test_le_curseur_revient_en_debut_de_ligne(self):
        """Un terminal replie la barre trop longue en gardant le curseur à sa place dans le texte : ramené au début, il reste sur la première ligne du repli, que le redessin suivant remplace."""
        stream = io.StringIO()
        with self._bar(stream, 80) as barre:
            ecrit = self._redessine(barre, stream)
        assert ecrit.startswith("\r")
        assert ecrit.endswith("\r")

    def test_une_largeur_stable_efface_la_fin_de_la_ligne(self):
        stream = io.StringIO()
        with self._bar(stream, 80) as barre:
            self._redessine(barre, stream)
            ecrit = self._redessine(barre, stream)
        assert module.CLEAR_TO_END_OF_LINE in ecrit
        assert module.CLEAR_TO_END_OF_SCREEN not in ecrit

    def test_la_barre_tient_dans_la_fenetre(self):
        """Une ligne plus longue que la fenêtre s'y replierait, décalant les barres voisines."""
        stream = io.StringIO()
        with self._bar(stream, 70) as barre:
            assert module.disp_len(str(barre)) <= 70

    def test_la_barre_ne_s_etire_pas_indefiniment(self):
        stream = io.StringIO()
        with self._bar(stream, 300) as barre:
            assert module.disp_len(str(barre)) == module.LINE_WIDTH

    def test_deux_volumes_differents_donnent_la_meme_longueur(self):
        """Le compteur occupe une colonne fixe : ce qui reste au remplissage l'est aussi."""
        stream = io.StringIO()
        with self._bar(stream, 80) as petite, self._bar(stream, 80) as grande:
            petite.total = 19
            grande.total = 435758
            assert module.disp_len(str(petite)) == module.disp_len(str(grande))

    def test_un_terminal_retreci_efface_jusqu_au_bas_de_l_ecran(self):
        """La barre trop longue s'y replie sur plusieurs lignes, toutes à effacer."""
        stream = io.StringIO()
        with self._bar(stream, 80) as barre:
            self._redessine(barre, stream)
            barre.dynamic_ncols = lambda _: (40, 20)
            ecrit = self._redessine(barre, stream)
        assert module.CLEAR_TO_END_OF_SCREEN in ecrit


class TestEcritureHorsBarre:
    """Une ligne écrite pendant qu'une barre tourne passe au-dessus d'elle."""

    def test_la_ligne_part_sur_le_flux_donne(self):
        stream = io.StringIO()
        module.write_above_bars("erreur sur hal-05614798", stream)
        assert "erreur sur hal-05614798" in stream.getvalue()

    def test_sans_la_bibliotheque_la_ligne_part_quand_meme(self, monkeypatch):
        monkeypatch.setattr(module, "tqdm", None)
        stream = io.StringIO()
        module.write_above_bars("erreur sur hal-05614798", stream)
        assert "erreur sur hal-05614798" in stream.getvalue()

    def test_le_terminal_recoit_de_quoi_effacer_la_fin_de_ligne(self, avec_terminal):
        """La ligne emporte de quoi effacer la fin de la barre dont elle prend la place."""
        stream = io.StringIO()
        module.write_above_bars("[HAL · 2018] 13 nouveaux", stream)
        assert module.CLEAR_TO_END_OF_LINE in stream.getvalue()

    def test_une_sortie_capturee_reste_sans_sequence_d_effacement(self, sans_terminal):
        """Un fichier de journal porterait la séquence telle quelle."""
        stream = io.StringIO()
        module.write_above_bars("[HAL · 2018] 13 nouveaux", stream)
        assert module.CLEAR_TO_END_OF_LINE not in stream.getvalue()


class TestCompteurDeRetenus:
    """Le compteur porte les éléments retenus ; le remplissage suit les éléments parcourus."""

    def test_le_compteur_part_de_zero(self, avec_terminal):
        with module.track_progress(25, "HAL", None, count_kept=True) as p:
            assert p._bar.kept == 0

    def test_le_compteur_suit_les_retenus_et_la_barre_les_parcourus(self, avec_terminal):
        with module.track_progress(25, "HAL", None, count_kept=True) as p:
            for i in range(25):
                p.advance()
                if i < 14:
                    p.keep()
            assert p._bar.kept == 14
            assert p._bar.n == 25

    def test_le_format_montre_les_retenus_sur_le_total(self, avec_terminal):
        with module.track_progress(25, "HAL", None, count_kept=True) as p:
            p.advance(25)
            p.keep(14)
            rendu = p._bar.format_meter(**p._bar.format_dict)
        assert "14/25" in rendu

    def test_sans_compteur_la_barre_montre_les_parcourus(self, avec_terminal):
        with module.track_progress(25, "HAL", None) as p:
            p.advance(25)
            rendu = p._bar.format_meter(**p._bar.format_dict)
        assert "25/25" in rendu

    def test_le_compteur_tient_sans_barre(self, sans_terminal):
        """Une sortie capturée compte les retenus sans rien afficher."""
        with module.track_progress(25, "HAL", None, count_kept=True) as p:
            p.keep(3)
            assert p._kept == 3


class TestAttente:
    """Un travail dont l'avancement ne se mesure pas : maintenance des tables, VACUUM."""

    def test_le_terminal_recoit_le_libelle_sur_une_ligne_reecrite(self, avec_terminal, monkeypatch):
        stream = io.StringIO()
        monkeypatch.setattr(module, "_bar_stream", stream)
        with module.waiting("maintenance des tables", None):
            pass
        ecrit = stream.getvalue()
        assert ecrit.startswith("\rmaintenance des tables")
        assert ecrit.endswith("\n")

    def test_les_points_courent_pendant_le_travail(self, avec_terminal, monkeypatch):
        stream = io.StringIO()
        monkeypatch.setattr(module, "_bar_stream", stream)
        monkeypatch.setattr(module, "WAITING_REFRESH_S", 0.01)
        with module.waiting("maintenance des tables", None):
            time.sleep(0.08)
        assert "maintenance des tables..." in stream.getvalue()

    def test_la_conclusion_efface_la_fin_du_libelle(self, avec_terminal, monkeypatch):
        """Plus courte que le libellé dont elle prend la place, elle en laisserait la fin derrière elle."""
        stream = io.StringIO()
        monkeypatch.setattr(module, "_bar_stream", stream)
        with module.waiting("mise à jour en cours", None) as ligne:
            ligne.conclude("Terminé en 12.3s")
        assert stream.getvalue().endswith(f"Terminé en 12.3s{module.CLEAR_TO_END_OF_LINE}\n")

    def test_en_terminal_la_conclusion_va_aussi_au_journal(
        self, avec_terminal, monkeypatch, caplog
    ):
        """Régression : en terminal, la conclusion restait au terminal, et le fichier de journal perdait la durée de l'étape."""
        monkeypatch.setattr(module, "_bar_stream", io.StringIO())
        with caplog.at_level(logging.INFO), module.waiting("en cours", _log()) as ligne:
            ligne.conclude("Terminé en 12.3s")
        [record] = [r for r in caplog.records if r.getMessage() == "Terminé en 12.3s"]
        assert record.detail is True

    def test_une_sortie_capturee_recoit_une_ligne_de_journal(self, sans_terminal, caplog):
        with caplog.at_level(logging.INFO), module.waiting("maintenance des tables", _log()):
            pass
        assert "maintenance des tables…" in caplog.text

    def test_une_ligne_effacee_ne_laisse_rien_au_terminal(self, avec_terminal, monkeypatch):
        stream = io.StringIO()
        monkeypatch.setattr(module, "_bar_stream", stream)
        with module.waiting("  ├─ ", None) as ligne:
            ligne.erase()
        assert stream.getvalue().endswith(f"\r{module.CLEAR_TO_END_OF_LINE}")

    def test_une_ligne_effacee_tait_sa_conclusion_au_journal(self, sans_terminal, caplog):
        with caplog.at_level(logging.INFO), module.waiting("  ├─ ", _log()) as ligne:
            ligne.conclude("  ├─ 0 contribution source")
            ligne.erase()
        assert "0 contribution source" not in caplog.text

    def test_une_exception_arrete_les_points(self, avec_terminal, monkeypatch):
        stream = io.StringIO()
        monkeypatch.setattr(module, "_bar_stream", stream)
        with pytest.raises(RuntimeError), module.waiting("maintenance des tables", None):
            raise RuntimeError("VACUUM en échec")
        assert stream.getvalue().endswith("\n")


def _log() -> logging.Logger:
    return logging.getLogger(__name__)
