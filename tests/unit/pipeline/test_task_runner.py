"""Exécuteur des tâches d'une phase (`pipeline.task_runner`)."""

import logging
import threading

import pytest

from pipeline.graph import Block, Phase, Step, Task
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import execute_tasks, run_phase


def test_l_executeur_mesure_la_duree_des_seules_taches_executees(contexte):
    """Une tâche exécutée reçoit sa durée, rangée aussi dans le contexte. Une tâche écartée par sa condition est absente du résultat."""
    tasks = (
        Task("une", run=lambda _ctx: PhaseMetrics()),
        Task("ecartee", run=lambda _ctx: PhaseMetrics(), when=lambda _ctx: False),
        Task("deux", run=lambda _ctx: PhaseMetrics()),
    )

    ctx = contexte()
    by_task = execute_tasks(tasks, ctx)

    assert by_task["une"].duration_s is not None
    assert "ecartee" not in by_task
    assert set(ctx.task_durations) == {"une", "deux"}


def test_l_executeur_ecrit_le_bilan_de_chaque_section_dans_l_ordre_des_taches(contexte, caplog):
    """Un groupe parallèle écrit ses lignes dans l'ordre des tâches. La dernière ligne d'une section la ferme. Une section aux tâches toutes silencieuses se ferme sur « Rien à faire »."""
    tasks = (
        Task(
            "issn",
            run=lambda _ctx: PhaseMetrics(report="a"),
            section="Revues",
            label="ISSN",
            parallel_group="g",
        ),
        Task(
            "titres",
            run=lambda _ctx: PhaseMetrics(report="b"),
            section="Revues",
            label="Titres",
            parallel_group="g",
        ),
        Task("types", run=lambda _ctx: PhaseMetrics(report="c"), section="Revues", label="Types"),
        Task(
            "editeurs",
            run=lambda _ctx: PhaseMetrics(),
            section="Éditeurs",
            label="Éditeurs",
            silent_when_empty=True,
        ),
    )

    with caplog.at_level(logging.INFO, logger="test"):
        execute_tasks(tasks, contexte())

    assert [record.getMessage() for record in caplog.records] == [
        "",
        "▶ Revues",
        "  ├─ ISSN : a",
        "  ├─ Titres : b",
        "  └─ Types : c",
        "",
        "▶ Éditeurs",
        "  └─ Rien à faire",
    ]


def test_la_derniere_ligne_d_une_phase_sans_section_la_ferme(contexte, caplog):
    """Les lignes d'une tâche sans section vont au seul journal. La dernière tâche exécutée ferme la phase, même suivie d'une tâche écartée."""
    tasks = (
        Task("hal", run=lambda _ctx: PhaseMetrics(new=1), label="HAL"),
        Task("openalex", run=lambda _ctx: PhaseMetrics(new=2), label="OpenAlex"),
        Task("wos", run=lambda _ctx: PhaseMetrics(), label="WoS", when=lambda _ctx: False),
    )

    with caplog.at_level(logging.INFO, logger="test"):
        execute_tasks(tasks, contexte())

    assert [(record.getMessage(), record.detail) for record in caplog.records] == [
        ("  ├─ HAL : 1 nouveau", True),
        ("  └─ OpenAlex : 2 nouveaux", True),
    ]


def test_le_bilan_d_une_tache_en_erreur_partielle_garde_ses_compteurs(contexte, caplog):
    """Un signal `harvest_error` laisse les compteurs, erreurs comprises ; une source coupée donne « interrompue »."""

    def _metriques(code: str) -> PhaseMetrics:
        metrics = PhaseMetrics(new=2, errors=1)
        metrics.signals.append({"level": "warning", "code": code, "message": ""})
        return metrics

    tasks = (
        Task("hal", run=lambda _ctx: _metriques("harvest_error"), section="Sources", label="HAL"),
        Task(
            "wos", run=lambda _ctx: _metriques("source_unavailable"), section="Sources", label="WoS"
        ),
    )

    with caplog.at_level(logging.INFO, logger="test"):
        execute_tasks(tasks, contexte())

    assert [record.getMessage() for record in caplog.records][-2:] == [
        "  ├─ HAL : 2 nouveaux, 1 erreur",
        "  └─ WoS : interrompue",
    ]


