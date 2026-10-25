"""Recherches dans HAL de la phase `fetch_missing` : par hal-id, et par NNT.

Deux pistes, même forme : sélectionner les identifiants absents, puis les chercher par un pool de workers et écrire les documents trouvés. Le pool réel est exercé ; la sélection, la requête HTTP, l'écriture dans `staging` et l'inscription des échecs sont remplacées.
"""

import logging

import pytest

from pipeline.http.circuit_breaker import source_circuit_breaker
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.ingestion.common.staging import StagingStore
from pipeline.ingestion.hal import fetch_missing
from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_id, fetch_missing_hal_by_nnt

_LOG = logging.getLogger("test")


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _HalSimule:
    """HAL et la base, simulés.

    `docs` porte les documents rendus, indexés par identifiant cherché ; un identifiant absent vaut « introuvable ». `en_echec` désigne les identifiants pour lesquels HAL est indisponible. `deja_en_staging` désigne les hal-ids des documents déjà présents.
    """

    def __init__(self, monkeypatch, *, ids=(), docs=None, en_echec=(), deja_en_staging=()):
        self.docs = docs or {}
        self.en_echec = set(en_echec)
        self.deja_en_staging = set(deja_en_staging)
        self.cherches: list[str] = []
        self.ecrits: list[str] = []
        self.echecs: list[tuple[str, str]] = []

        async def search_one(client, query, *, label):
            identifiant = query.split(":", 1)[1]
            self.cherches.append(identifiant)
            if identifiant in self.en_echec:
                return UNAVAILABLE
            return self.docs.get(identifiant, NOT_FOUND)

        def upsert(_store, *, source, source_id, doi, raw_data, authors_truncated, entry_mode):
            self.ecrits.append(source_id)
            return source_id not in self.deja_en_staging, False

        def record_failed_lookup(conn, source, id_type, id_value):
            self.echecs.append((id_type, id_value))

        monkeypatch.setattr(
            fetch_missing, "get_missing_hal_ids", lambda conn, *, retry_after_days: list(ids)
        )
        monkeypatch.setattr(
            fetch_missing, "get_missing_nnts", lambda conn, *, retry_after_days: list(ids)
        )
        monkeypatch.setattr(fetch_missing, "search_one", search_one)
        monkeypatch.setattr(StagingStore, "upsert", upsert)
        monkeypatch.setattr(fetch_missing, "record_failed_lookup", record_failed_lookup)


class TestParHalId:
    async def test_compte_les_recuperes_et_les_introuvables(self, monkeypatch):
        hal = _HalSimule(monkeypatch, ids=["hal-1", "hal-2"], docs={"hal-1": {"halId_s": "hal-1"}})

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), _LOG, retry_after_days=30)

        assert (metrics.seen, metrics.new, metrics.extras["not_found"]) == (2, 1, 1)
        assert hal.echecs == [("hal_id", "hal-2")]

    async def test_hal_indisponible_ni_ecrit_ni_compte(self, monkeypatch):
        # Une source indisponible ne prouve pas l'absence : l'identifiant attend le run suivant.
        hal = _HalSimule(
            monkeypatch,
            ids=["hal-1", "hal-2"],
            docs={"hal-1": {"halId_s": "hal-1"}},
            en_echec={"hal-2"},
        )

        metrics = await fetch_missing_hal_by_id(_FakeConnection(), _LOG, retry_after_days=30)

        assert hal.ecrits == ["hal-1"]
        assert hal.echecs == []
        assert (metrics.new, metrics.extras.get("not_found", 0)) == (1, 0)

    async def test_commit_par_lot(self, monkeypatch):
        # Au-delà du pas de commit, le pool commite en cours de route.
        hal_ids = [f"hal-{i}" for i in range(60)]
        _HalSimule(monkeypatch, ids=hal_ids, docs={h: {"halId_s": h} for h in hal_ids})
        conn = _FakeConnection()

        metrics = await fetch_missing_hal_by_id(conn, _LOG, retry_after_days=30)

        assert metrics.new == 60
        assert conn.commits == 2  # un au 50e document, un en sortie de pool

    async def test_s_arrete_quand_le_circuit_breaker_coupe(self, monkeypatch):
        """La recherche s'arrête à l'identifiant qui fait couper le circuit-breaker."""
        hal_ids = [f"hal-{i}" for i in range(20)]
        hal = _HalSimule(monkeypatch, ids=hal_ids)
        recherche = fetch_missing.search_one

        async def search_one_puis_coupure(client, query, *, label):
            breaker.tripped = True
            return await recherche(client, query, label=label)

        monkeypatch.setattr(fetch_missing, "search_one", search_one_puis_coupure)
        with source_circuit_breaker("hal") as breaker:
            await fetch_missing_hal_by_id(_FakeConnection(), _LOG, retry_after_days=30)

        assert hal.cherches == ["hal-0"]

    async def test_sans_hal_id_a_chercher_rien_n_est_ecrit(self, monkeypatch, caplog):
        """L'exécuteur des tâches ferme la section quand aucune recherche n'a rien cherché."""
        hal = _HalSimule(monkeypatch)

        with caplog.at_level(logging.INFO):
            metrics = await fetch_missing_hal_by_id(_FakeConnection(), _LOG, retry_after_days=30)

        assert metrics.seen == 0
        assert hal.cherches == []
        assert caplog.text == ""


class TestParNnt:
    async def test_document_deja_en_staging_ne_compte_pas_comme_nouveau(self, monkeypatch):
        _HalSimule(
            monkeypatch,
            ids=["2024UCA0001"],
            docs={"2024UCA0001": {"halId_s": "hal-9"}},
            deja_en_staging={"hal-9"},
        )

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), _LOG, retry_after_days=30)

        assert (metrics.seen, metrics.new) == (1, 0)
        # HAL a répondu : la thèse n'est pas portée manquante.
        assert metrics.extras.get("not_found", 0) == 0

    async def test_un_nnt_introuvable_est_inscrit(self, monkeypatch):
        hal = _HalSimule(
            monkeypatch,
            ids=["2024UCA0001", "2024UCA0002"],
            docs={"2024UCA0001": {"halId_s": "tel-1"}},
        )

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), _LOG, retry_after_days=30)

        assert (metrics.new, metrics.extras["not_found"]) == (1, 1)
        assert hal.echecs == [("nnt", "2024UCA0002")]

    @pytest.mark.parametrize("doc", [{}, {"halId_s": ""}])
    async def test_document_sans_hal_id_ignore(self, monkeypatch, doc):
        hal = _HalSimule(monkeypatch, ids=["2024UCA0001"], docs={"2024UCA0001": doc})

        metrics = await fetch_missing_hal_by_nnt(_FakeConnection(), _LOG, retry_after_days=30)

        assert (hal.ecrits, hal.echecs, metrics.new) == ([], [], 0)
