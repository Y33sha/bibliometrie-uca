"""Orchestrateurs du fetch des entrées HAL manquantes : par hal-id, et par NNT.

Deux pistes, même forme : repérer les références absentes, puis les télécharger par un pool de workers et les insérer. Les propriétés qui les distinguent tiennent aux comptages — un hal-id introuvable côté HAL, un NNT trouvé mais dont le document est déjà en staging — et aux deux modes qui s'arrêtent avant le téléchargement, `stats_only` et `dry_run`.

Le pool réel est exercé : seule la source HTTP est doublée. La déduplication des références, elle, décide de ce qui est téléchargé — un hal-id vu par OpenAlex et par ScanR ne l'est qu'une fois.
"""

import logging

from application.pipeline.cross_imports.fetch_missing_hal import (
    fetch_missing_hal_by_id,
    fetch_missing_hal_by_nnt,
)
from application.ports.pipeline.cross_imports.fetch_missing_hal import (
    HalIdRef,
    NntInsertResult,
    NntRef,
)

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

    def __init__(
        self, *, refs_oa=(), refs_scanr=(), refs_nnt=(), docs=None, deja_en_staging=(), delay_s=0.0
    ):
        self.delay_s = delay_s
        self.refs_oa = list(refs_oa)
        self.refs_scanr = list(refs_scanr)
        self.refs_nnt = list(refs_nnt)
        self.docs = docs or {}
        self.deja_en_staging = set(deja_en_staging)
        self.configure_appels = 0
        self.telecharges: list[str] = []
        self.inseres: list[str] = []

    def configure(self, conn) -> None:
        self.configure_appels += 1

    def find_halid_refs_from_openalex(self, conn) -> list[HalIdRef]:
        return self.refs_oa

    def find_halid_refs_from_scanr(self, conn) -> list[HalIdRef]:
        return self.refs_scanr

    def find_nnt_refs_from_theses(self, conn) -> list[NntRef]:
        return self.refs_nnt

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


def _halid(hal_id: str, source: str = "openalex") -> HalIdRef:
    return HalIdRef(source=source, hal_id=hal_id, foreign_id=f"{source}-{hal_id}")


class TestParHalId:
    async def test_compte_les_recuperes_et_les_introuvables(self):
        adapter = _FakeHalAdapter(
            refs_oa=[_halid("hal-1"), _halid("hal-2")],
            docs={"hal-1": {"halId_s": "hal-1"}},
        )

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 2
        assert metrics.new == 1
        assert metrics.extras["not_found"] == 1
        assert adapter.configure_appels == 1

    async def test_un_hal_id_vu_par_deux_sources_n_est_traite_qu_une_fois(self):
        adapter = _FakeHalAdapter(
            refs_oa=[_halid("hal-1")],
            refs_scanr=[_halid("hal-1", source="scanr"), _halid("hal-2", source="scanr")],
            docs={"hal-1": {}, "hal-2": {}},
        )

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 2
        assert sorted(adapter.telecharges) == ["hal-1", "hal-2"]

    async def test_stats_only_s_arrete_au_denombrement(self):
        adapter = _FakeHalAdapter(refs_oa=[_halid("hal-1")], docs={"hal-1": {}})

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG, stats_only=True)

        assert metrics.seen == 1
        assert adapter.telecharges == []

    async def test_dry_run_ne_telecharge_rien(self):
        # Plus de dix références : la liste affichée est tronquée, le décompte du reste aussi.
        adapter = _FakeHalAdapter(refs_oa=[_halid(f"hal-{i}") for i in range(12)])

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG, dry_run=True)

        assert metrics.seen == 12
        assert adapter.telecharges == []

    async def test_dry_run_liste_courte(self):
        # Dix références ou moins : la liste tient entière, sans mention d'un reste.
        adapter = _FakeHalAdapter(refs_oa=[_halid(f"hal-{i}") for i in range(3)])

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG, dry_run=True)

        assert metrics.seen == 3
        assert adapter.telecharges == []

    async def test_jalon_de_progression_et_pause_entre_fetchs(self):
        # Au-delà du pas de commit, le pool commite en cours de route et jalonne le journal.
        refs = [_halid(f"hal-{i}") for i in range(60)]
        adapter = _FakeHalAdapter(refs_oa=refs, docs={r.hal_id: {} for r in refs}, delay_s=0.001)
        conn = _FakeConnection()

        metrics = await fetch_missing_hal_by_id(conn, adapter, _LOG)

        assert metrics.new == 60
        assert conn.commits == 2  # un au 50e document, un en sortie de pool

    async def test_rien_a_faire(self):
        adapter = _FakeHalAdapter()

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 0
        assert adapter.telecharges == []


class TestParNnt:
    async def test_document_deja_en_staging_ne_compte_pas_comme_nouveau(self):
        adapter = _FakeHalAdapter(
            refs_nnt=[NntRef(nnt="2024UCA0001", theses_id="t1")],
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
            refs_nnt=[
                NntRef(nnt="2024UCA0001", theses_id="t1"),
                NntRef(nnt="2024UCA0002", theses_id="t2"),
            ],
            docs={"2024UCA0001": {}},
        )

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG)

        assert metrics.new == 1
        assert metrics.extras["not_found"] == 1

    async def test_stats_only_s_arrete_au_denombrement(self):
        adapter = _FakeHalAdapter(refs_nnt=[NntRef(nnt="2024UCA0001", theses_id="t1")])

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG, stats_only=True)

        assert metrics.seen == 1
        assert adapter.telecharges == []

    async def test_dry_run_ne_telecharge_rien(self):
        adapter = _FakeHalAdapter(
            refs_nnt=[NntRef(nnt=f"2024UCA{i:04d}", theses_id=f"t{i}") for i in range(12)]
        )

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG, dry_run=True)

        assert metrics.seen == 12
        assert adapter.telecharges == []

    async def test_dry_run_liste_courte(self):
        adapter = _FakeHalAdapter(
            refs_nnt=[NntRef(nnt=f"2024UCA{i:04d}", theses_id=f"t{i}") for i in range(3)]
        )

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG, dry_run=True)

        assert metrics.seen == 3
        assert adapter.telecharges == []

    async def test_rien_a_faire(self):
        adapter = _FakeHalAdapter()

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), adapter, _LOG)

        assert metrics.seen == 0
