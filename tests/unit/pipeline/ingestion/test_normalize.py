"""Tests unitaires de `pipeline.ingestion.common.normalizer.SourceNormalizer`.

Couvre la séquence d'écriture `normalize_record`, le tri de `process_work` sur les métadonnées minimales, et la template method `run()` et ses chemins :
- `total == 0` (rien à faire)
- happy path (success / skip / error mélangés, batch commit, summary)
- exception dans `process_work` (log de l'échec + rollback au SAVEPOINT)
- `KeyboardInterrupt` (rollback du batch en cours + re-raise pour arrêt propre)
- exception fatale en dehors de la boucle (rollback + relève)
- `_iter_rows` mode `FETCH_SUB_BATCH` (chargement par sous-lots)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest

from domain.serials.containers import ContainerDescription
from pipeline.ingestion.common import normalizer as normalizer_module
from pipeline.ingestion.common.normalizer import (
    Document,
    NormalizeStats,
    PublisherFacts,
    SourceNormalizer,
)
from pipeline.ingestion.common.source_contributions import AuthorBlock, AuthorRecord
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.common.staging import StagingRow
from pipeline.transformation.publishing.find_or_create import Containers


def _row(label: str) -> StagingRow:
    """Construit une StagingRow identifiable par son `source_id` pour les assertions."""
    return StagingRow(id=hash(label) & 0xFFFF, source_id=label, doi=None, raw_data={})


class _FakeStaging:
    """Stub minimal du port `StagingStore`."""

    def __init__(self) -> None:
        self.count_returns = 0
        self.pending_rows: list[StagingRow] = []
        self.batch_ids: list[int] = []
        self.batch_id_rows: dict[tuple[int, ...], list[StagingRow]] = {}

    def count_pending_staging(self, source: str) -> int:
        return self.count_returns

    def fetch_pending_staging(self, source: str, *, limit: int) -> list[StagingRow]:
        return self.pending_rows[:limit]

    def fetch_pending_staging_ids(self, source: str) -> list[int]:
        # Le test dédié à `FETCH_SUB_BATCH` peuple `batch_ids` directement.
        # Pour les autres tests qui peuplent `pending_rows`, on dérive les ids.
        if self.batch_ids:
            return self.batch_ids
        return [r.id for r in self.pending_rows]

    def fetch_staging_by_ids(self, ids: list[int]) -> list[StagingRow]:
        if self.batch_id_rows:
            return self.batch_id_rows.get(tuple(ids), [])
        ids_set = set(ids)
        return [r for r in self.pending_rows if r.id in ids_set]


def _stores(staging) -> dict[str, Any]:
    """Arguments du constructeur commun, `staging` compris, les autres stores étant des MagicMock."""
    return {
        "conn": MagicMock(invalidated=False),
        "logger": logging.getLogger("test"),
        "staging_store": staging,
        "record_store": MagicMock(),
        "container_stores": MagicMock(),
        "publisher_store": MagicMock(),
        "contribution_store": MagicMock(),
        "location_store": MagicMock(),
    }


class _StubNorm(SourceNormalizer):
    """Normalizer dont l'analyse d'une ligne est sans objet pour le test."""

    SOURCE = "test"

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return "Titre", 2024

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        raise NotImplementedError

    def author_block(self, doc: Document) -> AuthorBlock:
        return {}

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return []


class _Norm(_StubNorm):
    """Normalizer instrumenté pour pinguer `run()`."""

    SOURCE = "test"
    DEFAULT_BATCH_SIZE = 2

    def __init__(
        self,
        staging: _FakeStaging,
        *,
        results: list[Any] | None = None,
        raises_on: set[str] | None = None,
    ) -> None:
        super().__init__(**_stores(staging))
        self.results = results or []
        self.raises_on = raises_on or set()
        self.processed_rows: list[StagingRow] = []
        self.preload_called = False
        self.cleanup_called = False

    def process_work(self, row: StagingRow) -> bool | None:
        self.processed_rows.append(row)
        if row.source_id in self.raises_on:
            raise RuntimeError(f"boom on {row.source_id}")
        # Retourne le résultat indexé par position (True/None/False).
        idx = len(self.processed_rows) - 1
        if idx < len(self.results):
            return self.results[idx]
        return True

    def preload_caches(self):
        self.preload_called = True

    def cleanup(self):
        self.cleanup_called = True


# ── total == 0 ────────────────────────────────────────────────────


class TestRunNoWork:
    def test_nothing_to_do(self, caplog):
        """Une source sans document en attente se tait : la barre des autres reste lisible."""
        staging = _FakeStaging()
        staging.count_returns = 0
        norm = _Norm(staging)
        with caplog.at_level(logging.INFO):
            norm.run()
        # Pas de preload sur total=0 (sortie avant).
        assert norm.preload_called is False
        assert caplog.text == ""


# ── Happy path ────────────────────────────────────────────────────


class TestRunHappyPath:
    def test_processes_all_rows(self):
        staging = _FakeStaging()
        staging.count_returns = 3
        staging.pending_rows = [_row("r1"), _row("r2"), _row("r3")]
        norm = _Norm(staging, results=[True, True, True])
        norm.run()
        assert norm.preload_called is True
        assert [r.source_id for r in norm.processed_rows] == ["r1", "r2", "r3"]
        assert norm.cleanup_called is True

    def test_mixes_success_skip_error(self, caplog):
        """`True` → processed, `None` → skipped, `False` → errors, récapitulé par son identifiant."""
        staging = _FakeStaging()
        staging.count_returns = 3
        staging.pending_rows = [_row("ok"), _row("skip"), _row("err")]
        norm = _Norm(staging, results=[True, None, False])
        with caplog.at_level(logging.INFO):
            stats = norm.run()
        assert "1 document aux métadonnées incomplètes" in caplog.text
        assert "err" in caplog.text
        assert stats == NormalizeStats(processed=1, skipped=1, errors=1)

    def test_sans_document_incomplet_aucun_recapitulatif(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 2
        staging.pending_rows = [_row("ok"), _row("skip")]
        norm = _Norm(staging, results=[True, None])
        with caplog.at_level(logging.INFO):
            norm.run()
        assert "métadonnées incomplètes" not in caplog.text

    def test_le_commit_tombe_a_chaque_lot(self):
        """Avec DEFAULT_BATCH_SIZE=2 sur quatre documents : deux commits de lot, plus celui de fin."""
        staging = _FakeStaging()
        staging.count_returns = 4
        staging.pending_rows = [_row(s) for s in ("a", "b", "c", "d")]
        norm = _Norm(staging, results=[True, True, True, True])
        norm.run()
        assert norm.conn.commit.call_count == 3

    def test_un_run_sans_erreur_se_tait(self, caplog):
        """La barre porte l'avancement ; le compte des ignorés remonte par les métriques."""
        staging = _FakeStaging()
        staging.count_returns = 2
        staging.pending_rows = [_row("a"), _row("b")]
        norm = _Norm(staging, results=[True, None])
        with caplog.at_level(logging.INFO):
            stats = norm.run()
        assert caplog.text == ""
        assert stats.skipped == 1


