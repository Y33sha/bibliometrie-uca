"""Store nul, pour un déploiement sans archive des réponses brutes.

Il ignore les écritures, et la lecture se comporte comme sur un store vide : elle lève seulement les exceptions prévues par le contrat. La phase de normalisation le reçoit à la place du store sur disque quand le pipeline tourne sans `--raw-store`.
"""

import pytest

from infrastructure.raw_store import NullRawStore


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
