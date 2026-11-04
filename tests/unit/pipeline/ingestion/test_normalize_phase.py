"""Séquence de la phase `normalize`, exécutée tâche par tâche.

Le retrait des enregistrements sources disparus précède le nettoyage des informations du contributeur et des adresses : les lignes ainsi orphelines sont supprimées par le nettoyage. L'exécuteur lance enfin le `VACUUM` du staging, maintenance de la tâche de nettoyage.
"""

import dataclasses
from types import SimpleNamespace

import pytest

from domain.sources.registry import SOURCE_PRIORITY, Source
from pipeline.ingestion.common import normalize
from pipeline.ingestion.common.normalizer import NormalizeStats
from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase

_NORMALIZE = next(phase for phase in PHASES if phase.name == "normalize")


@pytest.fixture
def lancer(contexte, monkeypatch):
    """Renvoie l'exécution de la phase, ses accès à la base remplacés par des enregistreurs de leurs appels."""

    def _lancer(
        appels: list[str],
        *,
        disparues: int = 0,
        bilan: NormalizeStats = NormalizeStats(3, 0, 0),
        **options,
    ):
        def appel(nom: str, valeur):
            return lambda *_args: (appels.append(nom), valeur)[1]

        def normaliseur(source, _conn, _logger, *, archive):
            return SimpleNamespace(run=appel(f"normalize:{source}", bilan))

        monkeypatch.setattr(normalize, "build_normalizer", normaliseur)
        monkeypatch.setattr(
            normalize, "delete_disappeared_source_records", appel("prune", disparues)
        )
        nettoyages = {
            "cleanup_orphan_contributor_information": appel("cleanup", PhaseMetrics()),
            "cleanup_orphan_addresses": appel("cleanup_addresses", PhaseMetrics()),
        }
        phase = dataclasses.replace(
            _NORMALIZE,
            tasks=tuple(
                dataclasses.replace(t, run=nettoyages.get(t.name, t.run)) for t in _NORMALIZE.tasks
            ),
        )
        ctx = contexte(**{"mode": "daily", "sources": {"hal"}, **options})
        return run_phase(phase, dataclasses.replace(ctx, maintain=appels.append))

    return _lancer


def test_le_retrait_precede_le_nettoyage_des_identites_et_des_adresses(lancer):
    appels: list[str] = []
    lancer(appels)
    assert appels == ["normalize:hal", "prune", "cleanup", "cleanup_addresses", "VACUUM staging"]


def test_toutes_les_sources_sont_normalisees_dans_l_ordre(lancer):
    appels: list[str] = []
    lancer(appels, sources=frozenset(Source))
    assert appels[: len(SOURCE_PRIORITY)] == [f"normalize:{s.value}" for s in SOURCE_PRIORITY]


def test_le_mode_full_reecrit_le_staging(lancer):
    appels: list[str] = []
    lancer(appels, mode="full")
    assert appels[-1] == "VACUUM FULL staging"


def test_le_decompte_des_retraits_part_dans_les_metriques(lancer):
    metrics = lancer([], disparues=7)
    assert metrics.details["disappeared_pruned"] == 7


def test_le_total_reste_celui_des_documents_normalises(lancer):
    metrics = lancer([], disparues=7)
    assert metrics.total == 3


def test_sans_document_la_maintenance_tourne_quand_meme(lancer):
    appels: list[str] = []
    lancer(appels, bilan=NormalizeStats(0, 0, 0))
    assert appels == ["normalize:hal", "prune", "cleanup", "cleanup_addresses", "VACUUM staging"]


def test_la_table_porte_une_ligne_par_source(lancer):
    metrics = lancer([], bilan=NormalizeStats(3, 1, 2))
    (ligne,) = metrics.details["table"]["rows"]
    assert {k: v for k, v in ligne.items() if k != "duration_s"} == {
        "key": "hal",
        "processed": 3,
        "skipped": 1,
        "errors": 2,
    }
