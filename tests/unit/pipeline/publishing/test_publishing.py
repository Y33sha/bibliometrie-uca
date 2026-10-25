"""Tests de l'enchaînement de la phase `publishing`, exécutée tâche par tâche dans l'ordre du graphe."""

import dataclasses
import logging

from pipeline.graph import TASKS
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing import publishing
from pipeline.transformation.publishing.publishing import PublishingPhase

_CHAMPS = tuple(n.name.removeprefix("publishing.") for n in TASKS if n.phase == "publishing")


def _run(
    contexte,
    appels: list[str] | None = None,
    *,
    credentials_missing: str | None = None,
    **metrics: PhaseMetrics,
) -> PhaseMetrics:
    """Exécute la phase avec ses étapes réelles, leurs fonctions remplacées par des enregistreurs."""
    appels = [] if appels is None else appels

    def runner(champ: str):
        def run(_ctx) -> PhaseMetrics:
            appels.append(champ)
            return metrics.get(champ, PhaseMetrics())

        return run

    steps = {
        name: dataclasses.replace(step, run=runner(name.removeprefix("publishing.")))
        for name, step in publishing.build().steps.items()
    }
    return PublishingPhase(steps).run(
        contexte(credentials_missing=lambda _source: credentials_missing)
    )


def test_les_taches_s_enchainent_dans_l_ordre_du_graphe(contexte):
    appels: list[str] = []
    _run(contexte, appels)
    assert appels == list(_CHAMPS)


def test_chaque_tache_ecrit_sa_ligne_sous_sa_section(contexte, caplog):
    fusion = PhaseMetrics()
    fusion.add(seen=2, serials_merged=2)
    fusion.report = "2 revues fusionnées"
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, merge_duplicate_serials=fusion)
    lignes = [r.getMessage() for r in caplog.records if r.getMessage()]
    assert lignes[:3] == [
        "▶ Éditeurs",
        "  ├─ Éditeurs des préfixes DOI Crossref : rien à faire",
        "  └─ Éditeurs des préfixes DOI DataCite : rien à faire",
    ]
    assert "▶ Publications en série" in lignes and "▶ Monographies" in lignes
    assert "  ├─ Fusion des publications en série en double : 2 revues fusionnées" in lignes
    assert lignes[-1] == "  └─ Nature des monographies : rien à faire"


def test_les_compteurs_des_taches_remontent_a_la_phase(contexte):
    worked = PhaseMetrics()
    worked.add(seen=3)
    metrics = _run(contexte, resolve_crossref_publishers=worked)
    assert metrics.total == 3


def test_acces_non_configure_saute_les_taches_a_source(contexte, caplog):
    """Sans identifiants, l'accès à la source saute la tâche avant sa fonction, et sa ligne le dit."""
    appels: list[str] = []
    with caplog.at_level(logging.INFO, logger="test"):
        metrics = _run(contexte, appels, credentials_missing="clé absente")
    assert "enrich_serials_from_openalex" not in appels
    assert "merge_duplicate_serials" in appels  # tâche sans source
    assert (
        "Type des publications en série sur OpenAlex : sautée, accès non configuré" in caplog.text
    )
    assert {s["code"] for s in metrics.signals} == {"source_unconfigured"}
