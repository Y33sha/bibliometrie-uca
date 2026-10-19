"""Orchestrateur unique de la phase personnes.

Trois nœuds (`pipeline.graph`). Les quatre premières étapes forment le nœud `persons.resolve`, sur **une seule** transaction : l'arbitrage des identifiants détache des signatures, la cascade les re-résout, et le détachement cross-source final retire les liens sans appui. Un échec en cours de nœud annule l'ensemble. `populate` (nœud `persons.populate_person_name_forms`) et `purge` (nœud `persons.purge`) ont chacun leur transaction.

1. **enforce** — réapplique les épinglages admin (`confirmed_authorships`, must-link) : entrée fixe reposée avant toute dérivation. Les doublons d'auteur d'une notice (`duplicate_of`), non épinglés, perdent leur personne.
2. **identifiants mal placés et conflits d'identifiant** — sur un même consensus des porteurs, neutralise les identifiants mal placés, puis tranche les conflits d'attribution ; les signatures rattachées par un identifiant neutralisé ou capté repassent à NULL.
3. **cascade** — un seul balayage en deux passes internes, sur des index vivants partagés : `match` (rattachement ferme + cross-source), puis `create` (rattrapage cross-source + création des inconnues).
4. **détachement cross-source** — les liens cross-source restés sans appui ferme repassent à NULL.
5. **populate** — régénère les formes de nom canoniques.
6. **purge** — re-orpheline les formes devenues ambiguës après régénération, supprime les attributions d'identifiant automatiques qu'aucune signature ne porte, et supprime les personnes vidées.

Le rattachement est ordre-indépendant : le résultat ne dépend pas de la séquence d'ingestion des sources — propriété de l'algorithme (recompute complet, arbitrage par consensus, lectures d'agrégat sur le snapshot), non de la transaction.

`open_tx` gère le commit : `managed_transaction` commite en sortie de bloc si succès, rollback sinon.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection

from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_file_logger
from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, accord, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.persons.arbitrate_identifiers import arbitrate_identifier_conflicts
from pipeline.transformation.persons.cascade import run_cascade
from pipeline.transformation.persons.matching import PersonsMatchingQueries
from pipeline.transformation.persons.metrics import build_metrics
from pipeline.transformation.persons.name_forms import PersonNameFormsQueries
from pipeline.transformation.persons.person_writes import PersonWrites
from pipeline.transformation.persons.populate_person_name_forms import populate
from pipeline.transformation.persons.purge import purge


@dataclass(frozen=True)
class PersonsPhase:
    persons_queries: PersonsMatchingQueries
    name_forms_queries: PersonNameFormsQueries
    writes_factory: Callable[[Connection], PersonWrites]
    orphans_log: logging.Logger | None = None

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les trois nœuds de la phase personnes et rend ses métriques.

        `orphans_log` reçoit le motif de chaque signature du périmètre restée sans personne (`run_cascade`).
        """
        by_node = run_nodes(
            "persons",
            {
                "persons.resolve": NodeStep(self._resolve),
                "persons.populate_person_name_forms": NodeStep(
                    self._populate,
                    section="Rafraîchissement des formes de nom associées aux personnes",
                ),
                "persons.purge": NodeStep(self._purge),
            },
            ctx,
        )
        metrics = by_node["persons.resolve"]
        purge_counts = by_node["persons.purge"].extras
        summary = metrics.details["summary"]
        assert isinstance(summary, dict)
        summary["reorphaned_nominal"] = purge_counts.get("reorphaned", 0)
        summary["deleted_empty_persons"] = purge_counts.get("deleted_persons", 0)
        metrics.resume = ""
        return metrics

    def _resolve(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        """Épinglages, détachement des copies, arbitrage des identifiants, cascade et détachement cross-source, sur une transaction."""
        persons_queries, logger = self.persons_queries, ctx.logger
        with ctx.open_tx() as conn:
            writes = self.writes_factory(conn)

            n_enforced = persons_queries.enforce_confirmed_authorships(conn)
            if n_enforced:
                etape(logger, "Épinglages réappliqués")
                logger.info(
                    "%s%s",
                    DERNIERE_BRANCHE,
                    accord(n_enforced, "signature recalée", "signatures recalées"),
                )

            n_copies = persons_queries.detach_copies(conn)
            if n_copies:
                etape(logger, "Auteurs en double dans la liste d'une notice")
                logger.info(
                    "%s%s de leur personne",
                    DERNIERE_BRANCHE,
                    accord(n_copies, "doublon détaché", "doublons détachés"),
                )

            arbitration = arbitrate_identifier_conflicts(
                conn, persons_queries, logger, writes=writes
            )
            cascade_result = run_cascade(
                conn,
                persons_queries,
                logger,
                writes=writes,
                orphans_log=self.orphans_log,
            )

            # Les signatures cross-source qu'aucune passe n'a re-résolues ont perdu leur ancre ferme → détachées.
            stale = sorted(
                cascade_result.cross_source_candidate_ids - cascade_result.resolved_cross_source_ids
            )
            cross_source_detached = persons_queries.detach_source_authorships(conn, stale)

        return build_metrics(
            cascade_result,
            transferred=arbitration["transferred"],
            cross_source_detached=cross_source_detached,
        )

    def _populate(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        t0 = time.perf_counter()
        with (
            ctx.open_tx() as conn,
            attente(f"{DERNIERE_BRANCHE}rafraîchissement en cours", ctx.logger) as ligne,
        ):
            populate(conn, self.name_forms_queries, ctx.logger)
            ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")
        return PhaseMetrics()

    def _purge(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            counts = purge(conn, self.persons_queries, ctx.logger)
        return PhaseMetrics(extras=dict(counts))


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Rattachement des signatures aux personnes, et création des personnes inconnues.

    Une transaction enchaîne la réapplication des épinglages posés par l'administration, l'arbitrage des identifiants, le rattachement des signatures aux personnes connues et la création des personnes pour les signatures restantes. Suivent la régénération des formes de nom, puis la purge des formes devenues ambiguës et des personnes vidées, chacune dans sa transaction. Les publications hors scope sont écartées (`domain/publications/scope`).
    """
    from pipeline.transformation.persons.matching import PersonsMatchingQueries
    from pipeline.transformation.persons.name_forms import PersonNameFormsQueries

    return PersonsPhase(
        PersonsMatchingQueries(),
        PersonNameFormsQueries(),
        writes_factory=PersonWrites,
        orphans_log=setup_file_logger("persons_orphelines", str(PROJECT_ROOT / "logs")),
    )
