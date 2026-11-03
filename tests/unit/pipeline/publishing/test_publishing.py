"""Tests de l'enchaînement de la phase `publishing`, exécutée tâche par tâche dans l'ordre du graphe."""

import dataclasses
import logging

from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from pipeline.transformation.publishing import publishing

_PHASE = next(phase for phase in PHASES if phase.name == "publishing")
_CHAMPS = tuple(task.name.removeprefix("publishing.") for task in publishing.TASKS)


def _run(
    contexte,
    appels: list[str] | None = None,
    *,
    credentials_missing: str | None = None,
    **metrics: PhaseMetrics,
) -> PhaseMetrics:
    """Exécute la phase avec ses tâches réelles, leurs fonctions remplacées par des enregistreurs."""
    appels = [] if appels is None else appels

    def runner(champ: str):
        def run(_ctx) -> PhaseMetrics:
            appels.append(champ)
            return metrics.get(champ, PhaseMetrics())

        return run

    tasks = tuple(
        dataclasses.replace(task, run=runner(task.name.removeprefix("publishing.")))
        for task in _PHASE.tasks
    )
    return run_phase(
        dataclasses.replace(_PHASE, tasks=tasks),
        contexte(credentials_missing=lambda _source: credentials_missing),
    )


def test_les_taches_s_enchainent_dans_l_ordre_du_graphe(contexte):
    appels: list[str] = []
    _run(contexte, appels)
    assert appels == list(_CHAMPS)


def test_chaque_tache_ecrit_sa_ligne_sous_sa_section(contexte, caplog):
    rattachement = PhaseMetrics()
    rattachement.add(seen=2, updated=2)
    rattachement.report = "2 enregistrements sources rattachés à une autre revue"
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, attach_serials=rattachement)
    lignes = [r.getMessage() for r in caplog.records if r.getMessage()]
    assert lignes[:5] == [
        "▶ Éditeurs",
        "  ├─ Éditeurs des préfixes DOI Crossref : rien à faire",
        "  ├─ Éditeurs des préfixes DOI DataCite : rien à faire",
        "  ├─ Rattachement des enregistrements sources aux éditeurs : rien à faire",
        "  └─ Autres noms des éditeurs : rien à faire",
    ]
    assert "▶ Publications en série" in lignes and "▶ Monographies" in lignes
    assert (
        "  ├─ Rattachement des enregistrements sources aux publications en série : "
        "2 enregistrements sources rattachés à une autre revue"
    ) in lignes
    assert lignes[-1] == "  └─ Nature des monographies : rien à faire"


def test_les_compteurs_des_taches_remontent_a_la_phase(contexte):
    publishers = PhaseMetrics()
    publishers.add(new=1, publisher_matched=2)
    metrics = _run(
        contexte,
        resolve_crossref_publishers=publishers,
        enrich_serials_from_openalex=PhaseMetrics(updated=5),
    )
    assert (metrics.new, metrics.updated) == (1, 5)
    assert metrics.extras.get("publisher_matched") == 2


def test_les_signaux_des_taches_remontent_a_la_phase(contexte):
    publishers = PhaseMetrics()
    publishers.signals.append(
        {"level": "warning", "code": "source_unavailable", "message": "crossref : arrêt"}
    )
    metrics = _run(contexte, resolve_crossref_publishers=publishers)
    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def test_acces_non_configure_saute_les_taches_a_source(contexte, caplog):
    """Sans identifiants, une tâche à source est sautée avant l'appel de sa fonction, et sa ligne le signale."""
    appels: list[str] = []
    with caplog.at_level(logging.INFO, logger="test"):
        metrics = _run(contexte, appels, credentials_missing="clé absente")
    assert "enrich_serials_from_openalex" not in appels
    assert "attach_serials" in appels  # tâche sans source
    assert (
        "Type des publications en série sur OpenAlex : sautée, accès non configuré" in caplog.text
    )
    assert {s["code"] for s in metrics.signals} == {"source_unconfigured"}
