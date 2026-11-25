"""Séquence de la phase `normalize`, exécutée tâche par tâche.

Le retrait des contributions sources OpenAlex au profit d'INSPIRE-HEP, puis celui des enregistrements sources disparus, précèdent le nettoyage des informations du contributeur et des adresses : les lignes ainsi orphelines sont supprimées par le nettoyage. L'exécuteur lance le `VACUUM` du staging, maintenance de la tâche de nettoyage. L'arbitrage des identifiants de personne clôt la phase.
"""

import dataclasses
import logging
from types import SimpleNamespace

import pytest

from domain.sources.registry import SOURCE_PRIORITY, Source
from pipeline.ingestion.common import normalize
from pipeline.ingestion.common.normalizer import NormalizeStats
from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from tests.helpers.phase_tree import with_runs

_NORMALIZE = next(phase for phase in PHASES if phase.name == "normalize")


@pytest.fixture
def lancer(contexte, monkeypatch):
    """Renvoie l'exécution de la phase, ses accès à la base remplacés par des enregistreurs de leurs appels."""

    def _lancer(
        appels: list[str],
        *,
        disparues: int = 0,
        retraits: int = 0,
        bilan: NormalizeStats = NormalizeStats(3, 0, 0),
        **options,
    ):
        def appel(nom: str, valeur):
            return lambda *_args: (appels.append(nom), valeur)[1]

        def normaliseur(source, _conn, _logger, *, archive):
            return SimpleNamespace(run=appel(f"normalize:{source}", bilan))

        monkeypatch.setattr(normalize, "build_normalizer", normaliseur)
        monkeypatch.setattr(
            normalize, "withhold_covered_source_contributions", appel("withhold", retraits)
        )
        monkeypatch.setattr(
            normalize, "delete_disappeared_source_records", appel("prune", disparues)
        )
        nettoyages = {
            "cleanup_orphan_contributor_information": appel("cleanup", PhaseMetrics()),
            "cleanup_orphan_addresses": appel("cleanup_addresses", PhaseMetrics()),
            "arbitrate_identifiers": appel("arbitrate", PhaseMetrics(extras={"neutralized": 2})),
        }
        phase = with_runs(_NORMALIZE, nettoyages)
        ctx = contexte(**{"mode": "daily", "sources": {"hal"}, **options})
        return run_phase(phase, dataclasses.replace(ctx, maintain=appels.append))

    return _lancer


def test_le_retrait_precede_le_nettoyage_des_identites_et_des_adresses(lancer):
    appels: list[str] = []
    lancer(appels)
    assert appels == [
        "normalize:hal",
        "withhold",
        "prune",
        "cleanup",
        "cleanup_addresses",
        "VACUUM staging",
        "arbitrate",
    ]


def test_toutes_les_sources_sont_normalisees_dans_l_ordre(lancer):
    appels: list[str] = []
    lancer(appels, sources=frozenset(Source))
    assert appels[: len(SOURCE_PRIORITY)] == [f"normalize:{s.value}" for s in SOURCE_PRIORITY]


def test_le_mode_full_reecrit_le_staging(lancer):
    appels: list[str] = []
    lancer(appels, mode="full")
    assert appels[-2:] == ["VACUUM FULL staging", "arbitrate"]


def test_les_identifiants_neutralises_partent_dans_les_metriques(lancer):
    metrics = lancer([])
    assert metrics.details["summary"]["identifiers_neutralized"] == 2


def test_le_total_reste_celui_des_documents_normalises(lancer):
    metrics = lancer([], disparues=7)
    assert metrics.total == 3


def test_sans_document_la_maintenance_tourne_quand_meme(lancer):
    appels: list[str] = []
    lancer(appels, bilan=NormalizeStats(0, 0, 0))
    assert appels == [
        "normalize:hal",
        "withhold",
        "prune",
        "cleanup",
        "cleanup_addresses",
        "VACUUM staging",
        "arbitrate",
    ]


def test_le_recapitulatif_d_une_source_suit_sa_ligne_de_bilan(lancer, caplog):
    """Les documents refusés et les types inconnus suivent la ligne de bilan de leur source. La dernière ligne de la section des suppressions la ferme."""
    bilan = NormalizeStats(
        3,
        0,
        1,
        discarded=("hal-1",),
        unknown_doc_types={"study-registration": ("hal-2", "hal-3")},
    )
    with caplog.at_level(logging.INFO, logger="test"):
        lancer([], bilan=bilan, disparues=2, retraits=4)
    messages = [record.getMessage() for record in caplog.records]
    debut = messages.index("  └─ HAL : 3 documents normalisés, 1 document écarté, 1 erreur")
    assert messages[debut : debut + 11] == [
        "  └─ HAL : 3 documents normalisés, 1 document écarté, 1 erreur",
        "     documents écartés aux métadonnées incomplètes ou non conformes",
        "     hal-1",
        "     2 documents de type inconnu « study-registration »",
        "     hal-2",
        "     hal-3",
        "",
        "▶ Contributions sources en double et documents disparus",
        "  ├─ 4 contributions sources OpenAlex supprimées (listes d'auteurs d'INSPIRE-HEP)",
        "  └─ 2 documents supprimés (disparus de leur source)",
        "",
    ]


def test_la_table_porte_une_ligne_par_source(lancer):
    metrics = lancer([], bilan=NormalizeStats(3, 1, 2, discarded=("hal-1",)))
    (ligne,) = metrics.details["table"]["rows"]
    assert {k: v for k, v in ligne.items() if k != "duration_s"} == {
        "key": "hal",
        "processed": 3,
        "skipped": 1,
        "discarded": 1,
        "errors": 2,
    }
