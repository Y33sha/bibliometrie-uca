"""Séquence de la phase `normalize`.

Le retrait des documents disparus précède le nettoyage des identités : il en libère, que le nettoyage ramasse dans la foulée.
"""

import logging

from application.pipeline.normalize.phase import run


def _run(appels: list[str], *, disparues: int = 0):
    return run(
        sources={"hal"},
        mode="daily",
        ordered_sources=["hal"],
        normalize_one=lambda source: (appels.append(f"normalize:{source}"), {"processed": 3})[1],
        prune_disappeared=lambda: (appels.append("prune"), disparues)[1],
        cleanup_orphan_identities=lambda: appels.append("cleanup"),
        vacuum_staging=lambda full: appels.append("vacuum"),
        logger=logging.getLogger(__name__),
    )


def test_le_retrait_precede_le_nettoyage_des_identites():
    appels: list[str] = []
    _run(appels)
    assert appels == ["normalize:hal", "prune", "cleanup", "vacuum"]


def test_le_decompte_des_retraits_part_dans_les_metriques():
    metrics = _run([], disparues=7)
    assert metrics.details["disappeared_pruned"] == 7


def test_le_total_reste_celui_des_documents_normalises():
    metrics = _run([], disparues=7)
    assert metrics.total == 3
