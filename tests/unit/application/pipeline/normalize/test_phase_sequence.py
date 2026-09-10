"""Séquence de la phase `normalize`.

Le retrait des documents disparus précède le nettoyage des identités : il en libère, que le nettoyage ramasse dans la foulée.
"""

import logging

from application.pipeline.normalize.phase import run


def _run(appels: list[str], *, disparues: int = 0, ligne: dict | None = None):
    ligne = {"processed": 3} if ligne is None else ligne
    return run(
        sources={"hal"},
        mode="daily",
        ordered_sources=["hal"],
        normalize_one=lambda source: (appels.append(f"normalize:{source}"), ligne)[1],
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


_RIEN = {"processed": 0, "skipped": 0, "errors": 0}


def test_sans_document_la_phase_saute_la_maintenance(caplog):
    appels: list[str] = []
    with caplog.at_level(logging.INFO, logger=__name__):
        metrics = _run(appels, ligne=_RIEN)
    assert appels == ["normalize:hal", "prune"]
    assert "Rien à faire" in caplog.text
    assert "Maintenance" not in caplog.text
    assert metrics.resume == ""


def test_un_retrait_suffit_a_declencher_la_maintenance():
    appels: list[str] = []
    _run(appels, disparues=2, ligne=_RIEN)
    assert appels[-2:] == ["cleanup", "vacuum"]


def test_un_document_ecarte_suffit_a_declencher_la_maintenance():
    appels: list[str] = []
    _run(appels, ligne={**_RIEN, "skipped": 1})
    assert appels[-2:] == ["cleanup", "vacuum"]
