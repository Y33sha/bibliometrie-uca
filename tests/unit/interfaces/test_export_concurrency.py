"""Nombre d'exports menés de front.

Un export compose sa réponse en mémoire avant de l'envoyer : la requête s'exécute d'un coup, et les lignes tiennent en mémoire tant que le corps part. Le plafond de lignes borne ce qu'un export coûte, celui de fréquence ce qu'une rafale coûte à un client ; celui-ci borne ce que le processus porte à un instant donné, quel que soit le nombre de clients.
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
        """Une erreur survenue avant la construction de la réponse ne doit pas immobiliser un droit."""
        generateur = export_slot()
        next(generateur)
        generateur.close()
        pris = _prendre(settings.max_concurrent_exports)
        for slot in pris:
            slot.release()


class TestRestitutionParLeFlux:
    def test_le_droit_survit_a_la_fin_de_la_dependance(self):
        """La mémoire reste prise tant que le corps part, et le cycle des dépendances s'achève avant."""
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
