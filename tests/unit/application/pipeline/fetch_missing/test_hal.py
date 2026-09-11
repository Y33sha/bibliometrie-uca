"""Orchestrateurs du fetch des entrées HAL manquantes : par hal-id, et par NNT.

Deux pistes, même forme : repérer les identifiants absents, puis les télécharger par un pool de workers et les insérer. Les propriétés qui les distinguent tiennent aux comptages : un hal-id introuvable côté HAL, un NNT trouvé mais dont le document est déjà en staging.

Le pool réel est exercé : seule la source HTTP est doublée.
"""

import logging

from application.pipeline.fetch_missing.hal import (
    fetch_missing_hal_by_id,
    fetch_missing_hal_by_nnt,
)
from application.pipeline.libelles import DERNIERE_BRANCHE
from application.ports.pipeline.fetch_missing.hal import NntInsertResult

_LOG = logging.getLogger("test")


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakeHalAdapter:
    """Doublure du port : les documents rendus sont posés par `docs`, indexés par identifiant.

    Une clé absente vaut « introuvable côté HAL ». `deja_en_staging` désigne les NNT dont le document existe déjà, que HAL rend pourtant.
    """

    max_concurrent = 2

    def __init__(self, *, hal_ids=(), nnts=(), docs=None, deja_en_staging=(), delay_s=0.0):
        self.delay_s = delay_s
        self.hal_ids = list(hal_ids)
        self.nnts = list(nnts)
        self.docs = docs or {}
        self.deja_en_staging = set(deja_en_staging)
        self.configure_appels = 0
        self.telecharges: list[str] = []
        self.inseres: list[str] = []

    def configure(self, conn) -> None:
        self.configure_appels += 1

    def find_missing_hal_ids(self, conn) -> list[str]:
        return self.hal_ids

    def find_missing_nnts(self, conn) -> list[str]:
        return self.nnts

    async def fetch_by_halid(self, client, hal_id: str):
        self.telecharges.append(hal_id)
        return self.docs.get(hal_id)

    async def fetch_by_nnt(self, client, nnt: str):
        self.telecharges.append(nnt)
        return self.docs.get(nnt)

    def insert_halid_result(self, conn, hal_id: str, doc) -> bool:
        self.inseres.append(hal_id)
        return doc is not None

    def insert_nnt_result(self, conn, nnt: str, doc) -> NntInsertResult:
        self.inseres.append(nnt)
        if doc is None:
            return NntInsertResult(api_found=False, inserted=False)
        return NntInsertResult(api_found=True, inserted=nnt not in self.deja_en_staging)


class TestParHalId:
    async def test_compte_les_recuperes_et_les_introuvables(self):
        adapter = _FakeHalAdapter(
            hal_ids=["hal-1", "hal-2"],
            docs={"hal-1": {"halId_s": "hal-1"}},
        )

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 2
        assert metrics.new == 1
        assert metrics.extras["not_found"] == 1
        assert adapter.configure_appels == 1

    async def test_jalon_de_progression_et_pause_entre_fetchs(self):
        # Au-delà du pas de commit, le pool commite en cours de route et jalonne le journal.
        hal_ids = [f"hal-{i}" for i in range(60)]
        adapter = _FakeHalAdapter(
            hal_ids=hal_ids, docs={hal_id: {} for hal_id in hal_ids}, delay_s=0.001
        )
        conn = _FakeConnection()

        metrics = await fetch_missing_hal_by_id(conn, adapter, _LOG)

        assert metrics.new == 60
        assert conn.commits == 2  # un au 50e document, un en sortie de pool

    async def test_rien_a_faire(self, caplog):
        """Le titre de la sous-étape est écrit avant l'appel : sans ligne de conclusion, il reste seul."""
        adapter = _FakeHalAdapter()

        with caplog.at_level(logging.INFO):
            metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 0
        assert adapter.telecharges == []
        assert f"{DERNIERE_BRANCHE}Rien à faire" in caplog.text


class TestParNnt:
    async def test_document_deja_en_staging_ne_compte_pas_comme_nouveau(self):
        adapter = _FakeHalAdapter(
            nnts=["2024UCA0001"],
            docs={"2024UCA0001": {"halId_s": "hal-9"}},
            deja_en_staging={"2024UCA0001"},
        )

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 1
        assert metrics.new == 0
        # HAL a répondu : la thèse n'est pas portée manquante.
        assert metrics.extras["not_found"] == 0

    async def test_compte_les_absents_de_hal(self):
        adapter = _FakeHalAdapter(
            nnts=["2024UCA0001", "2024UCA0002"],
            docs={"2024UCA0001": {}},
        )

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG)

        assert metrics.new == 1
        assert metrics.extras["not_found"] == 1

    async def test_rien_a_faire(self, caplog):
        """Le titre de la sous-étape est écrit avant l'appel : sans ligne de conclusion, il reste seul."""
        adapter = _FakeHalAdapter()

        with caplog.at_level(logging.INFO):
            metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 0
        assert adapter.telecharges == []
        assert f"{DERNIERE_BRANCHE}Rien à faire" in caplog.text
