"""Orchestrateur unique de la phase personnes.

Quatre tâches (`pipeline.graph`). Les quatre premières étapes forment la tâche `persons.resolve`, sur **une seule** transaction : l'arbitrage des identifiants détache des contributions sources, la cascade les re-résout, et le détachement cross-source final retire les liens sans appui. Un échec en cours de tâche annule l'ensemble. `populate` (tâche `persons.populate_person_name_forms`), `purge` (tâche `persons.purge`) et `resolve_groups` (tâche `persons.resolve_groups`) ont chacun leur transaction.

1. **enforce** — réapplique les épinglages admin (`confirmed_source_contributions`, must-link) : entrée fixe reposée avant toute dérivation. Les contributions sources hors groupe, non épinglées, perdent leur personne.
2. **identifiants mal placés et conflits d'identifiant** — sur un même consensus des porteurs, neutralise les identifiants mal placés, puis tranche les conflits d'attribution ; les contributions sources rattachées par un identifiant neutralisé ou capté repassent à NULL.
3. **cascade** — un seul balayage en deux passes internes, sur des index vivants partagés : `match` (rattachement ferme + cross-source), puis `create` (rattrapage cross-source + création des inconnues).
4. **détachement cross-source** — les liens cross-source restés sans appui ferme repassent à NULL.
5. **populate** — régénère les formes de nom canoniques.
6. **purge** — re-orpheline les formes devenues ambiguës après régénération, supprime les attributions d'identifiant automatiques qu'aucune contribution source ne contient, et supprime les personnes vidées.
7. **resolve_groups** — rattache à une personne existante les groupes de contributions sources sans personne (`pipeline.transformation.persons.groups`).

Les publications hors scope sont écartées (`domain/publications/scope`).

`open_tx` gère le commit : `managed_transaction` commite en sortie de bloc si succès, rollback sinon.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_file_logger
from infrastructure.repositories.person_repository import (
    PgPersonRepository,
)
from infrastructure.sql_fragments import (
    DETACHED_SOURCE_CONTRIBUTION,
    person_source_contribution,
    pinned,
)
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.persons.cascade import run_cascade
from pipeline.transformation.persons.groups import resolve_groups
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from pipeline.transformation.persons.metrics import build_metrics
from pipeline.transformation.persons.populate_person_name_forms import populate
from pipeline.transformation.persons.purge import purge
from pipeline.transformation.persons.store import PersonsStore


def enforce_confirmed_source_contributions(conn: Connection) -> int:
    """Réapplique les épinglages admin (`confirmed_source_contributions`, must-link) : pose `source_contributions.person_id` sur la personne épinglée là où il diverge. Retourne le nombre de contributions sources recalées."""
    return conn.execute(
        text("""
            UPDATE source_contributions sc
            SET person_id = ca.person_id
            FROM confirmed_source_contributions ca
            WHERE ca.source_contribution_id = sc.id
              AND sc.person_id IS DISTINCT FROM ca.person_id
        """)
    ).rowcount


def detach_ungrouped(conn: Connection) -> int:
    """Détache de leur personne les contributions sources hors groupe (`person_source_contribution`), sauf épinglage. Rend le nombre de contributions sources détachées."""
    return conn.execute(
        text(f"""
            UPDATE source_contributions sc
            SET {DETACHED_SOURCE_CONTRIBUTION}
            WHERE sc.person_id IS NOT NULL
              AND NOT {person_source_contribution("sc")}
              AND NOT {pinned("sc.id")}
        """)
    ).rowcount


@dataclass(frozen=True)
class PersonsPhase:
    repo_factory: Callable[[Connection], PgPersonRepository]
    orphans_log: logging.Logger | None = None

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les quatre tâches de la phase personnes et rend ses métriques.

        `orphans_log` reçoit le motif de chaque contribution source du périmètre restée sans personne (`run_cascade`).
        """
        by_task = run_tasks(
            "persons",
            {
                "persons.resolve": TaskStep(self._resolve),
                "persons.populate_person_name_forms": TaskStep(
                    self._populate,
                    section="Rafraîchissement des formes de nom associées aux personnes",
                ),
                "persons.purge": TaskStep(self._purge),
                "persons.resolve_groups": TaskStep(
                    self._resolve_groups,
                    section="Rattachement des groupes de contributions sources",
                ),
            },
            ctx,
        )
        metrics = by_task["persons.resolve"]
        purge_counts = by_task["persons.purge"].extras
        name_form_counts = by_task["persons.populate_person_name_forms"].extras
        summary = metrics.details["summary"]
        assert isinstance(summary, dict)
        summary["reorphaned_nominal"] = purge_counts.get("reorphaned", 0)
        summary["detached_out_of_perimeter"] = purge_counts.get("detached_out_of_perimeter", 0)
        summary["deleted_empty_persons"] = purge_counts.get("deleted_persons", 0)
        for key, count in name_form_counts.items():
            summary[f"name_forms_{key}"] = count
        return metrics

    def _resolve(self, ctx: PhaseContext) -> PhaseMetrics:
        """Épinglages, détachement des contributions sources hors groupe, arbitrage des identifiants, cascade et détachement cross-source, sur une transaction."""
        logger = ctx.logger
        with ctx.open_tx() as conn:
            repo = self.repo_factory(conn)

            n_enforced = enforce_confirmed_source_contributions(conn)
            if n_enforced:
                step(logger, "Épinglages réappliqués")
                logger.info(
                    "%s%s",
                    LAST_BRANCH,
                    quantity(
                        n_enforced, "contribution source recalée", "contributions sources recalées"
                    ),
                )

            n_ungrouped = detach_ungrouped(conn)
            if n_ungrouped:
                step(logger, "Contributions sources hors groupe")
                logger.info(
                    "%s%s de leur personne",
                    LAST_BRANCH,
                    quantity(
                        n_ungrouped,
                        "contribution source détachée",
                        "contributions sources détachées",
                    ),
                )

            arbitration = arbitrate_identifier_conflicts(conn, logger, repo=repo)
            cascade_result = run_cascade(
                conn,
                logger,
                repo=repo,
                orphans_log=self.orphans_log,
            )

            # Les contributions sources cross-source qu'aucune passe n'a re-résolues ont perdu leur ancre ferme → détachées.
            stale = sorted(
                cascade_result.cross_source_candidate_ids - cascade_result.resolved_cross_source_ids
            )
            cross_source_detached = PersonsStore(conn).detach_source_contributions(stale)

        return build_metrics(
            cascade_result,
            transferred=arbitration["transferred"],
            cross_source_detached=cross_source_detached,
        )

    def _populate(self, ctx: PhaseContext) -> PhaseMetrics:
        t0 = time.perf_counter()
        with (
            ctx.open_tx() as conn,
            waiting(f"{LAST_BRANCH}rafraîchissement en cours", ctx.logger) as line,
        ):
            counts = populate(conn)
            line.conclude(f"{LAST_BRANCH}Terminé en {time.perf_counter() - t0:.1f}s")
        return PhaseMetrics(extras=counts._asdict())

    def _purge(self, ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            counts = purge(conn)
        return PhaseMetrics(extras=dict(counts))

    def _resolve_groups(self, ctx: PhaseContext) -> PhaseMetrics:
        with (
            ctx.open_tx() as conn,
            waiting(f"{LAST_BRANCH}décision des groupes sans personne", ctx.logger) as line,
        ):
            counts = resolve_groups(conn)
            line.conclude(
                f"{LAST_BRANCH}{quantity(counts['written'], 'groupe rattaché', 'groupes rattachés')}"
                f" sur {quantity(counts['groups'], 'groupe décidé', 'groupes décidés')}"
            )
        return PhaseMetrics(extras=counts)


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return PersonsPhase(
        repo_factory=PgPersonRepository,
        orphans_log=setup_file_logger("persons_orphelines", str(PROJECT_ROOT / "logs")),
    )
