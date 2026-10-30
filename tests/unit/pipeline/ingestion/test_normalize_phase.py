"""Séquence de la phase `normalize`, exécutée tâche par tâche.

Le retrait des enregistrements sources disparus précède le nettoyage des informations du contributeur et des adresses : les lignes ainsi orphelines sont supprimées par le nettoyage. L'exécuteur lance enfin le `VACUUM` du staging, maintenance de la tâche de nettoyage.
"""

import dataclasses
import logging

from domain.sources.registry import ALL_SOURCES_SET, SOURCE_PRIORITY
from pipeline.ingestion.common.normalize import NormalizePhase
from pipeline.ingestion.common.normalizer import NormalizeStats


def _run(
    contexte,
    appels: list[str],
    *,
    disparues: int = 0,
    bilan: NormalizeStats = NormalizeStats(3, 0, 0),
    **options,
):
    ctx = contexte(**{"mode": "daily", "sources": {"hal"}, **options})
    ctx = dataclasses.replace(ctx, maintain=appels.append)
    return NormalizePhase(
        normalize_one=lambda _ctx, source: (appels.append(f"normalize:{source}"), bilan)[1],
        prune_disappeared=lambda _ctx: (appels.append("prune"), disparues)[1],
        cleanup_orphan_contributor_information=lambda _ctx: (appels.append("cleanup"), 0)[1],
        cleanup_orphan_addresses=lambda _ctx: (appels.append("cleanup_addresses"), 0)[1],
    ).run(ctx)


def test_le_retrait_precede_le_nettoyage_des_identites_et_des_adresses(contexte):
    appels: list[str] = []
    _run(contexte, appels)
    assert appels == ["normalize:hal", "prune", "cleanup", "cleanup_addresses", "VACUUM staging"]


def test_toutes_les_sources_sont_normalisees_dans_l_ordre(contexte):
    appels: list[str] = []
    _run(contexte, appels, sources=ALL_SOURCES_SET)
    assert appels[: len(SOURCE_PRIORITY)] == [f"normalize:{s.value}" for s in SOURCE_PRIORITY]


def test_le_mode_full_reecrit_le_staging(contexte):
    appels: list[str] = []
    _run(contexte, appels, mode="full")
    assert appels[-1] == "VACUUM FULL staging"


def test_le_decompte_des_retraits_part_dans_les_metriques(contexte):
    metrics = _run(contexte, [], disparues=7)
    assert metrics.details["disappeared_pruned"] == 7


def test_le_total_reste_celui_des_documents_normalises(contexte):
    metrics = _run(contexte, [], disparues=7)
    assert metrics.total == 3


def test_sans_document_la_maintenance_tourne_quand_meme(contexte, caplog):
    appels: list[str] = []
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, appels, bilan=NormalizeStats(0, 0, 0))
    assert appels == ["normalize:hal", "prune", "cleanup", "cleanup_addresses", "VACUUM staging"]
    assert "aucun document disparu de sa source" in caplog.text
    assert "▶ Maintenance des tables" in caplog.text


def test_les_retraits_sont_annonces(contexte, caplog):
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, [], disparues=2)
    assert "2 documents supprimés (disparus de leur source)" in caplog.text


def test_la_table_porte_une_ligne_par_source(contexte):
    metrics = _run(contexte, [], bilan=NormalizeStats(3, 1, 2))
    (ligne,) = metrics.details["table"]["rows"]
    assert {k: v for k, v in ligne.items() if k != "duration_s"} == {
        "key": "hal",
        "processed": 3,
        "skipped": 1,
        "errors": 2,
    }