# ── Exception dans un work ────────────────────────────────────────


class TestRunWorkException:
    def test_savepoint_rollback_continues_batch(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 2
        staging.pending_rows = [_row("a"), _row("b")]
        norm = _Norm(staging, results=[True, True], raises_on={"a"})
        with caplog.at_level(logging.INFO):
            norm.run()
        # Le work en échec est loggé par la boucle (les process_work ne loggent pas eux-mêmes).
        assert "Erreur sur a" in caplog.text
        # Le 2e row est quand même traité après le rollback du 1er.
        assert "b" in [r.source_id for r in norm.processed_rows]
        # Une exception n'est pas un document incomplet : elle sort sur-le-champ, avec son motif.
        assert "métadonnées incomplètes" not in caplog.text


# ── KeyboardInterrupt ─────────────────────────────────────────────


class TestRunKeyboardInterrupt:
    def test_rollback_and_reraise(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 1
        staging.pending_rows = [_row("a")]

        class _Kb(_Norm):
            def process_work(self, row):
                raise KeyboardInterrupt

        norm = _Kb(staging, results=[True])
        with caplog.at_level(logging.WARNING), pytest.raises(KeyboardInterrupt):
            norm.run()
        # Le batch en cours est rollbacké (la transaction est avortée par le Ctrl+C ;
        # `commit()` lèverait `PendingRollbackError`), et le KeyboardInterrupt est
        # re-levé pour que `run_pipeline` arrête proprement (les batches committés
        # restent durables).
        assert "Interruption" in caplog.text
        norm.conn.rollback.assert_called()

    def test_connexion_invalidee_laisse_remonter_l_interruption(self):
        """Un Ctrl+C en pleine requête invalide la connexion : son `rollback()` lèverait `PendingRollbackError` à la place du `KeyboardInterrupt`."""
        staging = _FakeStaging()
        staging.count_returns = 1
        staging.pending_rows = [_row("a")]

        class _Kb(_Norm):
            def process_work(self, row):
                self.conn.invalidated = True
                self.conn.rollback.side_effect = RuntimeError("Can't reconnect until invalid")
                raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            _Kb(staging, results=[True]).run()


# ── Exception fatale ──────────────────────────────────────────────


class TestRunFatalException:
    def test_rollback_and_reraise(self, caplog):
        """Si `preload_caches` lève (avant la boucle), c'est une erreur fatale : rollback + log + reraise."""
        staging = _FakeStaging()
        staging.count_returns = 1
        staging.pending_rows = [_row("a")]

        class _Fatal(_Norm):
            def preload_caches(self):
                raise RuntimeError("fatal preload")

        norm = _Fatal(staging)
        with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
            norm.run()
        assert "Erreur fatale" in caplog.text
        assert norm.conn.rollback.called is True  # type: ignore[attr-defined]


# ── _iter_rows avec FETCH_SUB_BATCH ───────────────────────────────


class TestIterRowsSubBatch:
    def test_loads_by_subbatches(self):
        """`FETCH_SUB_BATCH=2` → chargement par sous-lots de 2 ids."""

        class _SubBatch(_Norm):
            FETCH_SUB_BATCH = 2

        staging = _FakeStaging()
        staging.batch_ids = [10, 20, 30]
        a, b, c = _row("a"), _row("b"), _row("c")
        staging.batch_id_rows = {(10, 20): [a, b], (30,): [c]}
        norm = _SubBatch(staging)
        rows = list(norm._iter_rows())
        assert rows == [a, b, c]


# ── process_work : métadonnées minimales ─────────────────────────


class _MinimalNorm(_StubNorm):
    """Normalizer qui lit titre et année dans le payload, pour la méthode de gabarit `process_work`."""

    def __init__(self, staging: MagicMock) -> None:
        super().__init__(**_stores(staging))
        self.normalized: list[StagingRow] = []

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return row.raw_data.get("title"), row.raw_data.get("year")  # type: ignore[return-value]

    def normalize_record(self, row: StagingRow) -> bool:
        self.normalized.append(row)
        return True


class TestProcessWorkMinimalMetadata:
    def test_enregistrement_source_vide_saute(self):
        staging = MagicMock()
        norm = _MinimalNorm(staging)
        row = StagingRow(id=1, source_id="a", doi=None, raw_data={})
        assert norm.process_work(row) is None
        staging.mark_done.assert_called_once()
        staging.discard_source_record.assert_not_called()

    def test_enregistrement_source_sans_annee_ecarte_et_supprime(self):
        """Régression : un enregistrement qu'OpenAlex renvoie sans année ne fonde aucune publication, et l'enregistrement source qu'il avait produit disparaît."""
        staging = MagicMock()
        norm = _MinimalNorm(staging)
        row = StagingRow(id=7, source_id="W3131333980", doi=None, raw_data={"title": "T"})
        assert norm.process_work(row) is False
        staging.discard_source_record.assert_called_once_with(7)
        staging.mark_done.assert_called_once_with(7)
        assert norm.normalized == []

    def test_enregistrement_source_refuse_par_la_source(self):
        """`normalize_record` rend False (Crossref sans DOI, HAL sans auteur) : même sort qu'un enregistrement source incomplet."""
        staging = MagicMock()
        norm = _MinimalNorm(staging)
        norm.normalize_record = lambda row: False  # type: ignore[method-assign]
        row = StagingRow(id=3, source_id="c", doi=None, raw_data={"title": "T", "year": 2020})
        assert norm.process_work(row) is False
        staging.discard_source_record.assert_called_once_with(3)
        staging.mark_done.assert_called_once_with(3)

    def test_enregistrement_source_complet_normalise(self):
        staging = MagicMock()
        norm = _MinimalNorm(staging)
        row = StagingRow(id=2, source_id="b", doi=None, raw_data={"title": "T", "year": 2020})
        assert norm.process_work(row) is True
        assert norm.normalized == [row]
        staging.discard_source_record.assert_not_called()


# ── normalize_record : séquence d'écriture ───────────────────────


_RECORD = SourceRecordUpsert(
    source="test",
    source_id="a",
    staging_id=1,
    doi=None,
    title="T",
    publication_year=2020,
    raw_doc_type=None,
    serial_id=None,
    monograph_id=None,
    container_title=None,
    raw_language=None,
    biblio=None,
    abstract=None,
    keywords=None,
    oa_status=None,
    license=None,
    impact=None,
    source_extras=None,
)


class _WritingNorm(_StubNorm):
    """Normalizer dont l'analyse est réglable : document lu, éditeur, conteneurs."""

    def __init__(
        self,
        *,
        doc: Document | None,
        publisher: PublisherFacts | None = None,
        facts: ContainerDescription | None = None,
    ) -> None:
        super().__init__(**_stores(MagicMock()))
        self._doc = doc
        self._publisher = publisher
        self._facts = facts
        self.containers_seen: list[Containers] = []

    def parse(self, row: StagingRow) -> Document | None:
        return self._doc

    def publisher(self, doc: Document) -> PublisherFacts | None:
        return self._publisher

    def container_facts(self, doc: Document) -> ContainerDescription | None:
        return self._facts

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        self.containers_seen.append(containers)
        return _RECORD


@pytest.fixture
def writes(monkeypatch) -> list[tuple]:
    """Écritures de la séquence, dans l'ordre : éditeur, conteneurs, contributions sources."""
    calls: list[tuple] = []

    def publisher(name, *, openalex_id, repo):
        calls.append(("publisher", name, openalex_id))
        return 5

    def containers(facts, *, publisher_id, stores):
        calls.append(("containers", publisher_id))
        return Containers(7, None)

    def sync(store, source, source_record_id, block, build):
        calls.append(("contributions", source, source_record_id))

    monkeypatch.setattr(normalizer_module, "find_or_create_publisher", publisher)
    monkeypatch.setattr(normalizer_module, "find_or_create_containers", containers)
    monkeypatch.setattr(normalizer_module, "sync_source_contributions", sync)
    return calls


class TestNormalizeRecord:
    ROW = StagingRow(id=1, source_id="a", doi=None, raw_data={"title": "T"})

    def test_enregistrement_refuse_sans_ecriture(self, writes):
        norm = _WritingNorm(doc=None)
        assert norm.normalize_record(self.ROW) is False
        assert writes == []
        norm._record_store.upsert_source_record.assert_not_called()
        norm._staging.mark_done.assert_not_called()

    def test_editeur_puis_conteneurs_puis_enregistrement_et_contributions(self, writes):
        norm = _WritingNorm(
            doc={"title": "T"},
            publisher=PublisherFacts("Elsevier", "P1"),
            facts=ContainerDescription(source="test", raw_doc_type=None, journal_title="Revue"),
        )
        norm._record_store.upsert_source_record.return_value = 42
        assert norm.normalize_record(self.ROW) is True
        assert writes == [
            ("publisher", "Elsevier", "P1"),
            ("containers", 5),
            ("contributions", "test", 42),
        ]
        assert norm.containers_seen == [Containers(7, None)]
        norm._record_store.upsert_source_record.assert_called_once_with(
            replace(_RECORD, publisher_id=5)
        )
        norm._location_store.replace_locations.assert_called_once_with(42, [])
        norm._staging.mark_done.assert_called_once_with(1)

    def test_sans_editeur_ni_conteneur(self, writes):
        norm = _WritingNorm(doc={"title": "T"})
        norm._record_store.upsert_source_record.return_value = 42
        assert norm.normalize_record(self.ROW) is True
        assert writes == [("contributions", "test", 42)]
        assert norm.containers_seen == [Containers(None, None)]

    def test_conteneurs_sans_editeur(self, writes):
        norm = _WritingNorm(
            doc={"title": "T"},
            facts=ContainerDescription(source="test", raw_doc_type=None, journal_title="Revue"),
        )
        norm.normalize_record(self.ROW)
        assert writes[0] == ("containers", None)
