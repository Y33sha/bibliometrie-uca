"""Store nul : un déploiement qui n'archive pas les réponses brutes.

Ce qui y entre n'en ressort pas, et la lecture se comporte comme sur un store vide — sans lever autrement que le contrat ne le prévoit.
"""

import pytest

from infrastructure.raw_store import NullRawStore, get_raw_store, set_raw_store
from infrastructure.raw_store.local import LocalFileRawStore


class TestNullRawStore:
    def test_ce_qui_entre_n_en_ressort_pas(self):
        store = NullRawStore()
        store.put("hal", "hal-123", b'{"titre": "x"}')
        assert store.exists("hal", "hal-123") is False
        with pytest.raises(KeyError):
            store.get("hal", "hal-123")

    def test_suppression_idempotente(self):
        assert NullRawStore().delete("hal", "hal-123") is False

    def test_aucune_cle_a_parcourir(self):
        assert list(NullRawStore().iter_keys("hal")) == []


class TestSurcharge:
    def test_la_surcharge_est_rendue_a_tous(self, tmp_path):
        nul = NullRawStore()
        set_raw_store(nul)
        try:
            assert get_raw_store() is nul
        finally:
            set_raw_store(None)

    def test_une_url_explicite_l_emporte(self, tmp_path):
        # Les scripts qui ciblent un store précis ne doivent pas tomber sur la surcharge.
        set_raw_store(NullRawStore())
        try:
            assert isinstance(get_raw_store(tmp_path.as_uri()), LocalFileRawStore)
        finally:
            set_raw_store(None)

    def test_la_surcharge_se_leve(self, tmp_path):
        set_raw_store(NullRawStore())
        set_raw_store(None)
        assert not isinstance(get_raw_store(), NullRawStore)