def test_un_groupe_parallele_ouvre_une_file_par_source(contexte):
    """Les tâches d'une même source s'enchaînent dans une file, dans l'ordre. Les sources s'exécutent en même temps : la première tâche de chaque source attend l'autre à une barrière."""
    barriere = threading.Barrier(2, timeout=5)
    ordre: list[str] = []

    def tache(name: str, network: str, *, attend: bool = False) -> Task:
        def run(_ctx) -> PhaseMetrics:
            if attend:
                barriere.wait()
            ordre.append(name)
            return PhaseMetrics()

        return Task(name, run=run, network=network, parallel_group="g")

    execute_tasks(
        (
            tache("hal_id", "hal", attend=True),
            tache("hal_doi", "hal"),
            tache("crossref_doi", "crossref", attend=True),
        ),
        contexte(),
    )

    assert ordre.index("hal_id") < ordre.index("hal_doi")


def test_une_etape_de_premier_niveau_donne_le_titre_de_section_de_ses_taches(contexte, caplog):
    """Les tâches d'une étape placée dans une autre écrivent sous le titre de l'étape englobante. Une tâche hors étape, ou dans une étape sans titre, garde sa `section`."""

    def tache(name: str, **kwargs) -> Task:
        return Task(name, run=lambda _ctx: PhaseMetrics(report=name), label=name, **kwargs)

    children = (
        Step(
            "revues",
            "ISSN → revues",
            (Step("issn", "ISSN → ISSN-L", (tache("sync"), tache("sudoc"))), tache("attach")),
            section="Revues",
        ),
        Step("editeurs", "noms → éditeurs", (tache("editeurs", section="Éditeurs"),)),
    )

    with caplog.at_level(logging.INFO, logger="test"):
        execute_tasks(children, contexte())

    assert [record.getMessage() for record in caplog.records] == [
        "",
        "▶ Revues",
        "  ├─ sync : sync",
        "  ├─ sudoc : sudoc",
        "  └─ attach : attach",
        "",
        "▶ Éditeurs",
        "  └─ editeurs : editeurs",
    ]


_TACHES = (
    Task("une", run=lambda _ctx: PhaseMetrics(new=1)),
    Task("deux", run=lambda _ctx: PhaseMetrics(new=2)),
)


def test_une_phase_somme_par_defaut_les_metriques_de_ses_taches(contexte):
    assert run_phase(Phase("essai", "Essai", _TACHES, Block.ENTITIES), contexte()).new == 3


def test_une_phase_assemble_ses_metriques_par_sa_fonction(contexte):
    phase = Phase(
        "essai", "Essai", _TACHES, Block.ENTITIES, assemble=lambda by_task: by_task["deux"]
    )

    assert run_phase(phase, contexte()).new == 2


def test_une_precondition_non_remplie_arrete_la_phase_avant_ses_taches(contexte):
    appels: list[str] = []

    def check(_ctx) -> None:
        raise RuntimeError("périmètre vide")

    tache = Task("une", run=lambda _ctx: appels.append("une") or PhaseMetrics())
    with pytest.raises(RuntimeError, match="périmètre vide"):
        run_phase(Phase("essai", "Essai", (tache,), Block.ENTITIES, check=check), contexte())

    assert appels == []


def test_une_phase_ecartee_par_sa_condition_le_signale_sans_executer_ses_taches(contexte, caplog):
    """La condition reçoit le contexte de la phase, comme celle d'une tâche."""
    appels: list[str] = []
    tache = Task("une", run=lambda _ctx: appels.append("une") or PhaseMetrics(new=1))
    phase = Phase(
        "essai",
        "Essai",
        (tache,),
        Block.HARVESTING,
        when=lambda ctx: ctx.options.policy.fetch_stale,
    )

    with caplog.at_level(logging.INFO, logger="test"):
        metrics = run_phase(phase, contexte(mode="daily"))

    assert metrics == PhaseMetrics()
    assert appels == []
    assert [record.getMessage() for record in caplog.records] == ["  └─ Sautée"]


def test_une_phase_de_moissonnage_ecrit_le_total_de_plusieurs_taches_executees(contexte, caplog):
    """Le total d'une seule tâche exécutée redirait sa ligne de bilan : la phase l'omet."""
    une_seule = (
        _TACHES[0],
        Task("ecartee", run=lambda _ctx: PhaseMetrics(), when=lambda _ctx: False),
    )

    with caplog.at_level(logging.INFO, logger="test"):
        run_phase(Phase("essai", "Essai", une_seule, Block.HARVESTING), contexte())
        assert not any(r.getMessage().startswith("Total") for r in caplog.records)
        run_phase(Phase("essai", "Essai", _TACHES, Block.HARVESTING), contexte())

    assert caplog.records[-1].getMessage() == "Total : 3 nouveaux"
