"""Séquence de la phase `normalize`.

Le retrait des documents disparus précède le nettoyage des identités : il en libère, que le nettoyage ramasse dans la foulée.
"""

import logging

from pipeline.sources.normalize import NormalizePhase, NormalizeStats


def _run(
    contexte,
    appels: list[str],
    *,
    disparues: int = 0,
    bilan: NormalizeStats = NormalizeStats(3, 0, 0),
    **options,
):
    return NormalizePhase(
        ordered_sources=["hal", "openalex"],
        normalize_one=lambda source: (appels.append(f"normalize:{source}"), bilan)[1],
        prune_disappeared=lambda: (appels.append("prune"), disparues)[1],
        cleanup_orphan_identities=lambda: appels.append("cleanup"),
        vacuum_staging=lambda full: appels.append("vacuum"),
    ).run(contexte(**{"mode": "daily", "sources": {"hal"}, **options}))


def test_le_retrait_precede_le_nettoyage_des_identites(contexte):
    appels: list[str] = []
    _run(contexte, appels)
    assert appels == ["normalize:hal", "prune", "cleanup", "vacuum"]


def test_sans_restriction_toutes_les_sources_sont_normalisees(contexte):
    appels: list[str] = []
    _run(contexte, appels, sources=None)
    assert appels[:2] == ["normalize:hal", "normalize:openalex"]


def test_le_decompte_des_retraits_part_dans_les_metriques(contexte):
    metrics = _run(contexte, [], disparues=7)
    assert metrics.details["disappeared_pruned"] == 7


def test_le_total_reste_celui_des_documents_normalises(contexte):
    metrics = _run(contexte, [], disparues=7)
    assert metrics.total == 3


_RIEN = NormalizeStats(0, 0, 0)


def test_sans_document_la_phase_saute_la_maintenance(contexte, caplog):
    appels: list[str] = []
    with caplog.at_level(logging.INFO, logger="test"):
        metrics = _run(contexte, appels, bilan=_RIEN)
    assert appels == ["normalize:hal", "prune"]
    assert "Rien à faire" in caplog.text
    assert "Maintenance" not in caplog.text
    assert metrics.resume == ""


def test_un_retrait_suffit_a_declencher_la_maintenance(contexte):
    appels: list[str] = []
    _run(contexte, appels, disparues=2, bilan=_RIEN)
    assert appels[-2:] == ["cleanup", "vacuum"]


def test_un_document_ecarte_suffit_a_declencher_la_maintenance(contexte):
    appels: list[str] = []
    _run(contexte, appels, bilan=NormalizeStats(0, 1, 0))
    assert appels[-2:] == ["cleanup", "vacuum"]


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
