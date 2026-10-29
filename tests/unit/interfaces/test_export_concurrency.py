"""Nombre d'exports simultanés.

Un export exécute sa requête d'un coup, et ses lignes restent en mémoire tant que le corps de la réponse part. Le plafond de lignes borne le coût d'un export, le plafond de fréquence le coût d'une rafale pour un client. Le plafond d'exports simultanés borne la mémoire du processus à un instant donné, quel que soit le nombre de clients.
"""

import pytest
from fastapi import HTTPException

from infrastructure.settings import settings
from interfaces.api import rate_limit
from interfaces.api.rate_limit import ExportSlot, export_slot, releasing, reset_export_slots


@pytest.fixture(autouse=True)
def _slots_neufs():
    reset_export_slots()
    yield
    reset_export_slots()


def _prendre(n: int) -> list[ExportSlot]:
    pris = []
    for _ in range(n):
        slot = ExportSlot()
        assert slot.acquire()
        pris.append(slot)
    return pris


class TestPlafond:
    def test_le_plafond_vient_de_la_configuration(self):
        pris = _prendre(settings.max_concurrent_exports)
        refuse = ExportSlot()
        assert not refuse.acquire()
        for slot in pris:
            slot.release()

    def test_un_droit_est_rendu_au_jeu_dont_il_a_ete_pris(self):
        """Un flux fermé après le renouvellement du jeu de droits (entre deux tests) laisse le jeu neuf intact."""
        ancien = _prendre(1)[0]
        reset_export_slots()
        ancien.release()
        assert len(_prendre(settings.max_concurrent_exports)) == settings.max_concurrent_exports

    def test_un_droit_rendu_redevient_disponible(self):
        pris = _prendre(settings.max_concurrent_exports)
        pris[0].release()
        suivant = ExportSlot()
        assert suivant.acquire()
        suivant.release()
        for slot in pris[1:]:
            slot.release()

    def test_rendre_deux_fois_ne_cree_pas_de_droit(self):
        slot = ExportSlot()
        assert slot.acquire()
        slot.release()
        slot.release()
        pris = _prendre(settings.max_concurrent_exports)
        assert not ExportSlot().acquire()
        for s in pris:
            s.release()


class TestDependance:
    def test_elle_refuse_en_503_quand_le_plafond_est_atteint(self):
        pris = _prendre(settings.max_concurrent_exports)
        generateur = export_slot()
        with pytest.raises(HTTPException) as refus:
            next(generateur)
        assert refus.value.status_code == 503
        assert refus.value.headers["Retry-After"]
        for slot in pris:
            slot.release()

    def test_le_droit_est_rendu_si_le_flux_ne_le_reprend_pas(self):
        """Une erreur avant la construction de la réponse libère le droit."""
        generateur = export_slot()
        next(generateur)
        generateur.close()
        pris = _prendre(settings.max_concurrent_exports)
        for slot in pris:
            slot.release()


class TestRestitutionParLeFlux:
    def test_le_droit_survit_a_la_fin_de_la_dependance(self):
        """Le droit reste pris tant que le corps de la réponse part, après la fin du cycle des dépendances."""
        generateur = export_slot()
        slot = next(generateur)
        flux = releasing(iter(["a", "b"]), slot)
        next(flux)  # l'envoi commence : le flux a repris le droit
        generateur.close()  # fin du cycle de la dépendance
        assert rate_limit._export_slots._value == settings.max_concurrent_exports - 1
        list(flux)  # l'envoi s'achève
        assert rate_limit._export_slots._value == settings.max_concurrent_exports

    def test_un_envoi_abandonne_rend_le_droit(self):
        generateur = export_slot()
        slot = next(generateur)
        flux = releasing(iter(["a", "b", "c"]), slot)
        next(flux)
        flux.close()  # le client se déconnecte
        generateur.close()
        assert rate_limit._export_slots._value == settings.max_concurrent_exports
